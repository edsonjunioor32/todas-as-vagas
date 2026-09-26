import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "jobs-dashboard"))

import description_crawler
import description_store


class PrivateDescriptionTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        handle.close()
        self.path = Path(handle.name)
        self.connection = description_store.connect(self.path)

    def tearDown(self):
        self.connection.close()
        for path in self.path.parent.glob(self.path.name + "*"):
            path.unlink(missing_ok=True)

    def test_extracts_jsonld_job_posting(self):
        payload = """
        <html><head>
          <script type="application/ld+json">
          {"@type":"JobPosting","description":"Experiência com suporte Linux e APIs REST. Atendimento de chamados, documentação técnica, análise de incidentes e sustentação de aplicações."}
          </script>
        </head><body><nav>Menu</nav><main>Resumo curto</main></body></html>
        """.encode("utf-8")
        description, kind = description_crawler.extract_description(payload)
        self.assertEqual(kind, "jsonld")
        self.assertIn("Linux", description)
        self.assertIn("APIs REST", description)

    def test_manifest_checkpoint_and_private_search(self):
        jobs = [
            {
                "source": "solides",
                "native_id": "1",
                "title": "Analista de Suporte",
                "company": "Empresa A",
                "url": "https://example.com/jobs/1",
            },
            {
                "source": "gupy",
                "native_id": "2",
                "title": "Engenheiro de Dados",
                "company": "Empresa B",
                "url": "https://example.com/jobs/2",
            },
        ]
        seen_at, count = description_store.sync_manifest(self.connection, jobs)
        self.assertEqual(count, 2)
        pending = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )
        self.assertEqual(len(pending), 2)

        support_job = next(row for row in pending if row["source"] == "solides")
        description_store.record_success(
            self.connection,
            support_job,
            "Experiência com Linux, Python e APIs REST.",
            content_kind="jsonld",
        )
        current = self.connection.execute(
            "SELECT * FROM job_descriptions WHERE job_uid = ?",
            (support_job["job_uid"],),
        ).fetchone()
        self.assertEqual(current["status"], "fetched")
        self.assertGreater(len(current["description_sha256"]), 20)

        remaining = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )
        self.assertEqual(len(remaining), 1)
        self.assertNotEqual(remaining[0]["job_uid"], support_job["job_uid"])

        results = description_store.search(self.connection, "Python")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Analista de Suporte")

    def test_prunes_jobs_missing_from_current_manifest(self):
        old_jobs = [{
            "source": "portal",
            "native_id": "old",
            "title": "Vaga encerrada",
            "company": "Empresa",
            "url": "https://example.com/jobs/old",
        }]
        current_jobs = [{
            "source": "portal",
            "native_id": "current",
            "title": "Vaga ativa",
            "company": "Empresa",
            "url": "https://example.com/jobs/current",
        }]
        description_store.sync_manifest(self.connection, old_jobs)
        description_store.sync_manifest(self.connection, current_jobs)
        removed = description_store.prune_missing(
            self.connection, current_jobs
        )
        self.assertEqual(removed, 1)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(1) FROM job_descriptions"
            ).fetchone()[0],
            1,
        )

    def test_refuses_pruning_after_abnormal_manifest_shrink(self):
        jobs = [
            {
                "source": "portal",
                "native_id": str(index),
                "title": f"Vaga {index}",
                "company": "Empresa",
                "url": f"https://example.com/jobs/{index}",
            }
            for index in range(4)
        ]
        description_store.sync_manifest(self.connection, jobs)
        removed = description_store.prune_missing(
            self.connection, jobs[:1], min_manifest_ratio=0.5
        )
        self.assertEqual(removed, 0)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(1) FROM job_descriptions"
            ).fetchone()[0],
            4,
        )

    def test_failed_refresh_keeps_previous_description(self):
        jobs = [{
            "source": "portal",
            "native_id": "1",
            "title": "Vaga",
            "company": "Empresa",
            "url": "https://example.com/jobs/1",
        }]
        seen_at, _ = description_store.sync_manifest(self.connection, jobs)
        job = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )[0]
        description_store.record_success(
            self.connection,
            job,
            "Descrição original suficientemente longa para ser mantida.",
            content_kind="main",
        )
        description_store.record_failure(
            self.connection,
            job,
            status="http_503",
            error="indisponível",
            http_status=503,
        )
        row = self.connection.execute(
            "SELECT description, status, attempts FROM job_descriptions"
        ).fetchone()
        self.assertIn("Descrição original", row["description"])
        self.assertEqual(row["status"], "stale")
        self.assertEqual(row["attempts"], 1)

    def test_robots_denied_job_is_retried_after_its_backoff(self):
        jobs = [{
            "source": "portal",
            "native_id": "robots-retry",
            "title": "Vaga",
            "company": "Empresa",
            "url": "https://example.com/jobs/robots-retry",
        }]
        seen_at, _ = description_store.sync_manifest(self.connection, jobs)
        job = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )[0]

        description_store.record_failure(
            self.connection,
            job,
            status="robots_denied",
            error="robots.txt não autoriza a coleta",
            retry_after_seconds=86400,
        )
        self.assertEqual(
            description_store.pending_jobs(self.connection, seen_at=seen_at), []
        )

        self.connection.execute(
            "UPDATE job_descriptions SET next_attempt_at = ? WHERE job_uid = ?",
            ("2000-01-01T00:00:00+00:00", job["job_uid"]),
        )
        self.connection.commit()

        retried = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )
        self.assertEqual([row["job_uid"] for row in retried], [job["job_uid"]])

    def test_robots_denied_refresh_with_saved_description_keeps_backoff_status(self):
        jobs = [{
            "source": "portal",
            "native_id": "robots-refresh",
            "title": "Vaga",
            "company": "Empresa",
            "url": "https://example.com/jobs/robots-refresh",
        }]
        seen_at, _ = description_store.sync_manifest(self.connection, jobs)
        job = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )[0]
        description_store.record_success(
            self.connection,
            job,
            "Descrição original que deve continuar armazenada.",
            content_kind="main",
        )
        self.connection.execute(
            "UPDATE job_descriptions SET checked_at = ? WHERE job_uid = ?",
            ("2000-01-01T00:00:00+00:00", job["job_uid"]),
        )
        self.connection.commit()
        due_job = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )[0]

        description_store.record_failure(
            self.connection,
            due_job,
            status="robots_denied",
            error="robots.txt não autoriza a coleta",
            retry_after_seconds=86400,
        )
        stored = self.connection.execute(
            "SELECT description, status FROM job_descriptions WHERE job_uid = ?",
            (job["job_uid"],),
        ).fetchone()
        self.assertEqual(stored["status"], "robots_denied")
        self.assertIn("Descrição original", stored["description"])

        self.connection.execute(
            "UPDATE job_descriptions SET next_attempt_at = ? WHERE job_uid = ?",
            ("2000-01-01T00:00:00+00:00", job["job_uid"]),
        )
        self.connection.commit()
        self.assertEqual(
            len(description_store.pending_jobs(self.connection, seen_at=seen_at)),
            1,
        )

    def test_unchanged_manifest_skips_row_updates_and_keeps_checkpoint(self):
        jobs = [{
            "source": "portal",
            "native_id": "stable",
            "title": "Vaga estável",
            "company": "Empresa",
            "url": "https://example.com/jobs/stable",
        }]
        first_seen, count = description_store.sync_manifest(
            self.connection, jobs, seen_at="2026-09-01T00:00:00+00:00"
        )
        self.connection.executescript(
            """
            CREATE TABLE manifest_updates (amount INTEGER NOT NULL);
            INSERT INTO manifest_updates VALUES (0);
            CREATE TRIGGER count_manifest_updates
            AFTER UPDATE OF last_seen_at ON job_descriptions
            BEGIN
                UPDATE manifest_updates SET amount = amount + 1;
            END;
            """
        )

        second_seen, second_count = description_store.sync_manifest(
            self.connection, jobs, seen_at="2026-09-02T00:00:00+00:00"
        )
        row = self.connection.execute(
            "SELECT last_seen_at FROM job_descriptions"
        ).fetchone()

        self.assertEqual(second_seen, first_seen)
        self.assertEqual(second_count, count)
        self.assertEqual(row["last_seen_at"], first_seen)
        self.assertEqual(
            self.connection.execute(
                "SELECT amount FROM manifest_updates"
            ).fetchone()[0],
            0,
        )

    def test_manifest_metadata_change_invalidates_checkpoint(self):
        job = {
            "source": "portal",
            "native_id": "changed",
            "title": "Título original",
            "company": "Empresa",
            "url": "https://example.com/jobs/changed",
        }
        first_seen, _ = description_store.sync_manifest(
            self.connection, [job], seen_at="2026-09-01T00:00:00+00:00"
        )
        changed_job = {**job, "title": "Título atualizado"}

        second_seen, _ = description_store.sync_manifest(
            self.connection,
            [changed_job],
            seen_at="2026-09-02T00:00:00+00:00",
        )

        stored = self.connection.execute(
            "SELECT title, last_seen_at FROM job_descriptions"
        ).fetchone()
        self.assertNotEqual(second_seen, first_seen)
        self.assertEqual(stored["title"], "Título atualizado")
        self.assertEqual(stored["last_seen_at"], second_seen)

    def test_schema_v1_upgrades_without_losing_description_rows(self):
        jobs = [{
            "source": "portal",
            "native_id": "legacy",
            "title": "Vaga legada",
            "company": "Empresa",
            "url": "https://example.com/jobs/legacy",
        }]
        seen_at, _ = description_store.sync_manifest(self.connection, jobs)
        job = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )[0]
        description_store.record_success(
            self.connection,
            job,
            "Descrição anterior preservada após atualização do banco.",
            content_kind="main",
        )
        self.connection.execute("DROP TABLE crawler_state")
        self.connection.execute("PRAGMA user_version = 1")
        self.connection.commit()

        upgraded = description_store.connect(self.path)
        try:
            version = upgraded.execute("PRAGMA user_version").fetchone()[0]
            stored = upgraded.execute(
                "SELECT description FROM job_descriptions WHERE job_uid = ?",
                (job["job_uid"],),
            ).fetchone()
            state_table = upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("crawler_state",),
            ).fetchone()
        finally:
            upgraded.close()

        self.assertEqual(version, 2)
        self.assertIsNotNone(state_table)
        self.assertIn("Descrição anterior", stored["description"])

    def test_prune_does_not_rebuild_an_unchanged_manifest(self):
        jobs = [{
            "source": "portal",
            "native_id": "prune-stable",
            "title": "Vaga",
            "company": "Empresa",
            "url": "https://example.com/jobs/prune-stable",
        }]
        description_store.sync_manifest(self.connection, jobs)
        description_store.prune_missing(self.connection, jobs)
        statements = []
        self.connection.set_trace_callback(statements.append)

        removed = description_store.prune_missing(self.connection, jobs)

        self.connection.set_trace_callback(None)
        self.assertEqual(removed, 0)
        self.assertFalse(
            any("current_description_manifest" in sql for sql in statements)
        )

    def test_stats_report_due_backlog_grouped_by_status(self):
        jobs = [
            {
                "source": "portal",
                "native_id": status,
                "title": f"Vaga {status}",
                "company": "Empresa",
                "url": f"https://example.com/jobs/{status}",
            }
            for status in ("http_503", "no_description", "robots_denied", "pending")
        ]
        seen_at, _ = description_store.sync_manifest(self.connection, jobs)
        self.connection.executemany(
            """
            UPDATE job_descriptions
            SET status = ?, next_attempt_at = ?
            WHERE native_id = ?
            """,
            [
                ("http_503", "2000-01-01T00:00:00+00:00", "http_503"),
                ("no_description", "2000-01-01T00:00:00+00:00", "no_description"),
                ("robots_denied", "2000-01-01T00:00:00+00:00", "robots_denied"),
                ("pending", "2999-01-01T00:00:00+00:00", "pending"),
            ],
        )
        self.connection.commit()

        summary = description_store.stats(self.connection, seen_at=seen_at)

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["with_description"], 0)
        self.assertEqual(
            summary["backlog_due_by_status"],
            {"http_503": 1, "no_description": 1, "robots_denied": 1},
        )

    def test_crawler_logs_counts_without_description_content(self):
        jobs = [
            {
                "source": "portal",
                "native_id": kind,
                "title": f"Vaga {kind}",
                "company": "Empresa",
                "url": f"https://example.com/jobs/{kind}",
            }
            for kind in ("description", "http", "empty")
        ]
        private_text = (
            "PRIVATE_DESCRIPTION_SENTINEL "
            + "requisitos confidenciais de exemplo " * 12
        )

        def fake_fetch(url, **_kwargs):
            if url.endswith("/http"):
                raise description_crawler.FetchError(
                    "http_503", "HTTP 503", http_status=503
                )
            if url.endswith("/empty"):
                return b"<html><body>Resumo curto</body></html>", "text/html", 200
            page = f"<html><main>{private_text}</main></html>"
            return page.encode("utf-8"), "text/html", 200

        output = io.StringIO()
        args = [
            "description_crawler.py",
            "--db", str(self.path),
            "--min-interval", "0",
            "--min-description-chars", "20",
        ]
        with (
            patch.object(sys, "argv", args),
            patch.object(description_crawler, "load_catalog", return_value=jobs),
            patch.object(description_crawler, "fetch_page", side_effect=fake_fetch),
            patch.object(description_crawler.RobotsCache, "allowed", return_value=True),
            contextlib.redirect_stdout(output),
        ):
            description_crawler.main()

        logged = output.getvalue().strip()
        self.assertTrue(logged.startswith("DESCRIPTION_CRAWLER_METRICS "))
        metrics = json.loads(logged.split(" ", 1)[1])
        self.assertEqual(metrics["candidates_due"], 3)
        self.assertEqual(metrics["descriptions_fetched_this_run"], 1)
        self.assertEqual(metrics["descriptions_stored_total"], 1)
        self.assertEqual(metrics["http_failures"], 1)
        self.assertEqual(metrics["no_description_failures"], 1)
        self.assertIn("backlog_due_by_status", metrics)
        self.assertNotIn(private_text, logged)
        self.assertNotIn("PRIVATE_DESCRIPTION_SENTINEL", logged)

    def test_crawler_schedules_robots_recheck_with_bounded_backoff(self):
        jobs = [{
            "source": "portal",
            "native_id": "robots-main",
            "title": "Vaga",
            "company": "Empresa",
            "url": "https://example.com/jobs/robots-main",
        }]
        args = ["description_crawler.py", "--db", str(self.path), "--min-interval", "0"]
        started = datetime.now(timezone.utc)
        with (
            patch.object(sys, "argv", args),
            patch.object(description_crawler, "load_catalog", return_value=jobs),
            patch.object(description_crawler.RobotsCache, "allowed", return_value=False),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            description_crawler.main()

        row = self.connection.execute(
            "SELECT status, attempts, next_attempt_at FROM job_descriptions"
        ).fetchone()
        delay = datetime.fromisoformat(row["next_attempt_at"]) - started
        self.assertEqual(row["status"], "robots_denied")
        self.assertEqual(row["attempts"], 1)
        self.assertGreaterEqual(delay.total_seconds(), 23 * 60 * 60)
        self.assertLessEqual(delay.total_seconds(), 25 * 60 * 60)


if __name__ == "__main__":
    unittest.main()

