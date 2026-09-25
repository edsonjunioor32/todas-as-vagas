# -*- coding: utf-8 -*-
"""Regression checks for portal-level failures that must not poison collection."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import geekhunter, wellfound  # noqa: E402
import pipeline  # noqa: E402


class PortalSourceResilienceTests(unittest.TestCase):
    def test_ntt_data_skips_a_malformed_nested_row_and_keeps_valid_jobs(self):
        malformed = {"id": "broken", "atsJob": "unexpected string"}
        valid = {
            "id": "ntt-1",
            "atsJob": {
                "id": "ntt-1",
                "jobSlug": "analista-qa",
                "company": {"slug": "ntt-data"},
                "atsJobDetail": {
                    "title": "Analista QA",
                    "workModality": "Remote",
                    "description": "Qualidade de software.",
                },
            },
        }
        with patch.object(
            geekhunter,
            "_page",
            return_value=([malformed, valid], {"lastPage": 1}),
        ):
            rows = geekhunter._catalog(
                geekhunter.NTT_DATA_BASE,
                "nttdata",
                company_filter="nttdata",
                company_override="NTT DATA",
            )

        self.assertEqual([row["native_id"] for row in rows], ["ntt-1"])

    def test_wellfound_detail_404_does_not_discard_other_listed_jobs(self):
        location_url = "https://wellfound.com/location/brazil"
        listing = """
        <a href="/jobs/101-expired-role">Expired role</a>
        <a href="/jobs/202-active-role">Active role</a>
        """
        posting = {
            "@type": "JobPosting",
            "title": "Active role",
            "identifier": {"value": "202"},
            "hiringOrganization": {"name": "Example Brasil"},
            "description": "<p>Public role description.</p>",
            "jobLocation": [{"address": {"addressCountry": "Brazil"}}],
        }
        detail = (
            "<h1>Active role</h1><script type='application/ld+json'>"
            + json.dumps(posting)
            + "</script>"
        )

        def fake_get_text(url, **_kwargs):
            if url == location_url:
                return listing
            if url.endswith("/jobs/101-expired-role"):
                raise RuntimeError("HTTP Error 404: Not Found")
            if url.endswith("/jobs/202-active-role"):
                return detail
            raise AssertionError(f"Unexpected URL: {url}")

        with patch.object(wellfound, "LOCATION_URLS", (location_url,)):
            with patch.object(wellfound, "get_text", side_effect=fake_get_text):
                rows = wellfound.fetch()

        self.assertEqual([row["native_id"] for row in rows], ["202"])
        self.assertEqual(rows[0]["title"], "Active role")

    def test_blocked_upstream_sources_are_paused_and_preserved(self):
        paused = {"ngcash"}
        selected = {name for name, _fetch in pipeline.selected_registry("")}
        self.assertTrue(paused.issubset(pipeline.PAUSED_SOURCES))
        self.assertTrue(paused.isdisjoint(selected))
        self.assertTrue(paused.issubset(set(pipeline.sources_to_preserve([]))))
        removed = {"cprocco", "atitude"}
        self.assertEqual(removed, pipeline.REMOVED_SOURCES)
        self.assertTrue(removed.isdisjoint(set(pipeline.sources_to_preserve([]))))
        self.assertTrue(removed.isdisjoint(selected))
        for name in removed:
            with self.assertRaises(SystemExit):
                pipeline.selected_registry(name)
        for name in paused:
            with self.assertRaises(SystemExit):
                pipeline.selected_registry(name)


if __name__ == "__main__":
    unittest.main()
