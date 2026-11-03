import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import postiz_linkedin


def snapshot_fixture():
    return {
        "generated_date": "2026-09-30",
        "publication_cutoff": "2026-07-29",
        "dict": {
            "source": ["gupy", "greenhouse"],
            "company": ["Acme", "Beta", "Acme Labs"],
            "area": ["Tecnologia"],
            "seniority": ["Pleno"],
            "work_model": ["remote", "hybrid"],
            "market": ["BR"],
            "country": ["Brasil"],
        },
        "jobs": {
            "title": ["Pessoa Engenheira", "Analista de Dados", "Vaga encerrada", "Vaga antiga", "Não coletada hoje"],
            "src": [0, 1, 0, 0, 0],
            "cmp": [0, 1, 0, 2, 1],
            "area": [0, 0, 0, 0, 0],
            "sen": [0, 0, 0, 0, 0],
            "wm": [0, 1, 0, 0, 1],
            "mk": [0, 0, 0, 0, 0],
            "co": [0, 0, 0, 0, 0],
            "city": ["Remoto Brasil", "São Paulo", "Rio de Janeiro", "Remoto", "Curitiba"],
            "pub": ["2026-09-29", "2026-09-30", "2026-09-29", "2026-06-01", "2026-09-30"],
            "seen": ["2026-09-30"] * 4 + ["2026-09-29"],
            "exp": ["", "", "2026-09-29", "", ""],
            "url": [
                "https://jobs.example/acme/1?utm_source=feed",
                "https://jobs.example/beta/2",
                "https://jobs.example/acme/closed",
                "https://jobs.example/acme/old",
                "https://jobs.example/beta/not-today",
            ],
        },
    }


class PostizLinkedInTests(unittest.TestCase):
    def test_selects_only_current_active_recent_rows_and_skips_previously_posted(self):
        snapshot = snapshot_fixture()
        posted = {postiz_linkedin.canonical_job_key("https://jobs.example/acme/1")}

        selected = postiz_linkedin.select_vacancies(snapshot, posted_keys=posted, today=date(2026, 9, 30))

        self.assertEqual([row["title"] for row in selected], ["Analista de Dados"])

    def test_digest_is_linkedin_page_payload_with_daily_tracking_marker(self):
        snapshot = snapshot_fixture()
        selected = postiz_linkedin.select_vacancies(snapshot, today=date(2026, 9, 30))
        content = postiz_linkedin.compose_digest(selected, date(2026, 9, 30))
        payload = postiz_linkedin.build_post_payload(
            "integration-123", content, now=datetime(2026, 9, 30, 23, 7, tzinfo=timezone.utc)
        )

        self.assertIn("utm_campaign=todas-as-vagas-20260930", content)
        self.assertLessEqual(len(content), postiz_linkedin.MAX_POST_CHARS)
        self.assertEqual(payload["type"], "now")
        self.assertEqual(payload["posts"][0]["integration"]["id"], "integration-123")
        self.assertEqual(payload["posts"][0]["settings"]["__type"], "linkedin-page")

    def test_publish_is_preview_only_in_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            result = postiz_linkedin.publish(
                snapshot_fixture(), env={}, state_path=state, dry_run=True,
                today=date(2026, 9, 30),
            )

        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["count"], 2)
        self.assertFalse(state.exists())

    def test_existing_post_marker_persists_dedupe_state_and_prevents_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            env = {
                "POSTIZ_API_BASE_URL": "https://postiz.example/api/public/v1",
                "POSTIZ_API_KEY": "test-key",
                "POSTIZ_LINKEDIN_INTEGRATION_ID": "integration-123",
            }
            with mock.patch.object(
                postiz_linkedin.PostizClient, "already_has_marker", return_value=True
            ) as existing:
                first = postiz_linkedin.publish(
                    snapshot_fixture(), env=env, state_path=state, today=date(2026, 9, 30)
                )
                second = postiz_linkedin.publish(
                    snapshot_fixture(), env=env, state_path=state, today=date(2026, 9, 30)
                )

        self.assertEqual(first["reason"], "marker_found_in_postiz")
        self.assertEqual(second["reason"], "already_posted_today")
        self.assertEqual(existing.call_count, 1)

    def test_invalid_snapshot_is_rejected(self):
        with self.assertRaises(postiz_linkedin.PostizError):
            postiz_linkedin.decode_snapshot({"jobs": {"title": ["a"], "url": []}})


if __name__ == "__main__":
    unittest.main()
