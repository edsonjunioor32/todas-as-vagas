# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import gupy  # noqa: E402


def item(**overrides):
    value = {
        "id": 123,
        "name": "Analista de Dados",
        "careerPageName": "Empresa",
        "jobUrl": "https://empresa.gupy.io/jobs/123",
        "status": "published",
        "type": "vacancy_type_effective",
        "publicationType": "external",
        "publishedDate": "2026-09-20T10:00:00Z",
        "applicationDeadline": "2026-12-31",
        "description": "Requisitos e responsabilidades",
    }
    value.update(overrides)
    return value


class GupyEligibilityTests(unittest.TestCase):
    def test_maps_verified_public_published_vacancy(self):
        row = gupy._api_row(item())

        self.assertEqual(row["source"], "gupy")
        self.assertEqual(row["published_date"], "2026-09-20T10:00:00+00:00")

    def test_excludes_unpublished_or_unverified_status(self):
        self.assertIsNone(gupy._api_row(item(status="closed")))
        self.assertIsNone(gupy._api_row(item(status=None)))

    def test_excludes_non_public_publication_type(self):
        self.assertIsNone(gupy._api_row(item(publicationType="internal")))
        self.assertIsNone(gupy._api_row(item(publicationType=None)))

    def test_excludes_talent_pools_by_type_or_title(self):
        self.assertIsNone(gupy._api_row(item(type="vacancy_type_talent_pool")))
        self.assertIsNone(gupy._api_row(item(name="Banco de Talentos | PCD")))
        self.assertIsNone(gupy._api_row(item(name="Talent Pool - Brazil")))

    def test_maps_public_candidate_mcp_result_without_inventing_api_status(self):
        source = item()
        source.pop("status")
        source.pop("publicationType")

        row = gupy._candidate_mcp_row(source)

        self.assertEqual(row["source_status"], "public_search")
        self.assertEqual(row["source_publication_type"], "candidate_mcp")
        self.assertEqual(row["source_type"], "vacancy_type_effective")
        self.assertTrue(gupy.is_verified_public_listing(row))

    def test_excludes_confidential_candidate_mcp_listings(self):
        source = item(isConfidentialCareerPage=True)

        self.assertIsNone(gupy._candidate_mcp_row(source))

    def test_search_page_maps_mcp_payload_and_query(self):
        class FakeClient:
            def __init__(self):
                self.call = None

            def call_tool(self, name, arguments):
                self.call = (name, arguments)
                return {
                    "data": {
                        "data": [item()],
                        "pagination": {"total": 501, "limit": 100, "offset": 100},
                    }
                }

        client = FakeClient()
        rows, total = gupy._search_page(client, "analista", 100)

        self.assertEqual(len(rows), 1)
        self.assertEqual(total, 501)
        self.assertEqual(client.call[0], "search_jobs")
        self.assertEqual(client.call[1]["term"], "analista")
        self.assertEqual(client.call[1]["offset"], 100)
        self.assertEqual(client.call[1]["country"], "Brasil")
        self.assertEqual(client.call[1]["sortBy"], "publishedDate")

    def test_search_page_omits_empty_term_for_broad_catalog_query(self):
        class FakeClient:
            def call_tool(self, name, arguments):
                self.arguments = arguments
                return {"data": {"data": [], "pagination": {"total": 0}}}

        client = FakeClient()
        gupy._search_page(client, None, 0)

        self.assertNotIn("term", client.arguments)

    def test_page_size_capped_pagination_total_does_not_end_the_sweep(self):
        self.assertFalse(gupy._reached_reported_total(0, 100, 100))
        self.assertFalse(gupy._reached_reported_total(100, 100, 100))
        self.assertTrue(gupy._reached_reported_total(100, 100, 200))
        self.assertFalse(gupy._reached_reported_total(0, 100, None))

    def test_broad_catalog_paginates_until_the_reported_total(self):
        rows = []
        for identifier in range(200):
            source = item(id=identifier + 1)
            source.pop("status")
            source.pop("publicationType")
            rows.append(source)

        with patch.dict(os.environ, {"GUPY_BROAD_MAX_PAGES": "100"}), patch.object(
            gupy,
            "_search_page",
            side_effect=[(rows[:100], 100), (rows[100:150], 100)],
        ) as search:
            collected = gupy._fetch_recent_catalog(object())

        self.assertEqual(len(collected), 150)
        self.assertEqual([call.args[2] for call in search.call_args_list], [0, 100])

    def test_mcp_client_initializes_session_and_parses_sse_tool_response(self):
        class FakeResponse:
            def __init__(self, body, headers=None):
                self.body = body
                self.headers = headers or {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.body

        sse_result = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"data": {"data": [item()]}}),
                }]
            },
        }
        responses = [
            FakeResponse(
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"protocolVersion": "2025-03-26"},
                }).encode(),
                {"Mcp-Session-Id": "test-session", "Content-Type": "application/json"},
            ),
            FakeResponse(b"", {"Content-Type": "application/json"}),
            FakeResponse(
                ("data: " + json.dumps(sse_result) + "\n\n").encode(),
                {"Content-Type": "text/event-stream"},
            ),
        ]
        client = gupy.GupyMCPClient(endpoint="https://example.test/mcp")
        with patch("sources.gupy.urllib.request.urlopen", side_effect=responses) as opened:
            result = client.call_tool("search_jobs", {"term": "analista"})

        self.assertEqual(result["data"]["data"][0]["id"], 123)
        self.assertEqual(opened.call_count, 3)
        tool_request = opened.call_args_list[2].args[0]
        self.assertEqual(tool_request.get_method(), "POST")
        self.assertEqual(tool_request.get_header("Mcp-session-id"), "test-session")
        self.assertEqual(
            tool_request.get_header("Mcp-protocol-version"), "2025-03-26"
        )

    def test_rate_limit_retry_uses_server_delay_or_slow_1015_backoff(self):
        self.assertEqual(
            gupy.GupyMCPClient._retry_delay(429, "12", 1), 12
        )
        self.assertEqual(
            gupy.GupyMCPClient._retry_delay(429, "", 1, "Error 1015"), 30
        )
        self.assertEqual(gupy.GupyMCPClient._retry_delay(502, "", 2), 1)


if __name__ == "__main__":
    unittest.main()
