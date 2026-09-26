# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
    def test_collect_rows_returns_healthy_rows_and_marks_empty_or_failed_sources(self):
        rows = [
            sample("experian", "fresh"),
            sample("digisystem", "partial"),
        ]
        with patch.object(
            merge, "TARGETS", (("experian", lambda: []), ("digisystem", lambda: []))
        ), patch.object(merge, "TARGET_NAMES", {"experian", "digisystem"}), patch.object(
            merge, "OPTIONAL_EMPTY_SOURCES", set()
        ), patch.object(
            pipeline, "collect", return_value=(rows, ["digisystem"], [])
        ):
            collected, counts, failed = merge.collect_rows()

        self.assertEqual({row["native_id"] for row in collected}, {"fresh", "partial"})
        self.assertEqual(counts, {"experian": 1, "digisystem": 1})
        self.assertEqual(failed, ["digisystem"])

    def test_collect_rows_does_not_treat_an_unexpected_empty_feed_as_healthy(self):
        rows = [sample("experian", "fresh")]
        with patch.object(
            merge, "TARGETS", (("experian", lambda: []), ("digisystem", lambda: []))
        ), patch.object(merge, "TARGET_NAMES", {"experian", "digisystem"}), patch.object(
            merge, "OPTIONAL_EMPTY_SOURCES", set()
        ), patch.object(
            pipeline, "collect", return_value=(rows, [], [])
        ):
            collected, counts, failed = merge.collect_rows()

        self.assertEqual([row["native_id"] for row in collected], ["fresh"])
        self.assertEqual(failed, ["digisystem"])

    def test_partial_merge_replaces_only_healthy_sources_and_keeps_failed_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "jobs.db"
            json_path = root / "vagas.json"
            fit_path = root / "fit.json"
            conn = storage.connect(str(db_path))
            storage.upsert(conn, [
                sample("experian", "stale"),
                sample("digisystem", "previous"),
            ], today="2026-09-20")
            conn.close()
            json_path.write_text(json.dumps({
                "count": 2,
                "failed_sources": ["experian", "digisystem", "legacy-source"],
                "collected_source_counts": {"experian": 1, "digisystem": 1},
            }), encoding="utf-8")

            result = merge.merge_catalog(
                [sample("experian", "fresh"), sample("digisystem", "partial")],
                {"experian": 1, "digisystem": 1},
                failed_sources=["digisystem"],
                db_path=db_path,
                json_path=json_path,
                fit_path=fit_path,
            )

            conn = storage.connect(str(db_path))
            records = conn.execute(
                "SELECT source, job_uid FROM jobs ORDER BY source, job_uid"
            ).fetchall()
            conn.close()
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(records, [
            ("digisystem", "digisystem:partial"),
            ("digisystem", "digisystem:previous"),
            ("experian", "experian:fresh"),
        ])
        self.assertEqual(payload["failed_sources"], ["digisystem", "legacy-source"])
        self.assertEqual(result["removed"], {"experian": 1})

    def test_partial_merge_keeps_catalog_untouched_when_no_feed_is_healthy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "jobs.db"
            json_path = root / "vagas.json"
            fit_path = root / "fit.json"
            conn = storage.connect(str(db_path))
            storage.upsert(conn, [sample("digisystem", "previous")])
            conn.close()
            original_json = json.dumps({
                "count": 1,
                "failed_sources": [],
            })
            json_path.write_text(original_json, encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "nenhuma fonte dinâmica saudável"):
                merge.merge_catalog(
                    [],
                    {"digisystem": 1},
                    failed_sources=["digisystem"],
                    db_path=db_path,
                    json_path=json_path,
                    fit_path=fit_path,
                )

            conn = storage.connect(str(db_path))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
            conn.close()
            self.assertEqual(json_path.read_text(encoding="utf-8"), original_json)

    def test_count_mismatch_marks_only_that_feed_failed_and_preserves_its_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "jobs.db"
            json_path = root / "vagas.json"
            fit_path = root / "fit.json"
            conn = storage.connect(str(db_path))
            storage.upsert(conn, [
                sample("experian", "stale"),
                sample("digisystem", "previous"),
            ], today="2026-09-20")
            conn.close()
            json_path.write_text(json.dumps({
                "count": 2,
                "failed_sources": [],
                "collected_source_counts": {},
            }), encoding="utf-8")

            result = merge.merge_catalog(
                [sample("experian", "fresh"), sample("digisystem", "partial")],
                {"experian": 1, "digisystem": 2},
                db_path=db_path,
                json_path=json_path,
                fit_path=fit_path,
            )

            conn = storage.connect(str(db_path))
            digisystem_uids = [row[0] for row in conn.execute(
                "SELECT job_uid FROM jobs WHERE source = 'digisystem' ORDER BY job_uid"
            ).fetchall()]
            conn.close()
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(digisystem_uids, ["digisystem:partial", "digisystem:previous"])
        self.assertEqual(payload["failed_sources"], ["digisystem"])
        self.assertEqual(result["removed"], {"experian": 1})

    def test_dbc_active_feed_is_not_discarded_for_old_release_date(self):
        rows, dropped = pipeline.discard_old_publications(
            [sample("dbccompany", "old", published="2021-01-07")],
            "2026-06-25",
            today="2026-08-25",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(dropped, 0)

    def test_mindsight_active_feeds_keep_old_publication_dates(self):
        rows, dropped = pipeline.discard_old_publications(
            [
                sample("liquidz", "old-liquidz", published="2026-07-07"),
                sample("pontotel", "old-pontotel", published="2026-07-07"),
            ],
            "2026-07-08",
            today="2026-09-08",
        )
        self.assertEqual(
            {row["source"] for row in rows},
            {"liquidz", "pontotel"},
        )
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
