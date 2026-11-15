# -*- coding: utf-8 -*-
"""Fontes geradas a partir das configurações por plataforma (sem rede)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import REGISTRY, abler, ats_boards, requested_portals_27082026, workday  # noqa: E402

WORKDAY_SOURCES = ["avanade", "santander", "iberdrola", "iqvia", "mdlz", "edenred", "acciona"]
ABLER_SOURCES = ["talentodovalesc", "precisionrh"]
LEVER_SOURCES = ["flash", "neon", "zippi", "bv"]


class PlatformTargetTests(unittest.TestCase):
    def test_targets_are_generated_from_each_platform_config(self):
        self.assertEqual([name for name, _ in workday.TARGETS], list(workday.TENANTS))
        self.assertEqual([name for name, _ in abler.BOARD_TARGETS],
                         [source for source, _sub, _company in abler.BOARDS])
        self.assertEqual([name for name, _ in ats_boards.LEVER_BOARD_TARGETS],
                         [source for source, _board, _company in ats_boards.LEVER_BOARDS])

    def test_registry_keeps_every_source_name_once_and_uses_platform_fetchers(self):
        names = [name for name, _ in REGISTRY]
        registry = dict(REGISTRY)
        expectations = (
            (WORKDAY_SOURCES, workday.FETCHERS),
            (ABLER_SOURCES, abler.BOARD_FETCHERS),
            (LEVER_SOURCES, ats_boards.LEVER_BOARD_FETCHERS),
        )
        for sources, fetchers in expectations:
            for name in sources:
                with self.subTest(source=name):
                    self.assertEqual(names.count(name), 1)
                    self.assertIs(registry[name], fetchers[name])

    def test_legacy_module_keeps_aliases_and_dynamic_portal_targets(self):
        legacy = requested_portals_27082026
        self.assertIs(legacy.WORKDAY, workday.TENANTS)
        self.assertIs(legacy._workday_rows, workday.fetch_tenant)
        self.assertIs(legacy._abler_rows, abler.fetch_board)
        self.assertIs(legacy.fetch_lever_board, ats_boards.fetch_lever_board)
        self.assertIs(legacy.fetch_abler_talentodovalesc, abler.BOARD_FETCHERS["talentodovalesc"])
        for name in WORKDAY_SOURCES:
            self.assertIs(getattr(legacy, f"fetch_{name}"), workday.FETCHERS[name])
        for name in LEVER_SOURCES:
            self.assertIs(getattr(legacy, f"fetch_{name}"), ats_boards.LEVER_BOARD_FETCHERS[name])
        # Validador e mesclador de portais dinâmicos dependem desta lista.
        self.assertEqual(
            [name for name, _ in legacy.TARGETS],
            ["avanade", "huntit", "talentodovalesc", "precisionrh", "beq", "forza",
             "saleco", "elis", "flash", "neon", "zippi", "bv", "santander",
             "iberdrola", "iqvia", "mdlz", "edenred"],
        )

    def test_fetchers_have_descriptive_names(self):
        self.assertEqual(workday.FETCHERS["mdlz"].__name__, "fetch_mdlz")
        self.assertEqual(abler.BOARD_FETCHERS["precisionrh"].__name__, "fetch_precisionrh")
        self.assertEqual(ats_boards.LEVER_BOARD_FETCHERS["bv"].__name__, "fetch_bv")

    def test_lever_board_rows_keep_source_company_and_market(self):
        payload = [{
            "id": "abc",
            "text": "Pessoa Desenvolvedora",
            "hostedUrl": "https://jobs.lever.co/flashapp/abc",
            "createdAt": 1762300800000,
            "categories": {"location": "São Paulo", "commitment": "Remoto",
                           "department": "Engenharia"},
        }]
        with patch.object(ats_boards, "get_json", return_value=payload) as request:
            rows = ats_boards.LEVER_BOARD_FETCHERS["flash"]()
        self.assertIn("api.lever.co/v0/postings/flashapp", request.call_args.args[0])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "flash")
        self.assertEqual(rows[0]["company"], "Flash")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["categories"], ["Engenharia"])

    def test_empty_lever_board_fails_loudly(self):
        with patch.object(ats_boards, "get_json", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "Lever/neon returned no vacancies"):
                ats_boards.LEVER_BOARD_FETCHERS["neon"]()


if __name__ == "__main__":
    unittest.main()
