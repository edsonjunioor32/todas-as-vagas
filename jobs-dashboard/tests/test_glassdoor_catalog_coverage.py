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
    "dict": {"company": ["Empresa Grande", "Empresa Pequena", "Nunca Tentada"]},
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
                         ["Empresa Grande", "Empresa Pequena", "Nunca Tentada"])
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
            keys["Empresa Grande"]: entry("Empresa Grande", "2026-11-16"),
            keys["Empresa Pequena"]: entry("Empresa Pequena", "2026-11-10"),
        }
        self._run(previous, 2, fetch)
        self.assertEqual(calls, ["Nunca Tentada", "Empresa Pequena"])


class NameCleanupTests(unittest.TestCase):
    def test_legal_suffix_free(self):
        cases = {
            "Wiz, Inc.": "Wiz",
            "Banco XYZ S.A.": "Banco XYZ",
            "LOJA ELETRICA LIMITADA": "LOJA ELETRICA",
            "Quantum-Systems GmbH": "Quantum-Systems",
            "Empresa Exemplo Ltda.": "Empresa Exemplo",
            "Squadra": None,
            "Acme": None,
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(glassdoor_catalog.legal_suffix_free(name), expected)

    def test_invalid_company_names(self):
        for name in ("Homologação - Vagas", "Vagas Granjas São José",
                     "Legal Counsel - 12 month FTC at Rightmove Greenhouse", "x" * 121):
            with self.subTest(name=name[:30]):
                self.assertTrue(glassdoor_catalog.invalid_company_name(name))
        for name in ("Vagabundo Bar", "Squadra", "Wiz, Inc."):
            with self.subTest(name=name):
                self.assertFalse(glassdoor_catalog.invalid_company_name(name))

    def _run(self, companies, fetch):
        snapshot = {"count": len(companies), "dict": {"company": companies},
                    "jobs": {"cmp": list(range(len(companies)))}}
        with patch.dict(os.environ, NO_BROWSERLESS), \
             patch.object(glassdoor_catalog, "fetch_profile", fetch):
            return glassdoor.update_catalog_cache(
                snapshot, {"schema_version": 1, "profiles": {}, "catalog_profiles": {}},
                now=datetime(2026, 11, 17, 8, 0), batch_size=10, fetcher=fetch,
                sleeper=lambda _s: None, profile_delay=0,
            )

    def test_retries_without_suffix_and_accepts_only_exact_names(self):
        calls = []

        def fetch(profile, **kwargs):
            calls.append((profile["scraper_company"], tuple(profile["company_names"])))
            if profile["scraper_company"] == "Wiz":
                return {"rating": 4.5, "review_count": 80}
            raise glassdoor.ProfileDataUnavailable("nome não confere")

        updated, summary = self._run(["Wiz, Inc."], fetch)
        self.assertEqual(calls, [("Wiz, Inc.", ("Wiz, Inc.",)),
                                 ("Wiz", ("Wiz, Inc.", "Wiz"))])
        self.assertEqual(summary["suffix_retry_succeeded"], 1)
        self.assertEqual(summary["succeeded"], 1)
        rating = next(iter(updated["catalog_profiles"].values()))["rating"]
        self.assertEqual(rating, 4.5)

    def test_failed_retry_keeps_company_unavailable(self):
        def fetch(profile, **kwargs):
            raise glassdoor.ProfileDataUnavailable("sem perfil")

        updated, summary = self._run(["Loja Eletrica Ltda"], fetch)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["suffix_retry_succeeded"], 0)
        self.assertEqual(next(iter(updated["catalog_profiles"].values()))["status"], "unavailable")

    def test_invalid_names_are_skipped_without_queries_or_batch_slots(self):
        calls = []

        def fetch(profile, **kwargs):
            calls.append(profile["scraper_company"])
            return {"rating": 4.0, "review_count": 5}

        updated, summary = self._run(["Homologação - Vagas", "Empresa Real"], fetch)
        self.assertEqual(calls, ["Empresa Real"])
        self.assertEqual(summary["invalid_names"], 1)
        invalid = updated["catalog_profiles"][glassdoor.company_key("Homologação - Vagas")]
        self.assertEqual(invalid["resolution_reason"], "invalid_company_name")


class CatalogPriorityAndSloganTests(unittest.TestCase):
    def test_alternative_name_strips_slogan_and_suffix(self):
        alt = glassdoor_catalog.alternative_company_name
        self.assertEqual(alt("Assaí Atacadista - O atacadista com 50 anos"), "Assaí Atacadista")
        self.assertEqual(alt("CONDOR - CENTRAL"), "CONDOR")
        self.assertEqual(alt("Drogal Farmaceutica LTDA"), "Drogal Farmaceutica")
        self.assertEqual(alt("Atrio Hoteis SA"), "Atrio Hoteis")
        self.assertIsNone(alt("Savegnago"))
        self.assertIsNone(alt("Coca-Cola"))

    def test_generic_career_pages_are_invalid(self):
        self.assertTrue(glassdoor_catalog.invalid_company_name("Página de Carreira"))
        self.assertTrue(glassdoor_catalog.invalid_company_name("Trabalhe Conosco"))
        self.assertFalse(glassdoor_catalog.invalid_company_name("Concremat"))

    def test_not_really_attempted_companies_return_to_front_of_queue(self):
        snapshot = {"dict": {"company": ["Grande", "Antiga"]}, "jobs": {"cmp": [0, 0, 0, 1]}}
        previous = {"profiles": {}, "catalog_profiles": {
            glassdoor.company_key("Grande"): {**entry("Grande", "2026-11-16"),
                                              "resolution_reason": "browserless_disabled"},
            glassdoor.company_key("Antiga"): entry("Antiga", "2026-11-10"),
        }}
        calls = []

        def fetch(profile, **kwargs):
            calls.append(profile["scraper_company"])
            return {"rating": 4.0, "source": "omkar"}

        with patch.dict(os.environ, NO_BROWSERLESS):
            glassdoor.update_catalog_cache(snapshot, previous, now=datetime(2026, 11, 17, 8, 0),
                                           batch_size=1, fetcher=fetch,
                                           sleeper=lambda _s: None, profile_delay=0)
        self.assertEqual(calls, ["Grande"])

    def test_slogan_retry_uses_clean_name(self):
        snapshot = {"dict": {"company": ["Assaí Atacadista - O atacadista"]}, "jobs": {"cmp": [0]}}
        calls = []

        def fetch(profile, **kwargs):
            calls.append(profile["scraper_company"])
            if profile["scraper_company"] == "Assaí Atacadista":
                return {"rating": 3.9, "source": "omkar"}
            return {"rating": None, "source": "omkar"}

        with patch.dict(os.environ, NO_BROWSERLESS):
            updated, summary = glassdoor.update_catalog_cache(
                snapshot, {"profiles": {}, "catalog_profiles": {}},
                now=datetime(2026, 11, 17, 8, 0), batch_size=5, fetcher=fetch,
                sleeper=lambda _s: None, profile_delay=0)
        self.assertEqual(calls, ["Assaí Atacadista - O atacadista", "Assaí Atacadista"])
        self.assertEqual(summary["succeeded"], 1)


if __name__ == "__main__":
    unittest.main()
