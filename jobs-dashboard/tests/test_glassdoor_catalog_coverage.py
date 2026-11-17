# -*- coding: utf-8 -*-
"""Cobertura das notas Glassdoor no catálogo: Omkar sem URL e fila justa (sem rede)."""
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

import glassdoor  # noqa: E402
import glassdoor_catalog  # noqa: E402

SNAPSHOT = {
    "count": 4,
    "dict": {"company": ["Muitas Vagas", "Poucas Vagas", "Nunca Tentada"]},
    "jobs": {"cmp": [0, 0, 1, 2]},
}
NO_BROWSERLESS = {"BROWSERLESS_GLASSDOOR_ENABLED": "false"}


def entry(name, last_attempted=None):
    return {"company_names": [name], "status": "unavailable" if last_attempted else "",
            "last_attempted_date": last_attempted}


class CatalogCoverageTests(unittest.TestCase):
    def _run(self, catalog_profiles, batch_size, fetch):
        with patch.dict(os.environ, NO_BROWSERLESS), \
             patch.object(glassdoor_catalog, "fetch_profile", fetch):
            return glassdoor.update_catalog_cache(
                SNAPSHOT,
                {"schema_version": 1, "profiles": {}, "catalog_profiles": catalog_profiles},
                now=datetime(2026, 11, 17, 8, 0),
                batch_size=batch_size,
                fetcher=fetch,
                sleeper=lambda _seconds: None,
                profile_delay=0,
            )

    def test_without_browserless_the_company_is_still_queried_by_name(self):
        calls = []

        def fetch(profile, **kwargs):
            calls.append((profile["scraper_company"], profile.get("url")))
            return {"rating": 4.1, "review_count": 12, "source": "omkar"}

        updated, summary = self._run({}, 3, fetch)
        self.assertEqual(sorted(name for name, _ in calls),
                         ["Muitas Vagas", "Nunca Tentada", "Poucas Vagas"])
        self.assertTrue(all(url is None for _, url in calls))
        self.assertEqual(summary["succeeded"], 3)
        self.assertEqual(summary["resolution_disabled"], 0)
        rated = [e for e in updated["catalog_profiles"].values() if e["rating"] == 4.1]
        self.assertEqual(len(rated), 3)
        self.assertTrue(all(e["resolution_source"] == "name" for e in rated))

    def test_queue_prefers_never_attempted_then_oldest_attempt(self):
        calls = []

        def fetch(profile, **kwargs):
            calls.append(profile["scraper_company"])
            raise glassdoor.ProfileDataUnavailable("sem nota")

        keys = {name: glassdoor.company_key(name) for name in SNAPSHOT["dict"]["company"]}
        previous = {
            keys["Muitas Vagas"]: entry("Muitas Vagas", "2026-11-16"),
            keys["Poucas Vagas"]: entry("Poucas Vagas", "2026-11-10"),
        }
        self._run(previous, 2, fetch)
        self.assertEqual(calls, ["Nunca Tentada", "Poucas Vagas"])


if __name__ == "__main__":
    unittest.main()
