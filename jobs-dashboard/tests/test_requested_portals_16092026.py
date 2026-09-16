import unittest
from unittest.mock import patch

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

    def test_blacklion_and_jobgether_are_registered(self):
        registry = dict(REGISTRY)
        self.assertIs(registry["blacklion"], portals.fetch_blacklion)
        self.assertIs(registry["jobgether"], portals.fetch_jobgether)


if __name__ == "__main__":
    unittest.main()
