# -*- coding: utf-8 -*-
"""Orçamento de tempo e publicação resistente da coleta LinkedIn (sem rede)."""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
REPO_ROOT = DASHBOARD.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import collect_linkedin  # noqa: E402

WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "linkedin-jobs.yml").read_text(encoding="utf-8")


class TimeBudgetTests(unittest.TestCase):
    def tearDown(self):
        collect_linkedin._DEADLINE = None

    def test_expired_budget_stops_before_requesting_pages(self):
        collect_linkedin._DEADLINE = time.monotonic() - 1
        coverage = {}
        with patch.object(collect_linkedin, "scrape_jobs") as scrape:
            rows = collect_linkedin._scrape_jobs_in_pages(results_limit=200, coverage=coverage)
        scrape.assert_not_called()
        self.assertEqual(rows, [])
        self.assertTrue(coverage["stopped_by_time_budget"])
        self.assertFalse(coverage["limit_reached"])

    def test_no_deadline_means_no_limit(self):
        collect_linkedin._DEADLINE = None
        self.assertFalse(collect_linkedin._time_budget_exhausted())

    def test_budget_comes_from_environment(self):
        with patch.dict(os.environ, {collect_linkedin.TIME_BUDGET_ENV: "10"}):
            self.assertEqual(collect_linkedin._time_budget_minutes(), 10.0)
        with patch.dict(os.environ, {collect_linkedin.TIME_BUDGET_ENV: "0"}):
            self.assertIsNone(collect_linkedin._time_budget_minutes())
        with patch.dict(os.environ, {collect_linkedin.TIME_BUDGET_ENV: "x"}):
            self.assertEqual(collect_linkedin._time_budget_minutes(),
                             collect_linkedin.DEFAULT_TIME_BUDGET_MINUTES)


class WorkflowTests(unittest.TestCase):
    def test_collection_sets_a_budget_below_the_job_timeout(self):
        self.assertIn('LINKEDIN_TIME_BUDGET_MINUTES: "32"', WORKFLOW)
        self.assertIn("timeout-minutes: 45", WORKFLOW)

    def test_publish_rebases_and_retries(self):
        self.assertIn("git pull --rebase --no-edit origin main", WORKFLOW)
        self.assertIn("git push origin HEAD:main", WORKFLOW)
        self.assertNotIn("            git push origin main\n", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
