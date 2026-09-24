# -*- coding: utf-8 -*-

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import NONEMPTY_SOURCES
from sources import REGISTRY, ngcash


class NGCashSourceTests(unittest.TestCase):
    def test_normalizes_remote_position(self):
        row = ngcash._normalize_position(
            "staff-product-manager-c63ec957-492e-4955-a229-a4443320c1a5",
            "Staff Product Manager",
            "Remote: Brasil",
            "Staff Product Manager\nRemote: Brasil",
        )
        self.assertEqual(row["source"], "ngcash")
        self.assertEqual(row["native_id"], "staff-product-manager-c63ec957-492e-4955-a229-a4443320c1a5")
        self.assertEqual(row["company"], "NG.CASH")
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brasil")
        self.assertEqual(row["country"], "BR")
        self.assertEqual(row["url"], "https://people-jobs.com/ngcash/public/careers/position/staff-product-manager-c63ec957-492e-4955-a229-a4443320c1a5")

    def test_normalizes_office_position(self):
        row = ngcash._normalize_position(
            "antifraud-specialist-credit-6048c6d7-b9a3-41ad-a4a1-a877b198cd2d",
            "Antifraud Specialist - Credit",
            "Office: São Paulo",
            "Antifraud Specialist - Credit\nOffice: São Paulo",
        )
        self.assertEqual(row["work_model"], "on-site")
        self.assertEqual(row["city"], "São Paulo")
        self.assertEqual(row["state"], "SP")

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
