import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from sources import REGISTRY
from sources import requested_portals_16092026 as portals


class RequestedPortalsTests(unittest.TestCase):
    def test_blacklion_uses_existing_quickin_company_collector(self):
        expected = [{"native_id": "blacklion-1"}]
        with patch.object(
            portals.quickin, "fetch_company", return_value=expected
        ) as fetch:
            self.assertEqual(portals.fetch_blacklion(), expected)

        fetch.assert_called_once_with(
            "blacklion",
            source="blacklion",
            company="Black Lion",
        )

    def test_jobgether_requests_and_keeps_only_brazil_postings(self):
        payload = [
            {
                "id": "brazil-1",
                "text": "Engenheira de Software",
                "categories": {
                    "location": "Brazil",
                    "commitment": "Full-time",
                    "team": "Engineering",
                },
                "hostedUrl": "https://jobs.lever.co/jobgether/brazil-1",
                "createdAt": 1789000000000,
            },
            {
                "id": "foreign-1",
                "text": "Engineer",
                "categories": {
                    "location": "Germany",
                    "commitment": "Full-time",
                    "team": "Engineering",
                },
                "hostedUrl": "https://jobs.lever.co/jobgether/foreign-1",
                "createdAt": 1789000000000,
            },
        ]
        with patch.object(portals, "get_json", return_value=payload) as get_json:
            rows = portals.fetch_jobgether()

        get_json.assert_called_once()
        self.assertEqual(
            get_json.call_args.args[0],
            "https://api.lever.co/v0/postings/jobgether?mode=json&location=Brazil",
        )
        self.assertEqual([row["native_id"] for row in rows], ["brazil-1"])
        self.assertEqual(rows[0]["company"], "Jobgether")
        self.assertEqual(rows[0]["market"], "BR")

    def test_jobgether_fails_closed_when_brazil_feed_is_empty(self):
        with patch.object(portals, "get_json", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "no Brazilian vacancies"):
                portals.fetch_jobgether()

    def test_asa_reads_rendered_public_listing_and_details(self):
        driver = MagicMock()
        driver.execute_script.side_effect = [
            [
                {
                    "title": "ANALISTA DE DADOS",
                    "url": "https://elevoplus.app/p/asa/vagas/analista-de-dados",
                    "text": "ANALISTA DE DADOS\nPresencial · Uberlândia, MG · PJ",
                }
            ],
            {
                "title": "ANALISTA DE DADOS",
                "text": (
                    "MODALIDADE\nPresencial\nLOCAL\nUberlândia, MG\n"
                    "CONTRATO\nPJ\nÁREA\nTecnologia\n"
                    "INSCRIÇÕES ATÉ\n15/10\nPUBLICADA EM\n15/09"
                ),
                "description": (
                    "SOBRE A OPORTUNIDADE\nPipeline de dados, Python e SQL."
                ),
            },
        ]
        with (
            patch.object(portals, "_new_asa_driver", return_value=driver),
            patch.object(portals, "_wait_for_asa_element"),
        ):
            rows = portals.fetch_asa(today=date(2026, 9, 16))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "asa")
        self.assertEqual(rows[0]["native_id"], "analista-de-dados")
        self.assertEqual(rows[0]["title"], "ANALISTA DE DADOS")
        self.assertEqual(rows[0]["company"], "ASA Digital")
        self.assertEqual(rows[0]["city"], "Uberlândia")
        self.assertEqual(rows[0]["state"], "MG")
        self.assertEqual(rows[0]["country"], "BR")
        self.assertEqual(rows[0]["work_model"], "on-site")
        self.assertEqual(rows[0]["contract_types"], ["PJ"])
        self.assertEqual(rows[0]["categories"], ["Tecnologia"])
        self.assertEqual(rows[0]["published_date"], "2026-09-15")
        self.assertEqual(rows[0]["expires_date"], "2026-10-15")
        self.assertIn("Python e SQL", rows[0]["description"])
        driver.quit.assert_called_once()

    def test_asa_fails_closed_when_public_page_has_no_job_cards(self):
        driver = MagicMock()
        driver.execute_script.return_value = []
        with (
            patch.object(portals, "_new_asa_driver", return_value=driver),
            patch.object(portals, "_wait_for_asa_element"),
            self.assertRaisesRegex(RuntimeError, "no public vacancies"),
        ):
            portals.fetch_asa(today=date(2026, 9, 16))

        driver.quit.assert_called_once()

    def test_asa_preserves_published_dates_and_rolls_over_deadlines(self):
        today = date(2026, 9, 16)
        self.assertEqual(portals._asa_date("15/07", today), "2026-07-15")
        self.assertEqual(
            portals._asa_date("15/01", today, rollover=True), "2027-01-15"
        )

    def test_requested_public_sources_are_registered(self):
        registry = dict(REGISTRY)
        self.assertIs(registry["blacklion"], portals.fetch_blacklion)
        self.assertIs(registry["jobgether"], portals.fetch_jobgether)
        self.assertIs(registry["asa"], portals.fetch_asa)


if __name__ == "__main__":
    unittest.main()
