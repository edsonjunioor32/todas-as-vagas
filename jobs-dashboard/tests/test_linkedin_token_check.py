# -*- coding: utf-8 -*-
"""Verificação do token da Community Management API (sem rede)."""
import io
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import test_linkedin_token as check  # noqa: E402

WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "verify-linkedin-token.yml").read_text(encoding="utf-8")
TOKEN = "AQVsegredo1234567890abcdef"


def http_error(code, body=b"{}"):
    return urllib.error.HTTPError("https://api.linkedin.com", code, "erro", Message(), io.BytesIO(body))


class TokenCheckTests(unittest.TestCase):
    def _main(self, side_effect):
        out = io.StringIO()
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": TOKEN, "GITHUB_ACTIONS": "true"}), \
             patch.object(check.urllib.request, "urlopen", side_effect=side_effect) as opener, \
             redirect_stdout(out):
            code = check.main()
        return code, out.getvalue(), opener

    def test_token_fragments_never_reach_the_log(self):
        code, output, _ = self._main(http_error(401))
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN[:8], output)
        self.assertNotIn(TOKEN[-6:], output)
        self.assertIn(f"{len(TOKEN)} caracteres", output)

    def test_permission_error_is_explained_and_not_retried_per_version(self):
        code, output, opener = self._main(http_error(403, b'{"message":"Not enough permissions"}'))
        self.assertEqual(code, 1)
        self.assertEqual(opener.call_count, 2)  # uma por teste, sem varrer versões
        self.assertIn("::error title=Token LinkedIn", output)
        self.assertIn("w_organization_social", output)

    def test_version_errors_try_next_version(self):
        self.assertIn("versão", check.diagnose(400, '{"message":"NONEXISTENT_VERSION"}'))

    def test_missing_token_fails(self):
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": ""}):
            self.assertEqual(check.main(), 1)

    def test_workflow_no_longer_masks_failures(self):
        self.assertNotIn("continue-on-error", WORKFLOW)
        self.assertIn("permissions:", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
