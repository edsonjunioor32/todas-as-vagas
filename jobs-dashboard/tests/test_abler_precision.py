"""Tests for the Precision RH Abler careers board."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import REGISTRY, requested_portals_27082026 as abler_portals  # noqa: E402
import notify_telegram  # noqa: E402


def vacancy(identifier, **overrides):
    attributes = {
        "title_formatted": f"Analista {identifier}",
        "company_name": "Precision RH",
        "country": "Brasil",
        "slug": f"precision-{identifier}",
        "city": "Curitiba",
        "state": "PR",
        "published_at": "2026-09-20T12:00:00Z",
        "work_type_formatted": "Presencial",
    }
    attributes.update(overrides)
    return {"id": str(identifier), "attributes": attributes}


class PrecisionRHAblerTests(unittest.TestCase):
    def test_board_is_registered_and_has_a_human_readable_label(self):
        registry = dict(REGISTRY)
        assert registry["precisionrh"] is abler_portals.fetch_precisionrh
        assert notify_telegram.SOURCE_LABELS["precisionrh"] == "Precision RH"

    def test_collection_follows_all_reported_pages_and_normalizes_rows(self):
        pages = [
            {"data": [vacancy(1001), vacancy(1002)], "meta": {"last": 2}},
            {"data": [vacancy(1003)], "meta": {"last": 2}},
        ]
        with patch.object(abler_portals, "get_json", side_effect=pages) as request:
            rows = abler_portals.fetch_precisionrh()

        self.assertEqual([row["native_id"] for row in rows], ["1001", "1002", "1003"])
        self.assertEqual(request.call_count, 2)
        self.assertIn("careers_pages/precision/vacancies", request.call_args_list[0].args[0])
        self.assertIn("page=1&per_page=100", request.call_args_list[0].args[0])
        self.assertIn("page=2&per_page=100", request.call_args_list[1].args[0])
        self.assertTrue(all(row["source"] == "precisionrh" for row in rows))
        self.assertTrue(all(row["company"] == "Precision RH" for row in rows))
        self.assertEqual(rows[0]["url"], "https://ats.abler.com.br/jobs/precision?slug=precision-1001")
        self.assertEqual(rows[0]["city"], "Curitiba")
        self.assertEqual(rows[0]["state"], "PR")
        self.assertEqual(rows[0]["market"], "BR")


if __name__ == "__main__":
    unittest.main()

