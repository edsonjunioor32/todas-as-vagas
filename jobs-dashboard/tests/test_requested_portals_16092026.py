import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from sources import REGISTRY
from sources import requested_portals_16092026 as portals
from sources import unlockcareer as unlockcareer_portals


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

    def test_unlockcareer_reads_visible_brazil_roles_and_normalizes_them(self):
        driver = MagicMock()
        search = MagicMock()
        driver.find_element.return_value = search
        driver.execute_script.return_value = [
            {
                "title": "Engineering Expert",
                "url": (
                    "https://unlockcareer.ai/jobs/mavila-consulting/apply/"
                    "154da33d-caf9-42c5-925c-f180ca93098c"
                ),
                "text": (
                    "AI Trainer / Data Annotator Brazil Colombia Senior Remote "
                    "Python Electrical Engineering\nRole Overview: Create and "
                    "validate engineering simulation tasks.\nPosted 15/09/2026"
                ),
            },
            {
                "title": "Regional Consultant",
                "url": (
                    "https://unlockcareer.ai/jobs/mavila-consulting/apply/"
                    "6a4b3a40-9947-4bd0-a174-31f74559f4a1"
                ),
                "text": "Consulting United States On-site\nPosted 14/09/2026",
            },
        ]
        with (
            patch.object(
                unlockcareer_portals, "_new_driver", return_value=driver
            ),
            patch.object(unlockcareer_portals, "_wait_for_element"),
        ):
            rows = unlockcareer_portals.fetch_mavila_consulting(
                today=date(2026, 9, 16)
            )

        search.clear.assert_called_once()
        search.send_keys.assert_called_once_with("Brazil")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "unlockcareer_mavila")
        self.assertEqual(
            rows[0]["native_id"], "154da33d-caf9-42c5-925c-f180ca93098c"
        )
        self.assertEqual(rows[0]["company"], "Mavila Consulting")
        self.assertEqual(rows[0]["country"], "BR")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["work_model"], "remote")
        self.assertEqual(rows[0]["published_date"], "2026-09-15")
        self.assertIn("engineering simulation tasks", rows[0]["description"])
        driver.quit.assert_called_once()

    def test_unlockcareer_fails_closed_when_no_brazil_roles_are_rendered(self):
        driver = MagicMock()
        driver.find_element.return_value = MagicMock()
        driver.execute_script.return_value = [
            {
                "title": "Regional Consultant",
                "url": (
                    "https://unlockcareer.ai/jobs/mavila-consulting/apply/"
                    "6a4b3a40-9947-4bd0-a174-31f74559f4a1"
                ),
                "text": "United States On-site",
            }
        ]
        with (
            patch.object(
                unlockcareer_portals, "_new_driver", return_value=driver
            ),
            patch.object(unlockcareer_portals, "_wait_for_element"),
            self.assertRaisesRegex(RuntimeError, "no Brazilian vacancies"),
        ):
            unlockcareer_portals.fetch_mavila_consulting(
                today=date(2026, 9, 16)
            )

        driver.quit.assert_called_once()

    def test_unlockcareer_normalizes_posted_dates_without_locale_ambiguity(self):
        self.assertEqual(
            unlockcareer_portals._posted_date("Posted 15/09/2026"),
            "2026-09-15",
        )
        self.assertEqual(
            unlockcareer_portals._posted_date("Posted 9/15/2026"),
            "2026-09-15",
        )


    def test_gft_parses_paginated_public_listing(self):
        listing_one = "".join(
            (
                f'<a href="/job/Alphaville-Remote-Engineer-{1001 + index}/'
                f'{1001 + index}/">Remote Python Engineer {index}</a>'
            )
            for index in range(25)
        )
        listing_two = (
            '<a href="/job/Sao-Paulo-Data-Engineer-2001/2001/">'
            "Data Engineer"
            "</a>"
        )
        detail_rows = []

        def fake_detail(row):
            detail_rows.append(row)
            return portals.job(
                "gft",
                row["native_id"],
                title=row["title"],
                company="GFT Technologies",
                url=row["url"],
                country="BR",
                market="BR",
            )

        with (
            patch.object(
                portals,
                "get_text",
                side_effect=[listing_one, listing_two],
            ) as get_text,
            patch.object(portals, "_gft_detail", side_effect=fake_detail),
        ):
            rows = portals.fetch_gft()

        self.assertEqual(len(rows), 26)
        self.assertEqual(
            [call.args[0] for call in get_text.call_args_list],
            [portals.GFT_LISTING_URL, portals.GFT_LISTING_URL + "&startrow=25"],
        )
        self.assertEqual(
            {row["native_id"] for row in detail_rows},
            {str(1001 + index) for index in range(25)} | {"2001"},
        )

    def test_gft_normalizes_public_jobposting_metadata(self):
        detail = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","title":"Cloud Security Specialist",'
            '"datePosted":"2026-09-17","description":"<p>Remote GCP security.</p>",'
            '"employmentType":"FULL_TIME",'
            '"jobLocation":{"address":{"addressLocality":"Barueri",'
            '"addressRegion":"SP","addressCountry":"BR"}},'
            '"occupationalCategory":"Technology"}'
            "</script>"
        )
        row = {
            "native_id": "1437281333",
            "title": "Cloud Security Specialist",
            "url": (
                "https://jobs.gft.com/job/Barueri-Cloud-Security-1437281333/"
                "1437281333/"
            ),
        }
        with patch.object(portals, "get_text", return_value=detail):
            vacancy = portals._gft_detail(row)

        self.assertEqual(vacancy["source"], "gft")
        self.assertEqual(vacancy["company"], "GFT Technologies")
        self.assertEqual(vacancy["city"], "Barueri")
        self.assertEqual(vacancy["state"], "SP")
        self.assertEqual(vacancy["country"], "BR")
        self.assertEqual(vacancy["market"], "BR")
        self.assertEqual(vacancy["published_date"], "2026-09-17")
        self.assertEqual(vacancy["contract_types"], ["FULL_TIME"])
        self.assertEqual(vacancy["categories"], ["Technology"])
        self.assertEqual(vacancy["work_model"], "remote")
        self.assertIn("Remote GCP security", vacancy["description"])


    def test_requested_public_sources_are_registered(self):
        registry = dict(REGISTRY)
        self.assertIs(registry["blacklion"], portals.fetch_blacklion)
        self.assertIs(registry["jobgether"], portals.fetch_jobgether)
        self.assertIs(registry["asa"], portals.fetch_asa)
        self.assertIs(registry["gft"], portals.fetch_gft)
        self.assertIs(
            registry["unlockcareer_mavila"],
            unlockcareer_portals.fetch_mavila_consulting,
        )


if __name__ == "__main__":
    unittest.main()
