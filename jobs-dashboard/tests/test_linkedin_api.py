# -*- coding: utf-8 -*-
"""Testes unitários para o módulo tools/linkedin_api.py e ferramentas correlatas."""
import io
import json
import os
import sys
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import linkedin_api  # noqa: E402
import publish_linkedin_daily as pld  # noqa: E402


def make_http_error(code: int, body: bytes = b"{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.linkedin.com/rest/posts",
        code,
        "error",
        Message(),
        io.BytesIO(body),
    )


class LinkedInAPITests(unittest.TestCase):
    def test_escape_little_text_parentheses_and_brackets(self):
        text = "Edição de Hoje (17/11/2026) [Vagas] {Senior} | Remote <Tag> @Corp \\path"
        escaped = linkedin_api.escape_little_text(text)
        self.assertIn(r"\(17/11/2026\)", escaped)
        self.assertIn(r"\[Vagas\]", escaped)
        self.assertIn(r"\{Senior\}", escaped)
        self.assertIn(r"\|", escaped)
        self.assertIn(r"\<Tag\>", escaped)
        self.assertIn(r"\@Corp", escaped)
        self.assertIn(r"\\path", escaped)

    def test_escape_little_text_preserves_hashtags(self):
        text = "#TodasAsVagas #MelhoresVagasDoDia #HomeOffice"
        escaped = linkedin_api.escape_little_text(text)
        self.assertEqual(escaped, text)

    def test_escape_little_text_empty(self):
        self.assertEqual(linkedin_api.escape_little_text(""), "")

    def test_create_post_escapes_commentary_and_sends_headers(self):
        token = "test_token_123"
        raw_commentary = "Vagas do Dia (17/11/2026)"

        mock_resp = MagicMock()
        mock_resp.headers = {"x-restli-id": "urn:li:share:999888777"}
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            urn = linkedin_api.create_post(
                commentary=raw_commentary,
                token=token,
            )
            self.assertEqual(urn, "urn:li:share:999888777")
            self.assertEqual(mock_urlopen.call_count, 1)

            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.headers.get("Authorization"), "Bearer test_token_123")
            self.assertEqual(req.headers.get("X-restli-protocol-version"), "2.0.0")
            self.assertEqual(req.headers.get("Linkedin-version"), "202611")

            payload = json.loads(req.data.decode("utf-8"))
            # Verifica se o commentary foi devidamente escapado
            self.assertEqual(payload["commentary"], r"Vagas do Dia \(17/11/2026\)")

    def test_delete_post_encodes_urn_and_calls_delete_method(self):
        token = "test_token_123"
        post_urn = "urn:li:share:7528575670092800001"

        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = linkedin_api.delete_post(post_urn, token)
            self.assertTrue(result)

            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.get_method(), "DELETE")
            self.assertIn("urn%3Ali%3Ashare%3A7528575670092800001", req.full_url)
            self.assertEqual(req.headers.get("Authorization"), "Bearer test_token_123")

    def test_delete_post_returns_true_on_404(self):
        token = "test_token_123"
        post_urn = "urn:li:share:already_deleted"

        with patch("urllib.request.urlopen", side_effect=make_http_error(404)):
            result = linkedin_api.delete_post(post_urn, token)
            self.assertTrue(result)

    def test_delete_post_raises_on_500(self):
        token = "test_token_123"
        post_urn = "urn:li:share:err"

        with patch("urllib.request.urlopen", side_effect=make_http_error(500, b'{"message":"Internal Error"}')):
            with self.assertRaises(linkedin_api.LinkedInAPIError):
                linkedin_api.delete_post(post_urn, token)


class PublishDailyIntegrationTests(unittest.TestCase):
    def test_publish_daily_delete_urn_integration(self):
        fake_jobs = [
            {"title": f"Dev {i}", "company": f"Corp {i}", "url": f"https://gupy.io/{i}", "cleaned_title": f"Dev {i}"}
            for i in range(12)
        ]
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": "valid_token"}), \
             patch("linkedin_api.delete_post", return_value=True) as mock_delete, \
             patch("linkedin_api.publish_to_linkedin", return_value="urn:li:share:new_post"), \
             patch("publish_linkedin_daily.select_daily_vacancies", return_value=fake_jobs), \
             patch("urllib.request.urlopen") as mock_url:

            # Mock snapshot fetch
            mock_url.return_value.__enter__.return_value.read.return_value = b"{}"

            # Mock state saving
            with patch("publish_linkedin_daily.save_state"):
                code = pld.publish_daily(
                    force=True,
                    delete_urn="urn:li:share:7528575670092800001"
                )
                self.assertEqual(code, 0)
                mock_delete.assert_called_once_with("urn:li:share:7528575670092800001", "valid_token")


if __name__ == "__main__":
    unittest.main()
