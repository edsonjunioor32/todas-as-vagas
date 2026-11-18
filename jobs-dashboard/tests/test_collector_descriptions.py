import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import collector_descriptions as cd  # noqa: E402
import description_store  # noqa: E402

LONG = "Responsabilidades e requisitos da vaga. " * 10


def _job(source, native_id, url):
    return {"source": source, "native_id": native_id, "url": url, "title": "Vaga", "company": "Empresa"}


class CollectorDescriptionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "descriptions.sqlite3"
        self.connection = description_store.connect(self.path)

    def tearDown(self):
        self.connection.close()
        self.tmp.cleanup()

    def _seed(self, jobs):
        description_store.sync_manifest(self.connection, jobs, seen_at=description_store.utc_now())

    def _row(self, uid):
        return self.connection.execute(
            "SELECT status, content_kind, description FROM job_descriptions WHERE job_uid = ?",
            (uid,),
        ).fetchone()

    def test_normalize_url_drops_query_fragment_www_and_trailing_slash(self):
        self.assertEqual(
            cd.normalize_url("https://www.Example.com/jobs/1/?utm_source=api#top"),
            "example.com/jobs/1",
        )

    def test_matches_by_url_when_native_ids_differ_and_fills_failed_row(self):
        url = "https://vagas.solides.com.br/vaga/945411/tecnico"
        self._seed([_job("solides", url, url)])
        self.connection.execute(
            "UPDATE job_descriptions SET status='http_404' WHERE job_uid=?", (f"solides:{url}",)
        )
        self.connection.commit()
        registry = [("solides", lambda: [{"source": "solides", "native_id": "945411",
                                         "url": url + "?origem=api", "description": LONG}])]
        metrics = cd.ingest(self.connection, registry, min_chars=120,
                            refresh_after_days=30, dry_run=False)
        row = self._row(f"solides:{url}")
        self.assertEqual(row["status"], "fetched")
        self.assertEqual(row["content_kind"], "collector_api")
        self.assertEqual(metrics["stored"], 1)

    def test_keeps_existing_usable_description(self):
        url = "https://example.com/jobs/2"
        self._seed([_job("vagascom", url, url)])
        description_store.record_success(
            self.connection, {"job_uid": f"vagascom:{url}"}, "Texto completo. " * 40,
            content_kind="jsonld",
        )
        registry = [("vagascom", lambda: [{"source": "vagascom", "native_id": url,
                                          "url": url, "description": LONG}])]
        metrics = cd.ingest(self.connection, registry, min_chars=120,
                            refresh_after_days=30, dry_run=False)
        self.assertEqual(self._row(f"vagascom:{url}")["content_kind"], "jsonld")
        self.assertEqual(metrics["kept_existing"], 1)

    def test_dry_run_writes_nothing_and_creates_no_cache_table(self):
        url = "https://example.com/jobs/3"
        self._seed([_job("solides", url, url)])
        registry = [("solides", lambda: [{"source": "solides", "native_id": url,
                                         "url": url, "description": LONG},
                                        {"source": "solides", "native_id": "novo",
                                         "url": "https://example.com/jobs/new", "description": LONG}])]
        metrics = cd.ingest(self.connection, registry, min_chars=120,
                            refresh_after_days=30, dry_run=True)
        self.assertEqual(metrics["stored"], 1)
        self.assertNotEqual(self._row(f"solides:{url}")["status"], "fetched")
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='collector_description_cache'"
        ).fetchone()
        self.assertIsNone(table)

    def test_unmatched_description_is_cached_and_applied_when_row_appears(self):
        url = "https://himalayas.app/companies/acme/jobs/dev"
        registry = [("himalayas", lambda: [{"source": "himalayas", "native_id": url,
                                           "url": "https://apply.acme.com/1", "description": LONG}])]
        first = cd.ingest(self.connection, registry, min_chars=120,
                          refresh_after_days=30, dry_run=False)
        self.assertEqual(first["cached_unmatched"], 1)
        self._seed([_job("himalayas", url + "?utm_source=api", url + "?utm_source=api")])
        second = cd.ingest(self.connection, [("himalayas", lambda: [])], min_chars=120,
                           refresh_after_days=30, dry_run=False)
        self.assertEqual(second["cache_applied"], 1)
        self.assertEqual(self._row(f"himalayas:{url}?utm_source=api")["status"], "fetched")

    def test_failing_source_is_isolated(self):
        def broken():
            raise RuntimeError("upstream")

        metrics = cd.ingest(self.connection, [("quebrada", broken)], min_chars=120,
                            refresh_after_days=30, dry_run=False)
        self.assertEqual(metrics["failed_sources"], [{"source": "quebrada", "error": "RuntimeError"}])

    def test_metrics_never_contain_description_text(self):
        url = "https://example.com/jobs/4"
        self._seed([_job("solides", url, url)])
        registry = [("solides", lambda: [{"source": "solides", "native_id": url,
                                         "url": url, "description": LONG}])]
        metrics = cd.ingest(self.connection, registry, min_chars=120,
                            refresh_after_days=30, dry_run=False)
        self.assertNotIn("Responsabilidades", repr(metrics))


if __name__ == "__main__":
    unittest.main()
