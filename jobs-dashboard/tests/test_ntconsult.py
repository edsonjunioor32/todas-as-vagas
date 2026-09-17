# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources import ntconsult


class NTConsultSourceTests(unittest.TestCase):
    def test_fetch_reads_all_public_pages_and_normalizes_detail(self):
        first_page = '<a href="/Visualizar/101">Visualizar Vaga</a>'
        second_page = '<a href="/Visualizar/102">Visualizar Vaga</a>'
        detail = """
        <html><head>
          <meta property="og:title" content="Oportunidade de AI Engineer Pleno">
          <meta property="og:description" content="Python, APIs REST e Docker.">
        </head><body>
          <h1>AI Engineer Pleno</h1>
          <h5>Local: Porto Alegre/RS</h5>
          <h5>Tipo de Contratação CLT</h5>
          <h5>Publicada em: 17/09/2026</h5>
          <h5>Experiência: Sênior</h5>
        </body></html>
        """

        def fake_text(url, **_kwargs):
            if url == ntconsult.LISTING_URL:
                return first_page
            return detail

        def fake_json(url, **_kwargs):
            if "page=2" in url:
                return {"sucesso": True, "viewLista": second_page}
            return {"sucesso": True, "viewLista": ""}

        with patch.object(ntconsult, "get_text", side_effect=fake_text):
            with patch.object(ntconsult, "get_json", side_effect=fake_json):
                rows = ntconsult.fetch()

        self.assertEqual([row["native_id"] for row in rows], ["101", "102"])
        self.assertEqual(rows[0]["company"], "NTConsult")
        self.assertEqual(rows[0]["city"], "Porto Alegre")
        self.assertEqual(rows[0]["state"], "RS")
        self.assertEqual(rows[0]["country"], "BR")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["published_date"], "2026-09-17")
        self.assertEqual(rows[0]["contract_types"], ["CLT"])
        self.assertIn("Python", rows[0]["description"])


if __name__ == "__main__":
    unittest.main()
