import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import description_crawler
import description_store


class CrawlerQualityMetricsTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        handle.close()
        self.path = Path(handle.name)
        self.connection = description_store.connect(self.path)

    def tearDown(self):
        self.connection.close()
        for path in self.path.parent.glob(self.path.name + "*"):
            path.unlink(missing_ok=True)

    def test_quality_metrics_are_scoped_to_processed_rows_and_grouped_by_source(self):
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

        metrics = description_crawler.quality_metrics_for_jobs(
            self.connection,
            [pending["complete"]["job_uid"], pending["blocked"]["job_uid"]],
        )

        self.assertEqual(
            metrics["quality"],
            {"blocked": 1, "complete_candidate": 1},
        )
        self.assertEqual(
            metrics["by_source"],
            {"portal-a": {"blocked": 1, "complete_candidate": 1}},
        )


if __name__ == "__main__":
    unittest.main()
