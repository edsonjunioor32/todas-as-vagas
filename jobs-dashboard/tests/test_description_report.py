import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import description_store
from description_report import build_report, render_json, render_markdown


class DescriptionReportTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        handle.close()
        self.path = Path(handle.name)
        self.connection = description_store.connect(self.path)

    def tearDown(self):
        self.connection.close()
        for path in self.path.parent.glob(self.path.name + "*"):
            path.unlink(missing_ok=True)

    def test_report_groups_quality_and_source_without_mutating_store(self):
        jobs = [
            {
                "source": "portal-a",
                "native_id": "complete",
                "title": "Vaga completa",
                "company": "Empresa A",
                "url": "https://example.com/complete",
            },
            {
                "source": "portal-a",
                "native_id": "blocked",
                "title": "Vaga bloqueada",
                "company": "Empresa A",
                "url": "https://example.com/blocked",
            },
            {
                "source": "portal-b",
                "native_id": "short",
                "title": "Vaga curta",
                "company": "Empresa B",
                "url": "https://example.com/short",
            },
            {
                "source": "portal-b",
                "native_id": "pending",
                "title": "Vaga pendente",
                "company": "Empresa B",
                "url": "https://example.com/pending",
            },
        ]
        seen_at, _ = description_store.sync_manifest(self.connection, jobs)
        pending = {
            row["native_id"]: row
            for row in description_store.pending_jobs(
                self.connection, seen_at=seen_at
            )
        }
        description_store.record_success(
            self.connection,
            pending["complete"],
            (
                "Responsabilidades\n"
                + ("Apoiar o time e acompanhar processos. " * 16)
                + "\nRequisitos\n"
                + ("Experiência em análise e atendimento. " * 16)
            ),
            content_kind="jsonld",
        )
        description_store.record_failure(
            self.connection,
            pending["blocked"],
            status="http_403",
            error="access denied",
            http_status=403,
            permanent=True,
        )
        description_store.record_success(
            self.connection,
            pending["short"],
            "Resumo curto da oportunidade.",
            content_kind="summary",
        )

        before = self.connection.execute(
            "SELECT COUNT(*) FROM job_descriptions"
        ).fetchone()[0]
        report = build_report(
            self.connection,
            seen_at=seen_at,
            sample_limit=2,
        )
        after = self.connection.execute(
            "SELECT COUNT(*) FROM job_descriptions"
        ).fetchone()[0]

        self.assertEqual(before, after)
        self.assertEqual(report["total"], 4)
        self.assertGreater(report["description_chars"], 0)
        self.assertGreater(report["description_bytes"], 0)
        self.assertEqual(
            report["quality"],
            {
                "blocked": 1,
                "complete_candidate": 1,
                "pending": 1,
                "short": 1,
            },
        )
        self.assertEqual(report["sources"]["portal-a"]["total"], 2)
        self.assertEqual(
            report["sources"]["portal-a"]["quality"]["blocked"], 1
        )
        self.assertEqual(report["sources"]["portal-b"]["quality"]["pending"], 1)
        self.assertEqual(len(report["samples"]["blocked"]), 1)

        encoded = json.loads(render_json(report))
        self.assertEqual(encoded["total"], 4)
        markdown = render_markdown(report)
        self.assertIn("portal-a", markdown)
        self.assertIn("complete_candidate", markdown)
        self.assertIn("https://example.com/blocked", markdown)

    def test_report_preserves_http_reason_for_stale_description(self):
        jobs = [{
            "source": "portal-a",
            "native_id": "stale-http",
            "title": "Vaga com refresh bloqueado",
            "company": "Empresa A",
            "url": "https://example.com/stale-http",
        }]
        seen_at, _ = description_store.sync_manifest(self.connection, jobs)
        job = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )[0]
        description_store.record_success(
            self.connection,
            job,
            "Descrição anterior " + "x" * 400,
            content_kind="main",
        )
        self.connection.execute(
            """
            UPDATE job_descriptions
            SET status = 'stale', http_status = 503, error = ?
            WHERE job_uid = ?
            """,
            ("HTTP 503", job["job_uid"]),
        )
        self.connection.commit()

        report = build_report(
            self.connection,
            seen_at=seen_at,
            sample_limit=2,
        )

        self.assertEqual(report["quality"].get("blocked"), 1)
        self.assertNotIn("stale", report["quality"])
        self.assertEqual(report["samples"]["blocked"][0]["reason"], "http_503")

    def test_reader_is_query_only_and_does_not_change_database(self):
        self.connection.execute(
            "CREATE TABLE report_read_only_probe (value TEXT NOT NULL)"
        )
        self.connection.commit()
        before_mtime = self.path.stat().st_mtime_ns

        reader = __import__("description_report")._read_only_connection(self.path)
        try:
            self.assertEqual(
                reader.execute("PRAGMA query_only").fetchone()[0],
                1,
            )
            with self.assertRaises(sqlite3.OperationalError):
                reader.execute(
                    "CREATE TABLE should_not_exist (value TEXT NOT NULL)"
                )
        finally:
            reader.close()

        after_mtime = self.path.stat().st_mtime_ns
        self.assertEqual(before_mtime, after_mtime)
        self.assertIsNone(
            self.connection.execute(
                "SELECT name FROM sqlite_master WHERE name = ?",
                ("should_not_exist",),
            ).fetchone()
        )


if __name__ == "__main__":
    unittest.main()
