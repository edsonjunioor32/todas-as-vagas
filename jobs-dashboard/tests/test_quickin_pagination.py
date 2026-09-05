# -*- coding: utf-8 -*-
"""Regression tests for complete Quickin catalogue collection."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import quickin  # noqa: E402


class QuickinPaginationTests(unittest.TestCase):
    @staticmethod
    def _listing(count, board="infovagas"):
        return "\n".join(
            f'<a href="/{board}/jobs/{index:024x}">Vaga {index}</a>'
            for index in range(1, count + 1)
        )

    @staticmethod
    def _rendered(count, board="infovagas"):
        return [
            (
                f"https://jobs.quickin.io/{board}/jobs/{index:024x}",
                f"Vaga {index}",
            )
            for index in range(1, count + 1)
        ]

    @staticmethod
    def _fake_detail(url, label, source, detail_re, company_override):
        match = detail_re.search(url)
        return {"native_id": match.group(1), "title": label, "url": url}

    def test_full_first_page_requires_rendered_pagination_and_merges_all_jobs(self):
        first_page = self._listing(quickin.QUICKIN_PAGE_SIZE)
        rendered = self._rendered(27)
        with (
            patch.object(quickin, "get_text", return_value=first_page),
            patch.object(
                quickin,
                "rendered_paginated_links",
                return_value=rendered,
            ) as browser,
            patch.object(quickin, "_fetch_detail", side_effect=self._fake_detail),
        ):
            rows = quickin._fetch_board("infovagas", "infovagas")

        self.assertEqual(len(rows), 27)
        browser.assert_called_once()

    def test_partial_first_page_does_not_launch_browser(self):
        first_page = self._listing(6, board="meutudo")
        with (
            patch.object(quickin, "get_text", return_value=first_page),
            patch.object(quickin, "rendered_paginated_links") as browser,
            patch.object(quickin, "_fetch_detail", side_effect=self._fake_detail),
        ):
            rows = quickin._fetch_board("meutudo", "meutudo")

        self.assertEqual(len(rows), 6)
        browser.assert_not_called()

    def test_browser_failure_is_not_silently_accepted_as_ten_jobs(self):
        first_page = self._listing(quickin.QUICKIN_PAGE_SIZE)
        with (
            patch.object(quickin, "get_text", return_value=first_page),
            patch.object(
                quickin,
                "rendered_paginated_links",
                side_effect=RuntimeError("pagination verification failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "pagination verification failed"):
                quickin._fetch_board("infovagas", "infovagas")


if __name__ == "__main__":
    unittest.main()
