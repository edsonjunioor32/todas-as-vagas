from unittest.mock import patch

import pytest

from sources import requested_portals_16092026 as portals


def test_blacklion_uses_existing_quickin_company_collector():
    expected = [{"native_id": "blacklion-1"}]
    with patch.object(portals.quickin, "fetch_company", return_value=expected) as fetch:
        assert portals.fetch_blacklion() == expected

    fetch.assert_called_once_with(
        "blacklion",
        source="blacklion",
        company="Black Lion",
    )


def test_jobgether_requests_and_keeps_only_brazil_postings():
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
    assert get_json.call_args.args[0] == (
        "https://api.lever.co/v0/postings/jobgether?mode=json&location=Brazil"
    )
    assert [row["native_id"] for row in rows] == ["brazil-1"]
    assert rows[0]["company"] == "Jobgether"
    assert rows[0]["market"] == "BR"


def test_jobgether_fails_closed_when_brazil_feed_is_empty():
    with patch.object(portals, "get_json", return_value=[]):
        with pytest.raises(RuntimeError, match="no Brazilian vacancies"):
            portals.fetch_jobgether()
