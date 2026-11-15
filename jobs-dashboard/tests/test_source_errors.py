# -*- coding: utf-8 -*-
"""Classificação de falhas das fontes e seu registro no pipeline (sem rede)."""
import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

import pipeline  # noqa: E402
from sources import _errors as errors  # noqa: E402
from sources import _http  # noqa: E402


def _http_error(code):
    return urllib.error.HTTPError("https://example.test", code, "erro", Message(), None)


def _raise(error):
    def fetch():
        raise error
    return fetch


class ClassifyErrorTests(unittest.TestCase):
    def test_http_codes(self):
        cases = {
            401: errors.BLOCKED, 403: errors.BLOCKED, 429: errors.BLOCKED,
            451: errors.BLOCKED, 500: errors.UNAVAILABLE, 503: errors.UNAVAILABLE,
            404: errors.FORMAT, 410: errors.FORMAT, 400: errors.OTHER,
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                self.assertEqual(errors.classify_error(_http_error(code)), expected)

    def test_transport_errors(self):
        self.assertEqual(errors.classify_error(TimeoutError("lento")), errors.TIMEOUT)
        self.assertEqual(
            errors.classify_error(urllib.error.URLError(TimeoutError("lento"))),
            errors.TIMEOUT,
        )
        self.assertEqual(
            errors.classify_error(urllib.error.URLError(socket.gaierror("dns"))),
            errors.UNAVAILABLE,
        )
        self.assertEqual(errors.classify_error(urllib.error.URLError("x")), errors.UNAVAILABLE)
        self.assertEqual(errors.classify_error(ConnectionResetError()), errors.UNAVAILABLE)

    def test_format_errors(self):
        for error in (json.JSONDecodeError("x", "doc", 0), KeyError("jobs"),
                      TypeError("lista"), IndexError()):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(errors.classify_error(error), errors.FORMAT)

    def test_cause_chain_is_followed(self):
        try:
            try:
                raise _http_error(403)
            except urllib.error.HTTPError as cause:
                raise RuntimeError("Greenhouse board failed") from cause
        except RuntimeError as wrapped:
            self.assertEqual(errors.classify_error(wrapped), errors.BLOCKED)

    def test_message_heuristics_and_named_timeouts(self):
        self.assertEqual(
            errors.classify_error(RuntimeError("Gupy MCP HTTP 429: limite")), errors.BLOCKED
        )
        self.assertEqual(
            errors.classify_error(RuntimeError("Cloudflare challenge")), errors.BLOCKED
        )
        self.assertEqual(
            errors.classify_error(RuntimeError("HTTP Error 502: Bad Gateway")),
            errors.UNAVAILABLE,
        )

        class TimeoutException(Exception):
            pass

        self.assertEqual(errors.classify_error(TimeoutException()), errors.TIMEOUT)
        self.assertEqual(errors.classify_error(RuntimeError("algo")), errors.OTHER)

    def test_exhausted_keeps_message_and_runtime_error_compatibility(self):
        error = errors.exhausted("get_json failed after 3 attempts", _http_error(403))
        self.assertIsInstance(error, errors.SourceBlocked)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), "get_json failed after 3 attempts")
        self.assertIsInstance(
            errors.exhausted("x", TimeoutError()), errors.SourceUnavailable
        )
        self.assertIs(type(errors.exhausted("x", RuntimeError("?"))), errors.SourceError)

    def test_http_helper_raises_typed_error_after_retries(self):
        with patch.object(_http.urllib.request, "urlopen", side_effect=_http_error(503)), \
             patch.object(_http.time, "sleep"):
            with self.assertRaises(errors.SourceUnavailable) as ctx:
                _http.get_json("https://example.test", retries=2)
        self.assertIn("get_json failed after 2 attempts", str(ctx.exception))
        self.assertEqual(errors.classify_error(ctx.exception), errors.UNAVAILABLE)


class PipelineCategoryTests(unittest.TestCase):
    def test_collect_source_records_category_of_exception(self):
        result = pipeline._collect_source(0, "fonte", _raise(_http_error(403)))
        self.assertEqual(result["error_category"], errors.BLOCKED)

    def test_adapter_returning_object_is_format_error(self):
        result = pipeline._collect_source(0, "fonte", lambda: {"jobs": []})
        self.assertEqual(result["error_category"], errors.FORMAT)

    def test_unexpected_empty_and_invalid_rows(self):
        name = sorted(pipeline.NONEMPTY_SOURCES)[0]
        empty = pipeline._collect_source(0, name, lambda: [])
        self.assertEqual(empty["error_category"], errors.UNEXPECTED_EMPTY)
        invalid = pipeline._collect_source(
            0, "fonte", lambda: [{"title": "", "url": "https://example.test/1"}]
        )
        self.assertEqual(invalid["error_category"], errors.INVALID_ROWS)

    def test_successful_source_has_no_category(self):
        result = pipeline._collect_source(0, "fonte", lambda: [])
        self.assertEqual(result["error"], "")
        self.assertEqual(result["error_category"], "")

    def test_collect_exposes_category_in_metrics(self):
        _rows, failed, metrics = pipeline.collect(
            [("fonte", _raise(TimeoutError("lento")))], checkpoint_dir=None
        )
        self.assertEqual(failed, ["fonte"])
        self.assertEqual(metrics[0]["error_category"], errors.TIMEOUT)

    def test_summary_shows_categories(self):
        metrics = [
            {"name": "gupy", "status": "falha", "error_category": errors.BLOCKED,
             "jobs": 0, "seconds": 3.0},
            {"name": "vagascom", "status": "ok", "error_category": "",
             "jobs": 10, "seconds": 1.0},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "summary.md")
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": path}):
                pipeline.write_actions_summary(metrics, {"total": 1.0}, 10, ["gupy"])
            text = Path(path).read_text(encoding="utf-8")
        self.assertIn("Fontes com falha:** gupy (bloqueio)", text)
        self.assertIn("Falhas por categoria:** bloqueio 1", text)
        self.assertIn("| gupy | falha (bloqueio) | 0 | 3.0s |", text)
        self.assertIn("| vagascom | ok | 10 | 1.0s |", text)


if __name__ == "__main__":
    unittest.main()
