# -*- coding: utf-8 -*-
"""Cache de campos de detalhe entre execuções (sem rede)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

import pipeline  # noqa: E402
import storage  # noqa: E402
from sources import _detail_cache as cache  # noqa: E402
from sources import sankhya_senior  # noqa: E402

T0 = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
SENIOR_PAGES = {
    0: {"totalPages": 1, "contents": [
        {"vacancy": {"id": "a", "title": "Analista Pleno", "jobModel": ["IN_PERSON"],
                     "localization": {"city": "Blumenau", "country": "Brasil"},
                     "publication": {"startDate": "2026-11-01"}},
         "company": {"name": "Senior", "sector": "Tecnologia"}},
        {"vacancy": {"id": "b", "title": "Suporte", "jobModel": ["IN_PERSON"],
                     "localization": {"city": "Joinville", "country": "Brasil"}},
         "company": {"name": "Empresa", "sector": "Operações"}},
    ]},
}
SENIOR_DETAILS = {
    "a": {"jobModel": ["Remote"], "hiringRegime": "PJ", "experience": ["Pleno"],
          "pcd": True, "localization": {"city": "Blumenau", "country": "Brasil"},
          "description": "texto longo que não pode ir para o cache"},
    "b": {"jobModel": ["Hybrid"], "hiringRegime": "CLT", "experience": [], "pcd": False},
}


class DetailCacheTests(unittest.TestCase):
    def setUp(self):
        cache.stop()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "jobs.db")

    def tearDown(self):
        cache.stop()
        self.tmp.cleanup()

    def _persist(self, now, entries):
        cache.start(self.db, now=now)
        for (source, native_id), payload in entries.items():
            cache.put(source, native_id, payload)
        conn = storage.connect(self.db)
        try:
            stored = cache.persist(conn)
        finally:
            conn.close()
        cache.stop()
        return stored

    def test_inactive_by_default(self):
        self.assertFalse(cache.is_active())
        cache.put("senior", "1", {"pcd": True})
        self.assertIsNone(cache.get("senior", "1"))
        self.assertEqual(cache.summary(), {})

    def test_round_trip_strips_descriptions(self):
        stored = self._persist(T0, {("senior", "1"): {"pcd": True, "description": "x",
                                                      "roleDescription": "y"}})
        self.assertEqual(stored, 1)
        self.assertEqual(cache.start(self.db, now=T0 + timedelta(hours=1)), 1)
        self.assertEqual(cache.get("senior", "1"), {"pcd": True})
        self.assertIsNone(cache.get("senior", "2"))
        self.assertEqual(cache.summary(), {"senior": {"hits": 1, "misses": 1}})

    def test_entries_expire_after_spread_ttl(self):
        self._persist(T0, {("senior", "1"): {"pcd": True}})
        ttl = timedelta(days=cache.DEFAULT_TTL_DAYS)
        self.assertEqual(cache.start(self.db, now=T0 + ttl * 0.49), 1)
        self.assertEqual(cache.start(self.db, now=T0 + ttl * 1.5), 0)

    def test_zero_ttl_disables_cache(self):
        self._persist(T0, {("senior", "1"): {"pcd": True}})
        with patch.dict(os.environ, {cache.TTL_ENV: "0"}):
            self.assertEqual(cache.start(self.db, now=T0), 0)
            self.assertFalse(cache.is_active())
            self.assertIsNone(cache.get("senior", "1"))

    def test_invalid_ttl_falls_back_to_default(self):
        with patch.dict(os.environ, {cache.TTL_ENV: "abc"}):
            self.assertEqual(cache.ttl_days(), cache.DEFAULT_TTL_DAYS)
        with patch.dict(os.environ, {cache.TTL_ENV: "999"}):
            self.assertEqual(cache.ttl_days(), cache.MAX_TTL_DAYS)

    def test_missing_database_or_table_is_an_empty_cache(self):
        self.assertEqual(cache.start(os.path.join(self.tmp.name, "nao-existe.db")), 0)
        self.assertTrue(cache.is_active())
        legacy = os.path.join(self.tmp.name, "antigo.db")
        import sqlite3
        sqlite3.connect(legacy).close()
        self.assertEqual(cache.start(legacy), 0)

    def test_persist_prunes_entries_older_than_retention(self):
        conn = storage.connect(self.db)
        old = (T0 - timedelta(days=cache.RETENTION_DAYS + 1)).isoformat()
        conn.execute("INSERT INTO detail_cache VALUES ('senior', 'velho', ?, ?)",
                     (json.dumps({"pcd": False}), old))
        conn.commit()
        conn.close()
        self._persist(T0, {("senior", "novo"): {"pcd": True}})
        conn = storage.connect(self.db)
        ids = [row[0] for row in conn.execute("SELECT native_id FROM detail_cache")]
        conn.close()
        self.assertEqual(ids, ["novo"])


class SeniorDetailReuseTests(unittest.TestCase):
    def setUp(self):
        cache.stop()

    def tearDown(self):
        cache.stop()

    def _rows(self):
        calls = []

        def detail(native_id):
            calls.append(native_id)
            return dict(SENIOR_DETAILS[native_id])

        with patch.object(sankhya_senior, "_senior_page", side_effect=lambda page: SENIOR_PAGES[page]), \
             patch.object(sankhya_senior, "_senior_detail_vacancy", side_effect=detail):
            rows = sankhya_senior._senior_rows()
        return rows, calls

    def test_cached_vacancies_skip_the_detail_request_with_identical_rows(self):
        baseline, baseline_calls = self._rows()  # cache inativo: comportamento anterior
        self.assertEqual(sorted(baseline_calls), ["a", "b"])

        with tempfile.TemporaryDirectory() as tmp:
            cache.start(os.path.join(tmp, "jobs.db"), now=T0)
            first, first_calls = self._rows()
            self.assertEqual(sorted(first_calls), ["a", "b"])
            self.assertEqual(cache.summary()["senior"], {"misses": 2, "stored": 2})
            second, second_calls = self._rows()

        self.assertEqual(second_calls, [])
        self.assertEqual(first, baseline)
        self.assertEqual(second, baseline)
        self.assertEqual(second[0]["work_model"], "remote")
        self.assertEqual(second[0]["contract_types"], ["PJ"])
        self.assertTrue(second[0]["pcd"])

    def test_empty_detail_is_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache.start(os.path.join(tmp, "jobs.db"), now=T0)
            with patch.object(sankhya_senior, "_senior_detail_vacancy", return_value={}):
                self.assertEqual(sankhya_senior._senior_detail_fields("x"), {})
            self.assertIsNone(cache.get("senior", "x"))


class DetailSummaryTests(unittest.TestCase):
    def test_reuse_text_and_summary_line(self):
        stats = {"senior": {"hits": 3100, "misses": 132, "stored": 132}}
        self.assertEqual(pipeline._detail_reuse_text(stats), "senior 3.100 de 3.232 (96%)")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "summary.md")
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": path}):
                pipeline.write_actions_summary([], {"total": 1.0}, 10, [], detail_stats=stats)
                pipeline.write_actions_summary([], {"total": 1.0}, 10, [])
            text = Path(path).read_text(encoding="utf-8")
        self.assertEqual(text.count("Detalhes reaproveitados do cache:** senior 3.100 de 3.232 (96%)"), 1)


if __name__ == "__main__":
    unittest.main()
