import json
import re
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "jobs-dashboard"))
sys.path.insert(0, str(ROOT / "ops"))

from catalog_catchup import decide as catalog_decide, dispatch_collection, latest_slot as catalog_latest_slot
from github_scheduler import (
    BRASILIA,
    decide,
    dispatch_collection as scheduler_dispatch_collection,
    fetch_runs,
    latest_slot,
    SchedulerLock,
    load_state,
    save_state,
)


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
            catalog_latest_slot(datetime(2026, 9, 11, 11, 20, tzinfo=utc)),
            slot,
        )
        self.assertEqual(
            catalog_decide(datetime(2026, 9, 11, 11, 20, tzinfo=utc), [])["action"],
            "grace",
        )
        active = {
            "event": "schedule",
            "status": "in_progress",
            "created_at": "2026-09-11T11:05:00Z",
        }
        self.assertEqual(
            catalog_decide(datetime(2026, 9, 11, 11, 45, tzinfo=utc), [active])["action"],
            "skip",
        )
        dispatched = {
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-09-11T11:31:00Z",
        }
        self.assertEqual(
            catalog_decide(datetime(2026, 9, 11, 11, 45, tzinfo=utc), [dispatched])["action"],
            "skip",
        )

    def test_guard_dispatches_when_the_slot_has_no_collection_run(self):
        utc = timezone.utc
        result = catalog_decide(datetime(2026, 9, 11, 11, 45, tzinfo=utc), [])
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
            catalog_decide(datetime(2026, 9, 11, 11, 45, tzinfo=utc), [successful])["action"],
            "skip",
        )

    def test_vps_scheduler_maps_latest_slot_to_explicit_brasilia_time(self):
        slot = latest_slot(datetime(2026, 9, 11, 14, 10, tzinfo=timezone.utc))
        self.assertEqual(slot, datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc))
        self.assertEqual(slot.astimezone(BRASILIA).strftime("%H:%M"), "11:00")

    def test_vps_scheduler_waits_then_dispatches_only_missing_slot(self):
        now = datetime(2026, 9, 11, 14, 45, tzinfo=timezone.utc)
        self.assertEqual(decide(now, [], {})["action"], "dispatch")
        self.assertEqual(
            decide(
                now,
                [],
                {"dispatched_slots": {"2026-09-11T14:00:00+00:00": "2026-09-11T14:45:00+00:00"}},
            )["action"],
            "skip",
        )

    def test_vps_scheduler_does_not_dispatch_over_active_or_successful_collection(self):
        now = datetime(2026, 9, 11, 14, 45, tzinfo=timezone.utc)
        active = {"event": "schedule", "status": "in_progress", "created_at": "2026-09-11T14:05:00Z"}
        successful = {
            "event": "schedule",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-09-11T14:02:00Z",
        }
        self.assertEqual(decide(now, [active], {})["reason"], "collection_active")
        self.assertEqual(decide(now, [successful], {})["reason"], "slot_succeeded")

    def test_vps_scheduler_retries_a_failed_dispatch_when_not_locally_confirmed(self):
        now = datetime(2026, 9, 11, 14, 45, tzinfo=timezone.utc)
        failed = {
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-09-11T14:31:00Z",
        }
        result = decide(now, [failed], {})
        self.assertEqual(result["action"], "dispatch")
        self.assertEqual(result["reason"], "slot_missing")

    def test_vps_scheduler_reads_runs_with_bearer_token(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None
            def read(self):
                return b'{"workflow_runs": [{"id": 1}]}'

        with patch("github_scheduler.urllib.request.urlopen", return_value=Response()) as urlopen:
            self.assertEqual(fetch_runs("edsonjunioor32/todas-as-vagas", "secret"), [{"id": 1}])
        request = urlopen.call_args.args[0]
        self.assertIn("actions/workflows/pages.yml/runs", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_vps_scheduler_dispatches_pages_workflow(self):
        with patch("github_scheduler.urllib.request.urlopen") as urlopen:
            scheduler_dispatch_collection("edsonjunioor32/todas-as-vagas", "secret")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"ref": "main"})
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_vps_scheduler_persists_state_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            expected = {"dispatched_slots": {"2026-09-11T14:00:00+00:00": "2026-09-11T14:31:00+00:00"}}
            save_state(path, expected)
            self.assertEqual(load_state(path), expected)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_vps_scheduler_lock_prevents_overlapping_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scheduler.lock"
            first = SchedulerLock(path)
            second = SchedulerLock(path)
            self.assertTrue(first.acquire())
            try:
                self.assertFalse(second.acquire())
            finally:
                first.release()


if __name__ == "__main__":
    unittest.main()
