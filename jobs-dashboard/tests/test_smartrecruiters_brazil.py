# -*- coding: utf-8 -*-
"""Contract tests for the global SmartRecruiters Brazil collector."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import smartrecruiters_brazil  # noqa: E402


class SmartRecruitersBrazilTests(unittest.TestCase):
    def test_discovery_extracts_unique_companies_from_job_links(self):
        markup = """
        <a href="https://jobs.smartrecruiters.com/RedBull/744000150145852-head-de-execucao-e-merchandising-">
          Head de Execução
        </a>
        <a href="/RedBull/744000150145852-head-de-execucao-e-merchandising-">
          duplicate
        </a>
        <a href="/OtherCompany/123456789-analista-de-dados">
          Analista
        </a>
        <a href="/careers">careers</a>
        """
        self.assertEqual(
            smartrecruiters_brazil.discover_companies(markup),
            ["RedBull", "OtherCompany"],
        )

    def test_catalog_paginates_filters_brazil_and_builds_canonical_url(self):
        pages = [
            {
                "content": [
                    {
                        "id": "br-1",
                        "name": "Head de Execução",
                        "location": {
                            "city": "São Paulo",
                            "region": "SP",
                            "country": "Brazil",
                        },
                    },
                    {
                        "id": "de-1",
                        "name": "Software Engineer",
                        "location": {
                            "city": "Stuttgart",
                            "region": "BW",
                            "country": "Germany",
                        },
                    },
                ],
                "totalFound": 3,
            },
            {
                "content": [
                    {
                        "id": "br-2",
                        "name": "Analista de Dados",
                        "location": {
                            "city": "Campinas",
                            "region": "SP",
                            "countryCode": "BR",
                        },
                    },
                ],
                "totalFound": 3,
            },
        ]
        with patch.object(smartrecruiters_brazil, "SMARTRECRUITERS_PAGE_SIZE", 2), \
             patch.object(smartrecruiters_brazil, "get_json", side_effect=pages) as request:
            rows = smartrecruiters_brazil._company_rows("RedBull")

        self.assertEqual([row["native_id"] for row in rows], ["br-1", "br-2"])
        self.assertEqual(rows[0]["country"], "BR")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(
            rows[0]["url"],
            "https://jobs.smartrecruiters.com/RedBull/br-1-head-de-execucao",
        )
        self.assertEqual(request.call_count, 2)
        self.assertIn("country=br", request.call_args_list[0].args[0])
        self.assertIn("limit=2&offset=0", request.call_args_list[0].args[0])
        self.assertIn("limit=2&offset=2", request.call_args_list[1].args[0])

    def test_fetch_deduplicates_companies_and_isolates_company_failure(self):
        good = {
            "source": "smartrecruiters_brazil",
            "native_id": "br-1",
            "title": "Head de Execução",
            "company": "RedBull",
            "url": "https://jobs.smartrecruiters.com/RedBull/br-1-head-de-execucao",
        }
        with patch.object(
            smartrecruiters_brazil,
            "get_text",
            return_value="<html></html>",
        ), patch.object(
            smartrecruiters_brazil,
            "discover_companies",
            return_value=["RedBull", "BrokenCompany", "RedBull"],
        ), patch.object(
            smartrecruiters_brazil,
            "_company_rows",
            side_effect=[[good], RuntimeError("upstream unavailable")],
        ):
            rows = smartrecruiters_brazil.fetch()

        self.assertEqual(rows, [good])


if __name__ == "__main__":
    unittest.main()
