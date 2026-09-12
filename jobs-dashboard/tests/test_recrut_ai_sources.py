import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sources import recrut_ai, solides, taggui


class RecrutAiSourceTests(unittest.TestCase):
    def test_registry_has_all_tenants_and_savegnago_combines_boards(self):
        names = {name for name, _ in recrut_ai.TARGETS}
        self.assertEqual(
            names,
            {
                "petlove",
                "economart",
                "savegnago",
                "grupoluck",
                "grupokoch",
                "atakarejo",
                "bravante",
                "supermercadosvianense",
                "recibom",
                "vagasdiaadia",
                "grupovanguarda",
                "tirol",
                "novomateus",
            },
        )
        savegnago = next(
            config for config in recrut_ai.TENANTS if config["source"] == "savegnago"
        )
        self.assertEqual(len(savegnago["urls"]), 2)

    def test_recrut_urls_canonicalize_and_ignore_invalid(self):
        self.assertEqual(
            recrut_ai._canonical_url(
                "https://petlove.jobs.recrut.ai/job/da2214?utm_source=x"
            ),
            "https://petlove.jobs.recrut.ai/job/DA2214",
        )
        self.assertEqual(
            recrut_ai._canonical_url("https://petlove.jobs.recrut.ai/job/"),
            "",
        )

    def test_taggui_identity_canonicalization(self):
        url = taggui._canonical_url(
            "https://rs.tagguirh.com.br/visualizar-vaga/valemat/2181?x=1"
        )
        self.assertEqual(
            url,
            "https://rs.tagguirh.com.br/visualizar-vaga/valemat/2181",
        )
        self.assertEqual(taggui._native_id(url), "valemat:2181")

    def test_solides_default_cap(self):
        self.assertEqual(solides.DEFAULT_MAX_PAGES, 600)

    def test_solides_respects_configured_cap(self):
        calls = []

        def fake_page(page, cache_stats=None):
            calls.append(page)
            return {"totalPages": 1000}, []

        with patch.dict(
            os.environ,
            {"SOLIDES_MAX_PAGES": "600", "SOLIDES_WORKERS": "1"},
            clear=False,
        ), patch.object(solides, "_page", side_effect=fake_page):
            solides.fetch()

        self.assertEqual(len(calls), 600)


if __name__ == "__main__":
    unittest.main()
