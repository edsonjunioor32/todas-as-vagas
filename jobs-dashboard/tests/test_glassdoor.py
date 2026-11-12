import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "jobs-dashboard"))

import glassdoor
import storage


def manifest(*, approved=True):
    return {
        "schema_version": 1,
        "profiles": {
            "empresa-teste": {
                "id": "empresa-teste",
                "company_names": ["Empresa Teste"],
                "company_keys": ["empresa teste"],
                "url": "https://www.glassdoor.com.br/Overview/Working-at-Empresa-Teste-EI_IE1.htm",
            }
        },
    }


class GlassdoorTests(unittest.TestCase):
    def test_parse_public_structured_metrics_without_visible_text_scraping(self):
        body = """
        <html><head>
          <script type="application/ld+json">
            {"@type":"Organization","aggregateRating":{"ratingValue":"4.3","reviewCount":"1.234"}}
          </script>
        </head><body>999,9 avaliações falsas</body></html>
        """
        self.assertEqual(
            glassdoor.parse_public_profile(body),
            {"rating": 4.3, "review_count": 1234},
        )

    def test_parse_profile_overall_rating_from_reference_shape_without_review_text(self):
        body = """
        <script type="application/ld+json">
          {
            "employer": {
              "ratings": {"overallRating": "4.0"},
              "reviews": [{"summary": "texto que não deve ser capturado"}]
            }
          }
        </script>
        """
        self.assertEqual(
            glassdoor.parse_public_profile(body),
            {"rating": 4.0, "review_count": None},
        )

    def test_parse_omkar_company_ratings_reads_only_overall_rating(self):
        body = {
            "company": {"id": 8990981, "name": "Heineken Brasil"},
            "ratings": {"overall": 4.0, "culture_and_values": 3.9},
            "reviews_count": 245,
            "reviews": [{"pros": "texto que não deve ser capturado"}],
        }
        profile = {
            "company_names": ["Heineken Brasil", "HEINEKEN Brazil"],
            "url": "https://www.glassdoor.com.br/Avaliações/Heineken-Brasil-Avaliações-E8990981.htm",
        }
        self.assertEqual(
            glassdoor.parse_omkar_company_ratings(body, profile),
            {"rating": 4.0, "review_count": 245},
        )

    def test_parse_omkar_company_ratings_rejects_wrong_company(self):
        body = {
            "company": {"id": 1, "name": "Outra Empresa"},
            "ratings": {"overall": 4.8},
            "reviews_count": 12,
        }
        with self.assertRaises(glassdoor.ProfileDataUnavailable):
            glassdoor.parse_omkar_company_ratings(
                body,
                {"company_names": ["Empresa Teste"], "url": manifest()["profiles"]["empresa-teste"]["url"]},
            )

    def test_fetch_profile_uses_local_omkar_ratings_endpoint(self):
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps({
                    "company": {"name": "Empresa Teste"},
                    "ratings": {"overall": 4.6},
                    "reviews_count": 17,
                }).encode("utf-8")

        def opener(request, timeout):
            requests.append((request.full_url, timeout))
            return Response()

        profile = manifest()["profiles"]["empresa-teste"]
        with patch.dict(
            "os.environ",
            {
                "OMKAR_GLASSDOOR_ENABLED": "true",
                "OMKAR_GLASSDOOR_ENDPOINT": "http://127.0.0.1:18081",
            },
        ):
            self.assertEqual(
                glassdoor.fetch_profile(profile, timeout=7, opener=opener),
                {"rating": 4.6, "review_count": 17},
            )
        self.assertEqual(requests[0][0], "http://127.0.0.1:18081/companies/ratings?company=Empresa+Teste")
        self.assertEqual(requests[0][1], 7)

    def test_manifest_url_is_explicit_and_canonical(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "profiles": [{
                        "id": "empresa-teste",
                        "approved": True,
                        "company_names": ["Empresa Teste"],
                        "url": "https://www.glassdoor.com.br/Overview/Working-at-Empresa-Teste-EI_IE1.htm?x=1",
                    }],
                }),
                encoding="utf-8",
            )
            loaded = glassdoor.load_manifest(path)
        self.assertEqual(
            loaded["profiles"]["empresa-teste"]["url"],
            "https://www.glassdoor.com.br/Overview/Working-at-Empresa-Teste-EI_IE1.htm",
        )
        self.assertFalse(glassdoor.is_canonical_profile_url("https://example.com/profile"))

    def test_failed_daily_refresh_preserves_last_valid_values_and_is_not_retried_same_day(self):
        previous = {
            "schema_version": 1,
            "profiles": {
                "empresa-teste": {
                    "id": "empresa-teste",
                    "company_names": ["Empresa Teste"],
                    "url": manifest()["profiles"]["empresa-teste"]["url"],
                    "rating": 4.1,
                    "review_count": 88,
                    "checked_at": "2026-11-10",
                    "last_attempted_date": "2026-11-10",
                }
            },
        }
        calls = []

        def fail(profile, **kwargs):
            calls.append(profile["id"])
            raise TimeoutError("timeout")

        updated, summary = glassdoor.update_cache(
            manifest(),
            previous,
            now=datetime(2026, 11, 11, 8, 0),
            fetcher=fail,
            sleeper=lambda _seconds: None,
            profile_delay=0,
        )
        entry = updated["profiles"]["empresa-teste"]
        self.assertEqual(entry["rating"], 4.1)
        self.assertEqual(entry["review_count"], 88)
        self.assertEqual(entry["checked_at"], "2026-11-10")
        self.assertEqual(entry["last_attempted_date"], "2026-11-11")
        self.assertEqual(summary["failed"], 1)

        again, second = glassdoor.update_cache(
            manifest(),
            updated,
            now=datetime(2026, 11, 11, 20, 0),
            fetcher=fail,
            sleeper=lambda _seconds: None,
            profile_delay=0,
        )
        self.assertEqual(calls, ["empresa-teste"])
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(again["profiles"]["empresa-teste"]["rating"], 4.1)

    def test_forced_refresh_retries_profile_marked_today(self):
        previous = {
            "schema_version": 1,
            "profiles": {
                "empresa-teste": {
                    "id": "empresa-teste",
                    "company_names": ["Empresa Teste"],
                    "url": manifest()["profiles"]["empresa-teste"]["url"],
                    "rating": None,
                    "review_count": None,
                    "checked_at": None,
                    "last_attempted_date": "2026-11-12",
                }
            },
        }
        calls = []

        def succeed(profile, **kwargs):
            calls.append(profile["id"])
            return {"rating": 4.6, "review_count": 17}

        updated, summary = glassdoor.update_cache(
            manifest(),
            previous,
            now=datetime(2026, 11, 12, 20, 0),
            fetcher=succeed,
            sleeper=lambda _seconds: None,
            profile_delay=0,
            force=True,
        )
        self.assertEqual(calls, ["empresa-teste"])
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(updated["profiles"]["empresa-teste"]["rating"], 4.6)
        self.assertEqual(updated["profiles"]["empresa-teste"]["checked_at"], "2026-11-12")

    def test_enrich_snapshot_uses_nulls_for_unconfigured_companies(self):
        payload = {
            "schema_version": 3,
            "count": 2,
            "dict": {"company": ["Empresa Teste", "Outra Empresa"]},
            "jobs": {"cmp": [0, 1]},
        }
        cache = {
            "schema_version": 1,
            "profiles": {
                "empresa-teste": {
                    "company_names": ["Empresa Teste"],
                    "url": manifest()["profiles"]["empresa-teste"]["url"],
                    "rating": 4.5,
                    "review_count": 120,
                    "checked_at": "2026-11-11",
                }
            },
        }
        enriched, matched = glassdoor.enrich_snapshot(payload, cache)
        self.assertEqual(matched, 1)
        self.assertEqual(enriched["jobs"]["gdr"], [4.5, None])
        self.assertEqual(enriched["jobs"]["gdc"], [120, None])
        self.assertEqual(enriched["jobs"]["gdu"][1], None)
        self.assertEqual(enriched["jobs"]["gdt"], ["2026-11-11", None])

    def test_enrich_snapshot_keeps_hasdata_rating_and_reference_separate(self):
        payload = {
            "schema_version": 3,
            "count": 1,
            "dict": {"company": ["Empresa Teste"]},
            "jobs": {"cmp": [0]},
        }
        cache = {
            "schema_version": 1,
            "profiles": {
                "empresa-teste": {
                    "company_names": ["Empresa Teste"],
                    "url": manifest()["profiles"]["empresa-teste"]["url"],
                    "hasdata_rating": 4.4,
                    "hasdata_reference_url": "https://www.glassdoor.com.br/job-listing/vaga-1.htm",
                    "hasdata_checked_at": "2026-11-11",
                }
            },
        }
        enriched, matched = glassdoor.enrich_snapshot(payload, cache)
        self.assertEqual(matched, 1)
        self.assertEqual(enriched["jobs"]["gdr"], [None])
        self.assertEqual(enriched["jobs"]["gdc"], [None])
        self.assertEqual(enriched["jobs"]["gfr"], [4.4])
        self.assertEqual(enriched["jobs"]["gfu"], ["https://www.glassdoor.com.br/job-listing/vaga-1.htm"])
        self.assertEqual(enriched["jobs"]["gft"], ["2026-11-11"])

    def test_enrich_snapshot_hides_fallback_when_official_rating_exists(self):
        payload = {
            "schema_version": 3,
            "count": 1,
            "dict": {"company": ["Empresa Teste"]},
            "jobs": {"cmp": [0]},
        }
        cache = {
            "schema_version": 1,
            "profiles": {
                "empresa-teste": {
                    "company_names": ["Empresa Teste"],
                    "url": manifest()["profiles"]["empresa-teste"]["url"],
                    "rating": 4.0,
                    "checked_at": "2026-11-12",
                    "hasdata_rating": 4.2,
                    "hasdata_reference_url": "https://www.glassdoor.com.br/job-listing/vaga-1.htm",
                    "hasdata_checked_at": "2026-11-12",
                }
            },
        }
        enriched, matched = glassdoor.enrich_snapshot(payload, cache)
        self.assertEqual(matched, 1)
        self.assertEqual(enriched["jobs"]["gdr"], [4.0])
        self.assertEqual(enriched["jobs"]["gfr"], [None])
        self.assertEqual(enriched["jobs"]["gfu"], [None])
        self.assertEqual(enriched["jobs"]["gft"], [None])

    def test_enrich_snapshot_matches_catalog_name_heineken_brazil(self):
        payload = {
            "schema_version": 3,
            "count": 1,
            "dict": {"company": ["HEINEKEN Brazil"]},
            "jobs": {"cmp": [0]},
        }
        cache = {
            "schema_version": 1,
            "profiles": {
                "heineken-brasil": {
                    "company_names": ["Heineken N.V.", "HEINEKEN Brazil"],
                    "url": "https://www.glassdoor.com.br/Avalia%C3%A7%C3%B5es/Heineken-Brasil-Avalia%C3%A7%C3%B5es-E8990981.htm",
                    "hasdata_rating": 4.2,
                    "hasdata_reference_url": "https://www.glassdoor.com.br/job-listing/vaga-1.htm",
                    "hasdata_checked_at": "2026-11-12",
                }
            },
        }
        enriched, matched = glassdoor.enrich_snapshot(payload, cache)
        self.assertEqual(matched, 1)
        self.assertEqual(enriched["jobs"]["gfr"], [4.2])
        self.assertEqual(enriched["jobs"]["gfu"], ["https://www.glassdoor.com.br/job-listing/vaga-1.htm"])
        self.assertEqual(enriched["jobs"]["gft"], ["2026-11-12"])

    def test_export_snapshot_includes_optional_arrays_without_changing_job_count(self):
        with tempfile.TemporaryDirectory() as directory:
            conn = storage.connect(str(Path(directory) / "jobs.db"))
            storage.upsert(conn, [{
                "source": "portal",
                "native_id": "1",
                "title": "Vaga",
                "company": "Empresa Teste",
                "url": "https://example.com/1",
                "city": "São Paulo",
                "state": "SP",
                "country": "BR",
                "market": "BR",
                "skills": [],
                "contract_types": [],
            }], today="2026-11-11")
            output = Path(directory) / "vagas.json"
            count, _ = storage.export_snapshot(
                conn,
                str(output),
                today="2026-11-11",
                glassdoor_cache={
                    "schema_version": 1,
                    "profiles": {
                        "empresa-teste": {
                            "company_names": ["Empresa Teste"],
                            "url": manifest()["profiles"]["empresa-teste"]["url"],
                            "rating": 4.2,
                            "review_count": 42,
                            "checked_at": "2026-11-11",
                        }
                    },
                },
            )
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(count, 1)
            self.assertEqual(data["jobs"]["gdr"], [4.2])
            self.assertEqual(data["jobs"]["gdc"], [42])
            conn.close()

    def test_daily_workflow_is_separate_and_serialized(self):
        workflow = (ROOT / ".github/workflows/glassdoor-daily.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "23 6 * * *"', workflow)
        self.assertIn("group: catalog-publication", workflow)
        self.assertIn("glassdoor.py", workflow)
        self.assertIn("--timeout 15", workflow)
        self.assertIn("--profile-delay 1", workflow)
        self.assertIn("force_refresh", workflow)
        self.assertIn("extra_args+=(--force)", workflow)
        self.assertIn('"${extra_args[@]}"', workflow)
        self.assertIn("runs-on: self-hosted", workflow)
        self.assertIn("OMKAR_GLASSDOOR_ENDPOINT", workflow)
        self.assertIn("glassdoor-scraper.git", workflow)
        self.assertNotIn("JOBS_SOURCE_WORKERS", workflow)

    def test_frontend_does_not_turn_missing_metrics_into_zero(self):
        app = (ROOT / "docs/app.js").read_text(encoding="utf-8")
        self.assertIn("function optionalGlassdoorNumber(value)", app)
        self.assertIn("const rating = optionalGlassdoorNumber(job.glassdoorRating);", app)
        self.assertIn("const fallbackRating = optionalGlassdoorNumber(job.glassdoorFallbackRating);", app)
        self.assertNotIn("const rating = Number(job.glassdoorRating);", app)
        self.assertNotIn("const fallbackRating = Number(job.glassdoorFallbackRating);", app)


if __name__ == "__main__":
    unittest.main()
