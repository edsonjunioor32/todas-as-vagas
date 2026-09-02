# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

import merge_dynamic_portals as merge  # noqa: E402
import pipeline  # noqa: E402
import storage  # noqa: E402


def sample(source, native_id, *, published="2026-08-25", description=""):
    return {
        "source": source,
        "native_id": native_id,
        "title": "Vaga de teste",
        "company": "Empresa de teste",
        "url": f"https://example.com/{source}/{native_id}",
        "work_model": "remote",
        "city": "Brasil",
        "state": "",
        "country": "BR",
        "market": "BR",
        "published_date": published,
        "expires_date": "",
        "skills": [],
        "contract_types": [],
        "levels": [],
        "categories": ["Tecnologia"],
        "description": description,
    }


class PartialCatalogTests(unittest.TestCase):
    def test_dbc_active_feed_is_not_discarded_for_old_release_date(self):
        rows, dropped = pipeline.discard_old_publications(
            [sample("dbccompany", "old", published="2021-01-07")],
            "2026-06-25",
            today="2026-08-25",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(dropped, 0)

    def test_fit_merge_preserves_existing_jobs(self):
        description = (
            "Requisitos: experiência com SQL e APIs REST para suporte de sistemas. "
            "Diferenciais: conhecimento em Linux. "
            "A pessoa atuará em incidentes e documentação da operação."
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "fit.json"
            existing.write_text(json.dumps({
                "schema_version": 1,
                "generated_at": "2026-08-24T00:00:00+00:00",
                "count": 1,
                "terms": ["Termo antigo"],
                "jobs": {"https://example.com/old": {"m": [0], "p": [], "c": [], "x": [], "q": 20}},
            }), encoding="utf-8")
            changed, total = merge.merge_fit_index(
                [sample("digisystem", "1", description=description)], existing
            )
            payload = json.loads(existing.read_text(encoding="utf-8"))
            self.assertEqual(changed, 1)
            self.assertEqual(total, 2)
            self.assertIn("https://example.com/old", payload["jobs"])
            self.assertIn("https://example.com/digisystem/1", payload["jobs"])

    def test_snapshot_export_keeps_old_dbc_when_current_feed_succeeds(self):
        with tempfile.TemporaryDirectory() as temporary:
            conn = storage.connect(str(Path(temporary) / "jobs.db"))
            storage.upsert(conn, [sample("dbccompany", "old", published="2021-01-07")], today="2026-08-25")
            output = Path(temporary) / "vagas.json"
            count, _ = storage.export_snapshot(
                conn, str(output), today="2026-08-25", source_counts={"dbccompany": 2}
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(count, 1)
            self.assertEqual(payload["source_counts"], {"dbccompany": 1})
            conn.close()

    def test_partial_snapshot_guard_rejects_batch_only_publication(self):
        with self.assertRaisesRegex(RuntimeError, "redução insegura"):
            merge.ensure_snapshot_not_shrunk(48946, 5139)

    def test_partial_snapshot_guard_allows_normal_variation(self):
        merge.ensure_snapshot_not_shrunk(48946, 30000)

    def test_prune_keeps_old_dbc_when_current_feed_succeeds(self):
        with tempfile.TemporaryDirectory() as temporary:
            conn = storage.connect(str(Path(temporary) / "jobs.db"))
            storage.upsert(
                conn,
                [sample("dbccompany", "old", published="2021-01-07")],
                today="2026-08-25",
            )
            removed = storage.prune(
                conn,
                today="2026-08-25",
                active_feed_sources={"dbccompany"},
            )
            self.assertEqual(removed, 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM jobs WHERE source = 'dbccompany'").fetchone()[0],
                1,
            )
            conn.close()


if __name__ == "__main__":
    unittest.main()
