# -*- coding: utf-8 -*-
"""Retentativas do cliente HTTP compartilhado (sem rede)."""
import sys
import unittest
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import _http  # noqa: E402


def _http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.test", code, "erro", headers, None)


def _ok_response(body=b'{"ok": true}'):
    response = MagicMock()
    response.status = 200
    response.read.return_value = body
    response.headers = {}
    response.__enter__.return_value = response
    return response


class RetryDelayTests(unittest.TestCase):
    def test_exponential_steps_with_equal_jitter_bounds(self):
        for attempt, step in ((1, 2.0), (2, 4.0), (3, 8.0)):
            with self.subTest(attempt=attempt):
                low = _http.retry_delay(attempt, 2.0, rand=lambda: 0.0)
                high = _http.retry_delay(attempt, 2.0, rand=lambda: 1.0)
                self.assertEqual(low, step / 2)
                self.assertEqual(high, step)

    def test_mean_wait_is_below_previous_linear_schedule(self):
        # Antes: 2s + 4s fixos para retries=3. Agora: média de 0,75 desse total.
        mean_total = sum(_http.retry_delay(a, 2.0, rand=lambda: 0.5) for a in (1, 2))
        self.assertEqual(mean_total, 4.5)

    def test_backoff_step_is_capped(self):
        delay = _http.retry_delay(10, 2.0, rand=lambda: 1.0)
        self.assertEqual(delay, _http.MAX_BACKOFF_SECONDS)

    def test_zero_backoff_never_waits(self):
        self.assertEqual(_http.retry_delay(3, 0, rand=lambda: 1.0), 0.0)

    def test_retry_after_seconds_wins_when_longer(self):
        delay = _http.retry_delay(1, 2.0, _http_error(429, "12"), rand=lambda: 0.0)
        self.assertEqual(delay, 12.0)

    def test_retry_after_is_capped(self):
        delay = _http.retry_delay(1, 2.0, _http_error(503, "600"), rand=lambda: 0.0)
        self.assertEqual(delay, _http.MAX_RETRY_AFTER_SECONDS)

    def test_short_retry_after_does_not_shorten_backoff(self):
        delay = _http.retry_delay(2, 2.0, _http_error(429, "1"), rand=lambda: 0.0)
        self.assertEqual(delay, 2.0)

    def test_retry_after_http_date(self):
        now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
        error = _http_error(429, "Sun, 15 Nov 2026 12:00:20 GMT")
        self.assertEqual(_http.retry_after_seconds(error, now=now), 20.0)

    def test_retry_after_ignored_for_other_codes_and_garbage(self):
        self.assertIsNone(_http.retry_after_seconds(_http_error(500, "10")))
        self.assertIsNone(_http.retry_after_seconds(_http_error(429, "logo")))
        self.assertIsNone(_http.retry_after_seconds(_http_error(429, "nan")))
        self.assertIsNone(_http.retry_after_seconds(_http_error(429)))
        self.assertIsNone(_http.retry_after_seconds(TimeoutError()))


class HelperIntegrationTests(unittest.TestCase):
    def test_get_json_honours_retry_after_then_succeeds(self):
        with patch.object(_http.urllib.request, "urlopen",
                          side_effect=[_http_error(429, "7"), _ok_response()]), \
             patch.object(_http.time, "sleep") as sleep, \
             patch.object(_http.random, "random", return_value=0.0):
            self.assertEqual(_http.get_json("https://example.test"), {"ok": True})
        sleep.assert_called_once_with(7.0)

    def test_permanent_client_error_is_not_retried(self):
        with patch.object(_http.urllib.request, "urlopen",
                          side_effect=_http_error(404)), \
             patch.object(_http.time, "sleep") as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                _http.get_text("https://example.test")
        sleep.assert_not_called()

    def test_server_errors_use_growing_jittered_pauses(self):
        with patch.object(_http.urllib.request, "urlopen",
                          side_effect=[_http_error(502), _http_error(502), _ok_response()]), \
             patch.object(_http.time, "sleep") as sleep, \
             patch.object(_http.random, "random", return_value=1.0):
            _http.post_json("https://example.test", {"q": 1})
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2.0, 4.0])

    def test_exhausted_retries_raise_with_last_error(self):
        with patch.object(_http.urllib.request, "urlopen",
                          side_effect=TimeoutError("lento")), \
             patch.object(_http.time, "sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                _http.post_form_json("https://example.test", {"a": 1}, retries=2)
        self.assertIsInstance(ctx.exception.__cause__, TimeoutError)


if __name__ == "__main__":
    unittest.main()
