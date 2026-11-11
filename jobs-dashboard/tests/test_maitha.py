# -*- coding: utf-8 -*-
"""Regression tests for the Maitha Tech public adapter."""
import sys
import unittest
from unittest.mock import patch

from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import maitha  # noqa: E402


class MaithaTests(unittest.TestCase):
    def test_normalize_remote_opportunity(self):
        row = maitha._normalize(
            {
                "id": "remote-1",
                "name": "Desenvolvedor Java Sr",
                "location": "REMOTO, REMOTO",
                "openingTime": "2026-11-05T19:52:43.486Z",
                "skills": ["JAVA", "SPRING"],
                "profile": "Sênior",
                "hiringType": "PJ",
            },
            {
                "_id": "remote-1",
                "name": "Desenvolvedor Java Sr",
                "description": "<p>Desenvolvimento backend.</p>",
                "opportunityLocation": {"address": "REMOTO, REMOTO"},
                "hiringType": "PJ",
                "specialities": ["JAVA", "SPRING"],
                "profile": "Sênior",
            },
        )
        self.assertEqual(row["source"], "maitha")
        self.assertEqual(row["company"], "Maitha Tech")
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brasil")
        self.assertEqual(row["country"], "BR")
        self.assertEqual(row["published_date"], "2026-11-05T19:52:43+00:00")
        self.assertEqual(row["contract_types"], ["PJ"])
        self.assertEqual(row["skills"], ["JAVA", "SPRING"])
        self.assertIn("Desenvolvimento backend", row["description"])
        self.assertEqual(
            row["url"],
            "https://maitha.com.br/vaga.html?id=remote-1",
        )

    def test_fetch_uses_public_list_and_detail_endpoints(self):
        listing = {
            "data": {
                "opportunitiesList": [
                    {
                        "id": "job-1",
                        "name": "Analista de Suporte",
                        "location": "São Paulo, SP",
                        "openingTime": "2026-11-06T14:25:08.817Z",
                        "skills": ["SUPORTE"],
                        "profile": "Pleno",
                        "hiringType": "PJ",
                    }
                ],
                "pagination": {"totalDocs": 1, "totalPages": 1},
            }
        }
        detail = {
            "status": 200,
            "data": {
                "_id": "job-1",
                "name": "Analista de Suporte",
                "description": "Atendimento e sustentação.",
                "opportunityLocation": {"address": "São Paulo, SP"},
                "hiringType": "PJ",
                "specialities": ["SUPORTE", "SQL"],
                "profile": "Pleno",
            },
        }
        with patch.object(
            maitha,
            "get_json",
            side_effect=[listing, detail],
        ) as request:
            rows = maitha.fetch()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], "job-1")
        self.assertEqual(rows[0]["city"], "São Paulo")
        self.assertEqual(rows[0]["state"], "SP")
        self.assertEqual(rows[0]["skills"], ["SUPORTE", "SQL"])
        self.assertEqual(rows[0]["description"], "Atendimento e sustentação.")
        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
