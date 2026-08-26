# -*- coding: utf-8 -*-
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sources import mercadolivre  # noqa: E402


class MercadoLivreTests(unittest.TestCase):
    def test_next_payload_is_normalized(self):
        payload = {
            "props": {"pageProps": {"positions": [{
                "id": 42885806,
                "title": "Analista de Suporte Pleno",
                "location": "São Paulo, Brasil",
                "country": "Brazil",
                "workModel": "HYBRID",
                "employmentType": "FULL_TIME",
                "department": "Tecnologia",
                "publishedAt": "2026-08-25T10:00:00Z",
                "description": "Atuar com suporte e operações.",
            }]}}
        }
        markup = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload, ensure_ascii=False)
            + "</script>"
        )
        rows = mercadolivre._parse_markup(markup)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], "42885806")
        self.assertEqual(rows[0]["work_model"], "hybrid")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["contract_types"], ["FULL_TIME"])
        self.assertEqual(rows[0]["published_date"], "2026-08-25T10:00:00+00:00")

    def test_html_anchor_fallback_is_normalized(self):
        markup = (
            '<a href="/pt/positions?id=41752175" aria-label="Vaga">'
            "Especialista de Operações"
            "</a>"
        )
        rows = mercadolivre._parse_markup(markup)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], "41752175")
        self.assertEqual(rows[0]["url"], "https://careers-meli.mercadolibre.com/pt/positions?id=41752175")

    def test_fetch_uses_browser_links_when_cdn_rejects_http(self):
        links = [(
            "https://careers-meli.mercadolibre.com/pt/positions?id=42885806",
            "Analista de Operações",
        )]
        with patch.object(mercadolivre, "get_text", side_effect=RuntimeError("403")), \
             patch.object(mercadolivre, "rendered_links", return_value=links):
            rows = mercadolivre.fetch()
        self.assertEqual([row["native_id"] for row in rows], ["42885806"])
        self.assertEqual(rows[0]["company"], "Mercado Livre")


if __name__ == "__main__":
    unittest.main()
