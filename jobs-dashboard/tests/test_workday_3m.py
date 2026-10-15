# -*- coding: utf-8 -*-
"""Regression tests for 3M's public Workday vacancies portal."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import REGISTRY, requested_portals_27082026  # noqa: E402


class ThreeMWorkdayTests(unittest.TestCase):
    def test_collects_brazil_jobs_through_the_public_workday_feed(self):
        payload = {
            "total": 1,
            "jobPostings": [{
                "title": "Analista de Sistemas",
                "locationsText": "São Paulo, Brazil",
                "externalPath": "/job/Brazil/Analista-de-Sistemas_12345",
                "bulletFields": ["12345"],
                "postedOn": "2026-10-14",
                "description": "<p>Suporte e análise de sistemas.</p>",
            }],
        }

        with patch.object(
            requested_portals_27082026, "post_json", return_value=payload
        ) as request:
            rows = requested_portals_27082026.fetch_3m()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "3m")
        self.assertEqual(rows[0]["native_id"], "12345")
        self.assertEqual(rows[0]["company"], "3M")
        self.assertEqual(rows[0]["country"], "BR")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["published_date"], "2026-10-14")
        self.assertEqual(
            rows[0]["url"],
            "https://3m.wd1.myworkdayjobs.com/pt-BR/Search/job/Brazil/Analista-de-Sistemas_12345",
        )

        self.assertEqual(
            request.call_args.args[0],
            "https://3m.wd1.myworkdayjobs.com/wday/cxs/3m/Search/jobs",
        )
        self.assertEqual(
            request.call_args.args[1]["appliedFacets"],
            {"Location_Country": ["1a29bb1357b240ab99a2fa755cc87c0e"]},
        )

    def test_3m_is_registered_exactly_once(self):
        names = [name for name, _fetch in REGISTRY]
        self.assertEqual(names.count("3m"), 1)
        self.assertIs(
            dict(REGISTRY)["3m"],
            requested_portals_27082026.fetch_3m,
        )


if __name__ == "__main__":
    unittest.main()
