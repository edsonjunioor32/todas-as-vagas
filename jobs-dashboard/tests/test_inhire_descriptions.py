import json
import sys
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inhire_descriptions


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=None):
        return self.payload


class InhireDescriptionTests(unittest.TestCase):
    def test_fetches_description_from_public_api_after_resolving_tenant(self):
        responses = [
            FakeResponse(
                {
                    "tenant": {"id": "objective"},
                    "subdomain": {"tenantId": "objective"},
                }
            ),
            FakeResponse(
                {
                    "jobId": "7cbf7a94-2248-48d4-948f-3c310772c65f",
                    "description": (
                        "<h2>Responsabilidades</h2><p>" +
                        "Atuar em projetos digitais com colaboração e melhoria contínua. " * 8 +
                        "</p>"
                    ),
                }
            ),
        ]

        def fake_open(_request, timeout):
            self.assertEqual(timeout, 12.0)
            return responses.pop(0)

        with patch.object(inhire_descriptions.urllib.request, "urlopen", side_effect=fake_open):
            result = inhire_descriptions.fetch_description(
                "https://objective.inhire.app/vagas/7cbf7a94-2248-48d4-948f-3c310772c65f/vemserobj-banco-de-talentos",
                timeout=12.0,
                user_agent="test-agent",
                min_chars=120,
            )

        self.assertEqual(result.content_kind, "inhire_api")
        self.assertEqual(result.http_status, 200)
        self.assertIn("Responsabilidades", result.description)
        self.assertNotIn("<p>", result.description)
        self.assertEqual(responses, [])

    def test_not_found_is_classified_as_gone(self):
        responses = [
            FakeResponse(
                {
                    "tenant": {"id": "objective"},
                    "subdomain": {"tenantId": "objective"},
                }
            ),
            urllib.error.HTTPError(
                "https://api.inhire.app/job-posts/public/pages/job",
                404,
                "Not Found",
                {},
                None,
            ),
        ]

        def fake_open(_request, timeout):
            self.assertEqual(timeout, 12.0)
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with patch.object(inhire_descriptions.urllib.request, "urlopen", side_effect=fake_open):
            result = inhire_descriptions.fetch_description(
                "https://objective.inhire.app/vagas/7cbf7a94-2248-48d4-948f-3c310772c65f/vemserobj-banco-de-talentos",
                timeout=12.0,
                user_agent="test-agent",
                min_chars=120,
            )

        self.assertEqual(result.status, "gone")
        self.assertEqual(result.http_status, 404)


if __name__ == "__main__":
    unittest.main()
