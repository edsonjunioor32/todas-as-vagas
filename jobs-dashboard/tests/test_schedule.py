import json
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "jobs-dashboard"))

from catalog_catchup import decide, dispatch_collection, latest_slot


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
        self.assertIn("vagas-main-writer", workflow)
        self.assertIn("CATCHUP_GRACE_MINUTES", workflow)
        self.assertIn("catalog_catchup.py", workflow)

    def test_dispatch_collection_calls_pages_dispatch_api(self):
        with patch("catalog_catchup.urllib.request.urlopen") as urlopen:
            dispatch_collection("edsonjunioor32/todas-as-vagas", "token")

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.github.com/repos/edsonjunioor32/todas-as-vagas/actions/workflows/pages.yml/dispatches",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"ref": "main"})
        self.assertEqual(request.get_header("Authorization"), "Bearer token")

    def test_collection_does_not_cancel_an_in_progress_run(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("  cancel-in-progress: false", workflow)

    def test_guard_waits_for_grace_and_never_duplicates_active_or_dispatched_runs(self):
        utc = timezone.utc
        slot = datetime(2026, 9, 11, 11, 0, tzinfo=utc)
        self.assertEqual(
            latest_slot(datetime(2026, 9, 11, 11, 20, tzinfo=utc)),
            slot,
        )
        self.assertEqual(
            decide(datetime(2026, 9, 11, 11, 20, tzinfo=utc), [])["action"],
            "grace",
        )
        active = {
            "event": "schedule",
            "status": "in_progress",
            "created_at": "2026-09-11T11:05:00Z",
        }
        self.assertEqual(
            decide(datetime(2026, 9, 11, 11, 45, tzinfo=utc), [active])["action"],
            "skip",
        )
        dispatched = {
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-09-11T11:31:00Z",
        }
        self.assertEqual(
            decide(datetime(2026, 9, 11, 11, 45, tzinfo=utc), [dispatched])["action"],
            "skip",
        )

    def test_guard_dispatches_when_the_slot_has_no_collection_run(self):
        utc = timezone.utc
        result = decide(datetime(2026, 9, 11, 11, 45, tzinfo=utc), [])
        self.assertEqual(result["action"], "dispatch")
        self.assertEqual(result["reason"], "slot_missing")

    def test_guard_accepts_a_successful_collection_run(self):
        utc = timezone.utc
        successful = {
            "event": "schedule",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-09-11T11:01:00Z",
        }
        self.assertEqual(
            decide(datetime(2026, 9, 11, 11, 45, tzinfo=utc), [successful])["action"],
            "skip",
        )


if __name__ == "__main__":
    unittest.main()
