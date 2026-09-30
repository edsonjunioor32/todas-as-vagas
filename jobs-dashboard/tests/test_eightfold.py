"""Tests for the public Eightfold career-site collector."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import eightfold  # noqa: E402
from pipeline import REGISTRY  # noqa: E402


def position(identifier, **overrides):
    row = {
        "id": identifier,
        "name": f"Analista {identifier}",
        "locations": ["Brazil", "Belo Horizonte, Minas Gerais, Brazil"],
        "work_location_option": "onsite",
        "t_create": 1790181153,
        "department": "Tecnologia",
        "business_unit": "Soluções",
        "job_description": "<p>Atuar com Python e dados.</p>",
        "canonicalPositionUrl": f"/careers/job/{identifier}",
    }
    row.update(overrides)
    return row


class EightfoldTests(unittest.TestCase):
    def test_vale_catalog_paginates_and_normalizes_public_positions(self):
        pages = [
            {"count": 3, "positions": [position(101), position(102)]},
            {"count": 3, "positions": [position(103)]},
        ]
        with patch.object(eightfold, "PAGE_SIZE", 2), patch.object(
            eightfold, "get_json", side_effect=pages
        ) as request:
            rows = eightfold.fetch_vale()

        self.assertEqual([row["native_id"] for row in rows], ["101", "102", "103"])
        self.assertEqual(request.call_count, 2)
        self.assertIn("start=0&limit=2", request.call_args_list[0].args[0])
        self.assertIn("start=2&limit=2", request.call_args_list[1].args[0])
        self.assertEqual(rows[0]["source"], "vale")
        self.assertEqual(rows[0]["company"], "Vale")
        self.assertEqual(rows[0]["country"], "BR")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["city"], "Belo Horizonte")
        self.assertEqual(rows[0]["state"], "Minas Gerais")
        self.assertEqual(rows[0]["work_model"], "on-site")
        self.assertTrue(rows[0]["published_date"].startswith("2026-09-23T"))
        self.assertEqual(rows[0]["categories"], ["Tecnologia", "Soluções"])
        self.assertEqual(rows[0]["description"], "Atuar com Python e dados.")
        self.assertEqual(rows[0]["url"], "https://vale.eightfold.ai/careers/job/101")

    def test_location_normalization_removes_country_and_region_prefixes(self):
        row = eightfold._normalize_position(position(
            104,
            locations=[
                "Minas Gerais, Brazil",
                "Nova Lima, State of Minas Gerais, Brazil",
            ],
        ))
        self.assertEqual(row["city"], "Nova Lima")
        self.assertEqual(row["state"], "Minas Gerais")

    def test_vale_rejects_a_truncated_page_when_count_says_more_exist(self):
        response = {"count": 5, "positions": [position(101)]}
        with patch.object(eightfold, "PAGE_SIZE", 2), patch.object(
            eightfold, "get_json", return_value=response
        ), self.assertRaisesRegex(RuntimeError, "incomplete pagination"):
            eightfold.fetch_vale()

    def test_vale_rejects_repeated_pages_instead_of_looping_or_truncating(self):
        response = {"count": 5, "positions": [position(101), position(102)]}
        with patch.object(eightfold, "PAGE_SIZE", 2), patch.object(
            eightfold, "get_json", side_effect=[response, response]
        ), self.assertRaisesRegex(RuntimeError, "no new positions"):
            eightfold.fetch_vale()

    def test_vale_uses_safe_canonical_fallback_for_untrusted_position_url(self):
        row = eightfold._normalize_position(
            position(123, canonicalPositionUrl="https://example.org/job/123")
        )
        self.assertEqual(row["url"], "https://vale.eightfold.ai/careers/job/123")

    def test_vale_is_registered_as_a_required_catalog_source(self):
        registry = dict(REGISTRY)
        self.assertIs(registry["vale"], eightfold.fetch_vale)


if __name__ == "__main__":
    unittest.main()
