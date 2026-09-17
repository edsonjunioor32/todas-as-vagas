import json
import sys
import tempfile
import unittest
from pathlib import Path

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
          {"@type":"JobPosting","description":"Experiência com suporte Linux e APIs REST. Atendimento de chamados, "
          "documentação técnica, análise de incidentes e sustentação de aplicações."}
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

        description_store.record_success(
            self.connection,
            pending[0],
            "Experiência com Linux, Python e APIs REST.",
            content_kind="jsonld",
        )
        current = self.connection.execute(
            "SELECT * FROM job_descriptions WHERE job_uid = ?",
            (pending[0]["job_uid"],),
        ).fetchone()
        self.assertEqual(current["status"], "fetched")
        self.assertGreater(len(current["description_sha256"]), 20)

        remaining = description_store.pending_jobs(
            self.connection, seen_at=seen_at
        )
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["job_uid"], pending[1]["job_uid"])

        results = description_store.search(self.connection, "Python")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Analista de Suporte")

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


if __name__ == "__main__":
    unittest.main()
