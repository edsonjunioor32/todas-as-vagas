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

    def test_daily_sync_follows_collection_by_thirty_minutes(self):
        self.assertIn(
            "30 11,14,18,23 * * *",
            cron_entries(".github/workflows/telegram-sync.yml"),
        )


if __name__ == "__main__":
    unittest.main()
