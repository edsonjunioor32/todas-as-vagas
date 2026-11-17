# -*- coding: utf-8 -*-
"""Adaptador Empregare via MCP oficial (sem rede)."""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

import storage  # noqa: E402
from sources import empregare  # noqa: E402
from sources._errors import SourceBlocked, SourceFormatError  # noqa: E402


def _sse(payload, total_pages=2, page=1):
    inner = {"sucesso": True, "total": 3, "pagina": page, "totalPaginas": total_pages, "vagas": payload}
    envelope = {"jsonrpc": "2.0", "id": page, "result": {
        "content": [{"type": "text", "text": json.dumps(inner, ensure_ascii=False)}]}}
    return f"event: message\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n".encode("utf-8")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


PAGE1 = [
    {"id": 10, "cargo": "Analista de Dados", "salario": "R$ 5.000,00 a R$ 7.000,00",
     "empresa": "ACME", "pcd": True, "remoto": "Remoto", "cidades": ["São Paulo, SP, BR"]},
    {"id": 11, "cargo": "Estoquista", "salario": "", "empresa": "Loja",
     "pcd": False, "remoto": "Presencial", "cidades": ["Uruaçu, GO, BR"]},
]
PAGE2 = [
    {"id": 11, "cargo": "Estoquista", "salario": "", "empresa": "Loja",
     "pcd": False, "remoto": "Presencial", "cidades": ["Uruaçu, GO, BR"]},
    {"id": 12, "cargo": "Vendedor", "salario": "", "empresa": "Loja",
     "pcd": False, "remoto": "Híbrido", "cidades": []},
]


class EmpregareMcpTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(empregare.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def _serve(self, *bodies):
        calls = []

        def fake(req, timeout=None):
            calls.append(json.loads(req.data))
            body = bodies[len(calls) - 1]
            if isinstance(body, Exception):
                raise body
            return _Resp(body)

        return calls, patch.object(empregare.urllib.request, "urlopen", side_effect=fake)

    def test_fetch_walks_all_pages_sequentially_and_dedupes(self):
        calls, p = self._serve(_sse(PAGE1, page=1), _sse(PAGE2, page=2))
        with p:
            rows = empregare.fetch()
        self.assertEqual([c["params"]["arguments"]["pagina"] for c in calls], [1, 2])
        self.assertTrue(all(c["params"]["arguments"]["itensPagina"] == 50 for c in calls))
        self.assertEqual(sorted(r["native_id"] for r in rows), ["10", "11", "12"])
        first = next(r for r in rows if r["native_id"] == "10")
        self.assertEqual(first["title"], "Analista de Dados")
        self.assertEqual(first["url"], "https://www.empregare.com/v10")
        self.assertEqual((first["salary_min"], first["salary_max"], first["salary_currency"]), (5000.0, 7000.0, "BRL"))
        self.assertTrue(first["pcd"])
        self.assertEqual(first["work_model"], "remote")
        self.assertTrue(all(r["market"] == "BR" for r in rows))

    def test_rate_limit_is_retried_then_succeeds(self):
        limited = urllib.error.HTTPError(empregare.ENDPOINT, 429, "Too Many Requests", {"Retry-After": "5"}, None)
        calls, p = self._serve(limited, _sse(PAGE1, total_pages=1))
        with p:
            rows = empregare.fetch()
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(rows), 2)

    def test_persistent_rate_limit_raises_typed_blocked_error(self):
        limited = urllib.error.HTTPError(empregare.ENDPOINT, 429, "Too Many Requests", {}, None)
        _, p = self._serve(*([limited] * empregare.RETRIES))
        with p, self.assertRaises(SourceBlocked):
            empregare.fetch()

    def test_jsonrpc_error_is_format_error(self):
        body = b'{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"bad"}}'
        _, p = self._serve(body)
        with p, self.assertRaises(SourceFormatError):
            empregare.fetch()


class UpsertKeepsKnownDatesTests(unittest.TestCase):
    def test_empty_dates_do_not_erase_stored_dates(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        conn = storage.connect(str(Path(tmp.name) / "jobs.db"))
        self.addCleanup(conn.close)
        base = empregare.job("empregare", 99, "Cargo", "Empresa", "https://www.empregare.com/v99",
                             published_date="2026-11-01", expires_date="2026-12-01")
        storage.upsert(conn, [base], today="2026-11-05")
        refreshed = dict(base, published_date="", expires_date="")
        storage.upsert(conn, [refreshed], today="2026-11-16")
        row = conn.execute(
            "SELECT published_date, expires_date, last_seen_date FROM jobs WHERE job_uid='empregare:99'").fetchone()
        self.assertEqual(row, ("2026-11-01", "2026-12-01", "2026-11-16"))


if __name__ == "__main__":
    unittest.main()
