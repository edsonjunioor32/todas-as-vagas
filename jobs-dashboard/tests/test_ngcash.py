# -*- coding: utf-8 -*-

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import NONEMPTY_SOURCES
from sources import REGISTRY, ngcash


POSTING_ID = "c63ec957-492e-4955-a229-a4443320c1a5"


def listing(title="Staff Product Manager", name="Brasil", kind="remote"):
    return {
        "id": POSTING_ID,
        "title": title,
        "locations": [
            {
                "name": name,
                "type": kind,
                "country": {"name": "Brazil"},
            }
        ],
        "function": {"name": "Product"},
    }


def detail(title="Staff Product Manager"):
    return {
        "id": POSTING_ID,
        "title": title,
        "description": "<h2>Sobre a vaga</h2><p>Experiência com produto.</p>",
        "creation_date_time": "2026-09-20T12:30:00Z",
        "function": {"name": "Product"},
    }


def page(results, total=1):
    return {
        "count": len(results),
        "pages": {"next": None, "previous": None, "total": total, "page_size": 100},
        "results": results,
    }


class NGCashSourceTests(unittest.TestCase):
    def test_normalizes_remote_position_from_public_api_payloads(self):
        row = ngcash._normalize_position(listing(), detail())

        self.assertEqual(row["source"], "ngcash")
        self.assertEqual(row["native_id"], POSTING_ID)
        self.assertEqual(row["company"], "NG.CASH")
        self.assertEqual(row["title"], "Staff Product Manager")
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brasil")
        self.assertEqual(row["country"], "BR")
        self.assertEqual(row["market"], "BR")
        self.assertEqual(row["published_date"], "2026-09-20T12:30:00+00:00")
        self.assertEqual(row["categories"], ["Product"])
        self.assertEqual(row["description"], "Sobre a vaga Experiência com produto.")
        self.assertEqual(
            row["url"],
            "https://revolutpeople.com/ngcash/public/careers/position/"
            "staff-product-manager-" + POSTING_ID,
        )

    def test_normalizes_office_position(self):
        row = ngcash._normalize_position(
            listing(
                title="Antifraud Specialist - Credit",
                name="São Paulo",
                kind="office",
            ),
            detail(title="Antifraud Specialist - Credit"),
        )

        self.assertEqual(row["work_model"], "on-site")
        self.assertEqual(row["city"], "São Paulo")
        self.assertEqual(row["state"], "SP")

    def test_fetch_uses_public_list_and_detail_apis(self):
        with patch.object(
            ngcash,
            "get_json",
            side_effect=[page([listing()]), detail()],
        ) as request:
            rows = ngcash.fetch()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], POSTING_ID)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            request.call_args_list[0].args[0],
            ngcash.POSTINGS_API + "?page=1",
        )
        self.assertEqual(
            request.call_args_list[1].args[0],
            f"{ngcash.DETAILS_API}/{POSTING_ID}",
        )

    def test_fetch_follows_pagination(self):
        second_id = "d45275d7-742f-4754-a7ea-34108291a7aa"
        second_listing = {
            **listing(title="Talent Acquisition Specialist"),
            "id": second_id,
            "locations": listing()["locations"],
        }
        second_detail = {
            **detail(title="Talent Acquisition Specialist"),
            "id": second_id,
        }

        with patch.object(
            ngcash,
            "get_json",
            side_effect=[
                page([listing()], total=2),
                page([second_listing], total=2),
                detail(),
                second_detail,
            ],
        ) as request:
            rows = ngcash.fetch()

        self.assertEqual(len(rows), 2)
        self.assertEqual(request.call_count, 4)
        self.assertIn("?page=2", request.call_args_list[1].args[0])

    def test_detail_failure_keeps_public_listing(self):
        with patch.object(
            ngcash,
            "get_json",
            side_effect=[page([listing()]), TimeoutError("detail timeout")],
        ):
            rows = ngcash.fetch()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Staff Product Manager")
        self.assertEqual(rows[0]["description"], "")

    def test_non_brazil_listing_is_ignored(self):
        posting = listing()
        posting["locations"][0]["country"]["name"] = "Argentina"
        self.assertIsNone(ngcash._normalize_position(posting, detail()))

    def test_is_registered_and_protected(self):
        registered = dict(REGISTRY)
        self.assertIs(registered["ngcash"], ngcash.fetch)
        self.assertIn("ngcash", NONEMPTY_SOURCES)
        self.assertEqual(
            sum(name == "ngcash" for name, _fetch in REGISTRY),
            1,
        )


if __name__ == "__main__":
    unittest.main()
