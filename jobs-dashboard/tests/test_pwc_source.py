# -*- coding: utf-8 -*-
"""Tests for PwC's public Brazilian experienced-careers feed."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import pwc  # noqa: E402
import pipeline  # noqa: E402


def listing(records):
    return (
        "<html><script>var jsondata = "
        + json.dumps(records, ensure_ascii=False)
        + " ;\nwindow.bootstrap = {};</script></html>"
    )


class PwCSourceTests(unittest.TestCase):
    def test_collects_full_embedded_feed_with_brazil_filter_and_unique_ids(self):
        first = {
            "jobreqid": "146878WD",
            "title": "Banco de Talentos – Assurance",
            "location": "São Paulo",
            "los": "Assurance",
            "specialism": "Auditoria",
            "grade": "Associate",
            "apply": (
                "https://pwc.wd3.myworkdayjobs.com/"
                "Global_Experienced_Careers/job/So-Paulo/Assurance_146878WD/apply"
            ),
            "jobsite": "Global_Experienced_Careers",
            "iso": "BRA",
        }
        second = {
            **first,
            "jobreqid": "747541WD",
            "title": "Analista de Dados Remoto",
            "location": "Remote",
            "apply": "",
        }
        foreign = {**first, "jobreqid": "OTHER", "iso": "USA"}
        wrong_site = {**first, "jobreqid": "STUDENT", "jobsite": "Global_Students"}
        with patch.object(
            pwc, "get_text",
            return_value=listing([first, second, first, foreign, wrong_site]),
        ) as request:
            rows = pwc.fetch()

        request.assert_called_once_with(pwc.LISTING, timeout=45, retries=3)
        self.assertEqual([row["native_id"] for row in rows], ["146878WD", "747541WD"])
        self.assertEqual(rows[0]["source"], "pwc")
        self.assertEqual(rows[0]["company"], "PwC")
        self.assertEqual(rows[0]["city"], "São Paulo")
        self.assertEqual(rows[0]["country"], "BR")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["levels"], ["Associate"])
        self.assertEqual(rows[0]["categories"], ["Assurance", "Auditoria"])
        self.assertEqual(
            rows[0]["url"],
            "https://pwc.wd3.myworkdayjobs.com/"
            "Global_Experienced_Careers/job/So-Paulo/Assurance_146878WD",
        )
        self.assertEqual(rows[1]["work_model"], "remote")
        self.assertEqual(rows[1]["city"], "Brasil")
        self.assertIn("wdjobreqid=747541WD", rows[1]["url"])

    def test_missing_or_invalid_feed_fails_instead_of_silently_clearing_source(self):
        for markup in (
            "<html>No results markup</html>",
            "<script>var jsondata = {}</script>",
            "<script>var jsondata = [broken]</script>",
            listing([]),
        ):
            with self.subTest(markup=markup):
                with patch.object(pwc, "get_text", return_value=markup):
                    with self.assertRaises(RuntimeError):
                        pwc.fetch()

    def test_source_is_in_regular_and_explicit_collection(self):
        self.assertIn("pwc", [name for name, _ in pipeline.selected_registry("")])
        self.assertEqual(
            [name for name, _ in pipeline.selected_registry("pwc")],
            ["pwc"],
        )
