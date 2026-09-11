import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def cron_entries(path: str) -> list[str]:
    workflow = (ROOT / path).read_text(encoding="utf-8")
    return re.findall(r'^\s*- cron: "([^"]+)"$', workflow, re.MULTILINE)


class ScheduleTests(unittest.TestCase):
    def test_daily_collection_runs_at_brasilia_hours(self):
        self.assertIn(
            "0 11,14,18,23 * * *",
            cron_entries(".github/workflows/pages.yml"),
        )

    def test_catalog_catchup_guard_is_scheduled_and_can_dispatch(self):
        workflow = (ROOT / ".github/workflows/catalog-catchup.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('    - cron: "*/15 * * * *"', workflow)
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertIn("  actions: write", workflow)
        self.assertIn("actions/workflows/pages.yml/dispatches", workflow)
        self.assertIn("vagas-main-writer", workflow)
        self.assertIn("CATCHUP_GRACE_MINUTES", workflow)


if __name__ == "__main__":
    unittest.main()
