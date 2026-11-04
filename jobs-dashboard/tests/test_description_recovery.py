import asyncio
import io
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import description_alternates
import description_recovery


JOB = {
    "url": "https://jobs.example/role/123",
    "title": "Analista de Dados Pleno",
    "company": "Empresa Exemplo",
}
DESCRIPTION = "Responsabilidades e requisitos para Analista de Dados Pleno. " * 5


class RecoveryTests(unittest.TestCase):
    def test_quality_gate_rejects_another_job_and_block_page(self):
        self.assertTrue(description_recovery.acceptable_description(
            JOB, DESCRIPTION, kind="jsonld", resolved_url=JOB["url"],
        ))
        self.assertFalse(description_recovery.acceptable_description(
            JOB, DESCRIPTION, kind="jsonld",
            resolved_url="https://jobs.example/role/456",
        ))
        query_job = {**JOB, "url": "https://jobs.example/positions?id=123"}
        self.assertFalse(description_recovery.acceptable_description(
            query_job, DESCRIPTION, kind="jsonld",
            resolved_url="https://jobs.example/positions?id=456",
        ))
        self.assertFalse(description_recovery.acceptable_description(
            JOB, "Access Denied " + DESCRIPTION, kind="jsonld",
            resolved_url=JOB["url"],
        ))
        self.assertFalse(description_recovery.acceptable_description(
            JOB, "Utilizamos cookies para melhorar sua experiência. " * 5,
            kind="job_container", resolved_url=JOB["url"],
        ))
        self.assertFalse(description_recovery.acceptable_description(
            JOB, "Esta vaga não está mais disponível. " + DESCRIPTION,
            kind="body", resolved_url=JOB["url"],
        ))
        self.assertFalse(description_recovery.acceptable_description(
            JOB, "texto institucional " * 25, kind="body",
            resolved_url=JOB["url"],
        ))

    def test_firecrawl_accepts_only_local_service_and_structured_same_job(self):
        page = ('<script type="application/ld+json">'
                + json.dumps({"@type": "JobPosting", "description": DESCRIPTION})
                + '</script>')
        response = io.BytesIO(json.dumps({
            "success": True,
            "data": {"html": page, "metadata": {"statusCode": 200, "url": JOB["url"]}},
        }).encode())
        with patch("urllib.request.urlopen", return_value=response) as opener:
            text, kind, error = description_recovery.firecrawl_local(
                JOB, endpoint="http://127.0.0.1:3002", timeout=10, min_chars=120,
            )
        self.assertEqual((text, kind, error), (DESCRIPTION.strip(), "firecrawl_jsonld", ""))
        self.assertEqual(opener.call_args.args[0].full_url,
                         "http://127.0.0.1:3002/v2/scrape")
        self.assertEqual(json.loads(opener.call_args.args[0].data)["formats"], ["html"])
        with patch("urllib.request.urlopen") as opener:
            text, kind, error = description_recovery.firecrawl_local(
                JOB, endpoint="https://api.firecrawl.dev", timeout=10, min_chars=120,
            )
        self.assertEqual((text, kind), ("", ""))
        self.assertIn("ValueError", error)
        opener.assert_not_called()

    def test_browser_use_runs_without_paid_keys_or_telemetry(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"description": DESCRIPTION, "kind": "jsonld",
                               "url": JOB["url"], "title": JOB["title"]}),
            stderr="",
        )
        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "secret", "BROWSER_USE_API_KEY": "secret"}),
            patch.object(description_recovery.subprocess, "run", return_value=completed) as runner,
        ):
            text, kind, error = description_recovery.browser_use_local(
                JOB, python="/opt/browser-use/bin/python", timeout=20, min_chars=120,
            )
        self.assertEqual((text, kind, error), (DESCRIPTION.strip(), "browser_use_jsonld", ""))
        env = runner.call_args.kwargs["env"]
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("BROWSER_USE_API_KEY", env)
        self.assertEqual(env["ANONYMIZED_TELEMETRY"], "false")
        self.assertEqual(env["BROWSER_USE_CLOUD_SYNC"], "false")

    def test_browser_renderer_uses_local_browser_without_agent(self):
        import browser_use_description

        page_html = ('<script type="application/ld+json">'
                     + json.dumps({"@type": "JobPosting", "description": DESCRIPTION})
                     + '</script>')
        class Page:
            async def evaluate(self, expression):
                self.expression = expression
                return page_html
            async def get_url(self):
                return JOB["url"]
            async def get_title(self):
                return JOB["title"]
        class Browser:
            def __init__(self, **kwargs):
                self.options = kwargs
            async def start(self):
                pass
            async def new_page(self, url):
                return Page()
            async def kill(self):
                pass
        fake = types.ModuleType("browser_use")
        fake.Browser = Browser
        with (patch.dict(sys.modules, {"browser_use": fake}),
              patch.object(browser_use_description.asyncio, "sleep", return_value=None)):
            result = asyncio.run(browser_use_description.render(
                JOB["url"], 10, 120, "/snap/bin/chromium",
            ))
        self.assertEqual(result["description"], DESCRIPTION.strip())
        self.assertEqual(result["kind"], "jsonld")

    def test_jobspy_suggestions_are_review_only_and_strictly_matched(self):
        candidate = {"title": JOB["title"], "company": JOB["company"],
                     "job_url": "https://indeed.example/123", "description": DESCRIPTION}
        async def search_jobs(**kwargs):
            return {"jobs": [candidate, {"title": "Outra vaga", "company": "Outra empresa"}]}
        server = types.ModuleType("jobspy_mcp.server")
        server.search_jobs = search_jobs
        package = types.ModuleType("jobspy_mcp")
        with patch.dict(sys.modules, {"jobspy_mcp": package, "jobspy_mcp.server": server}):
            result = asyncio.run(description_alternates.suggestions(
                JOB, sites=["indeed"], location="Brazil",
            ))
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["review_required"])
        self.assertEqual(result[0]["description_chars"], len(DESCRIPTION))
        self.assertNotIn("description", result[0])


if __name__ == "__main__":
    unittest.main()
