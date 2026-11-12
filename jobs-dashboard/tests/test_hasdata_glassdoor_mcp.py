import json
import os
import sys
import unittest
import urllib.error
from datetime import datetime
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "jobs-dashboard"))

import glassdoor
from hasdata_glassdoor_mcp import HasDataGlassdoorMcpClient


class _Response:
    def __init__(self, body, content_type="application/json", status=200, headers=None):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type, **(headers or {})}

    def read(self, _limit=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class HasDataGlassdoorMcpTests(unittest.TestCase):
    def test_uses_current_hasdata_glassdoor_mcp_endpoint(self):
        from hasdata_glassdoor_mcp import DEFAULT_ENDPOINT

        self.assertEqual(
            "https://mcp.hasdata.com/mcp?apis=glassdoor",
            DEFAULT_ENDPOINT,
        )

    def test_accepts_structured_content_and_markdown_json(self):
        structured = HasDataGlassdoorMcpClient._tool_payload({
            "structuredContent": {"jobs": []},
        })
        self.assertEqual(structured, {"jobs": []})
        markdown = HasDataGlassdoorMcpClient._tool_payload({
            "content": [{"type": "text", "text": "Resultado:\n```json\n{\"jobs\": []}\n```"}],
        })
        self.assertEqual(markdown, {"jobs": []})

    def test_ignores_unstructured_text_without_a_json_object(self):
        self.assertIsNone(HasDataGlassdoorMcpClient._tool_payload({
            "content": [{"type": "text", "text": "Nenhuma vaga encontrada"}],
        }))

    def test_queries_accept_the_official_brazilian_regional_domain(self):
        queries = glassdoor.load_hasdata_queries()
        self.assertTrue(queries)
        self.assertTrue(all(item["domain"] == "www.glassdoor.com.br" for item in queries))

    def test_rejects_non_hasdata_endpoint_to_prevent_key_exfiltration(self):
        with self.assertRaises(ValueError):
            HasDataGlassdoorMcpClient(
                "secret-value",
                endpoint="https://example.invalid/mcp",
            )

    def test_streamable_http_session_initializes_lists_tools_and_calls_search(self):
        calls = []

        def opener(request, timeout):
            calls.append((json.loads(request.data.decode("utf-8")), request.headers, timeout))
            method = calls[-1][0]["method"]
            if method == "initialize":
                return _Response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode())
            if method == "notifications/initialized":
                return _Response(b"", status=202)
            if method == "tools/list":
                return _Response(json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}).encode())
            return _Response(
                b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n'
                b'data: {"jsonrpc":"2.0","id":99,"result":{}}\n\n'
                b'data: {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\\"jobs\\":[],\\"searchInformation\\":{\\"totalResults\\":0}}"}]}}\n\n',
                content_type="text/event-stream",
            )

        client = HasDataGlassdoorMcpClient(
            "secret-value",
            timeout=7,
            opener=opener,
            sleeper=lambda _seconds: None,
        )
        result = client.search_jobs(keyword="Empresa Teste", location="Brasil")

        self.assertEqual(result["jobs"], [])
        self.assertEqual([item[0]["method"] for item in calls], [
            "initialize",
            "notifications/initialized",
            "tools/list",
            "tools/call",
        ])
        self.assertTrue(all(item[1].get("X-api-key") == "secret-value" for item in calls))
        self.assertEqual(calls[0][2], 7)

    def test_real_hasdata_envelope_and_employer_rating_are_used(self):
        payload = {
            "json": {
                "jobs": [{
                    "company": {"name": "Empresa Teste", "rating": 4.7},
                    "rating": 1.1,
                    "url": "https://www.glassdoor.com.br/job-listing/vaga.htm?jl=123&utm_source=x",
                }]
            }
        }
        result = glassdoor._mcp_match(payload, {"company_names": ["Empresa Teste"]})
        self.assertEqual(result["rating"], 4.7)
        self.assertEqual(result["reference_url"].split("?", 1)[1], "jl=123")

    def test_fallback_accepts_matching_company_without_review_count(self):
        cache = {
            "schema_version": 1,
            "profiles": {
                "empresa-teste": {
                    "id": "empresa-teste",
                    "company_names": ["Empresa Teste"],
                    "company_keys": ["empresa teste"],
                    "url": "https://www.glassdoor.com.br/Overview/Working-at-Empresa-Teste-EI_IE1.htm",
                    "rating": None,
                    "review_count": None,
                    "checked_at": None,
                    "last_attempted_date": None,
                }
            },
        }
        queries = [{
            "id": "empresa-teste-query",
            "profile_id": "empresa-teste",
            "company_names": ["Empresa Teste"],
            "keyword": "Empresa Teste",
            "location": "Brasil",
            "domain": "glassdoor.com.br",
        }]

        with patch.dict(os.environ, {"HASDATA_MCP_ENABLED": "true", "HASDATA_API_KEY": "test"}, clear=True):
            updated, summary = glassdoor.update_hasdata_fallback(
                cache,
                queries,
                now=datetime(2026, 11, 11, 8, 0),
                fetcher=lambda _query: {
                    "jobs": [{
                        "title": "Vaga pública",
                        "url": "https://www.glassdoor.com.br/job-listing/vaga-1.htm",
                        "company": {"name": "Empresa Teste", "rating": 4.4},
                    }]
                },
                max_calls=1,
            )

        entry = updated["profiles"]["empresa-teste"]
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(entry["hasdata_rating"], 4.4)
        self.assertEqual(entry["hasdata_reference_url"], "https://www.glassdoor.com.br/job-listing/vaga-1.htm")
        self.assertIsNone(entry.get("hasdata_review_count"))

    def test_fallback_rejects_divergent_company_and_preserves_previous_value(self):
        cache = {
            "schema_version": 1,
            "profiles": {
                "empresa-teste": {
                    "id": "empresa-teste",
                    "company_names": ["Empresa Teste"],
                    "company_keys": ["empresa teste"],
                    "url": "https://www.glassdoor.com.br/Overview/Working-at-Empresa-Teste-EI_IE1.htm",
                    "rating": None,
                    "review_count": None,
                    "checked_at": None,
                    "last_attempted_date": None,
                    "hasdata_rating": 4.1,
                    "hasdata_reference_url": "https://www.glassdoor.com.br/job-listing/vaga-anterior.htm",
                    "hasdata_checked_at": "2026-11-10",
                    "hasdata_last_attempted_date": "2026-11-10",
                }
            },
        }
        queries = [{
            "id": "empresa-teste-query",
            "profile_id": "empresa-teste",
            "company_names": ["Empresa Teste"],
            "keyword": "Empresa Teste",
            "location": "Brasil",
            "domain": "glassdoor.com.br",
        }]

        with patch.dict(os.environ, {"HASDATA_MCP_ENABLED": "true", "HASDATA_API_KEY": "test"}, clear=True):
            updated, summary = glassdoor.update_hasdata_fallback(
                cache,
                queries,
                now=datetime(2026, 11, 11, 8, 0),
                fetcher=lambda _query: {
                    "jobs": [{
                        "title": "Vaga pública",
                        "url": "https://www.glassdoor.com.br/job-listing/vaga-2.htm",
                        "company": {"name": "Outra Empresa", "rating": 4.9},
                    }]
                },
                max_calls=1,
            )

        entry = updated["profiles"]["empresa-teste"]
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(entry["hasdata_rating"], 4.1)
        self.assertEqual(entry["hasdata_reference_url"], "https://www.glassdoor.com.br/job-listing/vaga-anterior.htm")

    def test_default_is_disabled_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(glassdoor.hasdata_mcp_enabled())

    def test_fallback_respects_per_execution_call_cap(self):
        cache = {
            "schema_version": 1,
            "profiles": {
                "empresa-teste": {
                    "id": "empresa-teste",
                    "company_names": ["Empresa Teste"],
                    "company_keys": ["empresa teste"],
                    "url": "https://www.glassdoor.com.br/Overview/Working-at-Empresa-Teste-EI_IE1.htm",
                },
                "outra-empresa": {
                    "id": "outra-empresa",
                    "company_names": ["Outra Empresa"],
                    "company_keys": ["outra empresa"],
                    "url": "https://www.glassdoor.com.br/Overview/Working-at-Outra-Empresa-EI_IE2.htm",
                },
            },
        }
        queries = [
            {
                "id": "empresa-teste-query",
                "profile_id": "empresa-teste",
                "company_names": ["Empresa Teste"],
                "keyword": "Empresa Teste",
                "location": "Brasil",
                "domain": "glassdoor.com.br",
            },
            {
                "id": "outra-empresa-query",
                "profile_id": "outra-empresa",
                "company_names": ["Outra Empresa"],
                "keyword": "Outra Empresa",
                "location": "Brasil",
                "domain": "glassdoor.com.br",
            },
        ]
        calls = []
        with patch.dict(os.environ, {"HASDATA_MCP_ENABLED": "true", "HASDATA_API_KEY": "test"}, clear=True):
            updated, summary = glassdoor.update_hasdata_fallback(
                cache,
                queries,
                fetcher=lambda query: calls.append(query) or {"jobs": []},
                max_calls=1,
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary["attempted"], 1)
        self.assertEqual(summary["capped"], 1)
        self.assertEqual(updated["profiles"]["outra-empresa"].get("hasdata_rating"), None)

    def test_fallback_rotates_oldest_attempted_query_before_newer_query(self):
        cache = {
            "schema_version": 1,
            "profiles": {
                "empresa-teste": {
                    "id": "empresa-teste",
                    "company_names": ["Empresa Teste"],
                    "company_keys": ["empresa teste"],
                    "hasdata_last_attempted_date": "2026-11-10",
                },
                "outra-empresa": {
                    "id": "outra-empresa",
                    "company_names": ["Outra Empresa"],
                    "company_keys": ["outra empresa"],
                    "hasdata_last_attempted_date": "2026-11-01",
                },
            },
        }
        queries = [
            {
                "id": "empresa-teste-query",
                "profile_id": "empresa-teste",
                "company_names": ["Empresa Teste"],
                "keyword": "Empresa Teste",
                "location": "Brasil",
                "domain": "glassdoor.com.br",
            },
            {
                "id": "outra-empresa-query",
                "profile_id": "outra-empresa",
                "company_names": ["Outra Empresa"],
                "keyword": "Outra Empresa",
                "location": "Brasil",
                "domain": "glassdoor.com.br",
            },
        ]
        calls = []
        with patch.dict(os.environ, {"HASDATA_MCP_ENABLED": "true", "HASDATA_API_KEY": "test"}, clear=True):
            _updated, summary = glassdoor.update_hasdata_fallback(
                cache,
                queries,
                now=datetime(2026, 11, 11, 8, 0),
                fetcher=lambda query: calls.append(query["profile_id"]) or {"jobs": []},
                max_calls=1,
            )
        self.assertEqual(calls, ["outra-empresa"])
        self.assertEqual(summary["attempted"], 1)

    def test_transport_retries_rate_limit_but_does_not_retry_invalid_json(self):
        rate_limit_calls = []

        def rate_limited_opener(request, timeout):
            self.assertGreater(timeout, 0)
            payload = json.loads(request.data.decode("utf-8"))
            rate_limit_calls.append(payload["method"])
            if len(rate_limit_calls) < 3:
                raise urllib.error.HTTPError("https://mcp.hasdata.com/mcp", 429, "busy", {}, None)
            if payload["method"] == "notifications/initialized":
                return _Response(b"", status=202)
            return _Response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode())

        client = HasDataGlassdoorMcpClient(
            "secret-value",
            retries=2,
            opener=rate_limited_opener,
            sleeper=lambda _seconds: None,
        )
        client.initialize()
        self.assertEqual(rate_limit_calls, ["initialize", "initialize", "initialize", "notifications/initialized"])

        invalid_calls = []

        def invalid_opener(_request, timeout):
            self.assertGreater(timeout, 0)
            invalid_calls.append(True)
            return _Response(b"not-json")

        invalid = HasDataGlassdoorMcpClient(
            "secret-value",
            retries=2,
            opener=invalid_opener,
            sleeper=lambda _seconds: None,
        )
        with self.assertRaises(Exception):
            invalid.initialize()
        self.assertEqual(len(invalid_calls), 1)


if __name__ == "__main__":
    unittest.main()
