import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, "jobs-dashboard")

import catalog_catchup


class CatalogCatchupTests(unittest.TestCase):
    def test_waits_for_grace_period(self):
        now = datetime(2026, 9, 24, 11, 10, tzinfo=timezone.utc)
        result = catalog_catchup.decide(now, [])
        self.assertEqual(result["action"], "grace")

    def test_skips_when_slot_succeeded(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        runs = [{
            "id": 123,
            "event": "schedule",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-09-24T11:05:00Z",
        }]
        result = catalog_catchup.decide(now, runs)
        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "slot_succeeded")

    def test_skips_when_collection_is_active(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        runs = [{
            "id": 456,
            "event": "workflow_dispatch",
            "status": "in_progress",
            "created_at": "2026-09-24T11:05:00Z",
        }]
        result = catalog_catchup.decide(now, runs)
        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "collection_active")

    def test_dispatches_only_after_missing_slot(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        runs = [{
            "id": 789,
            "event": "schedule",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-09-24T11:05:00Z",
        }]
        result = catalog_catchup.decide(
            now,
            runs,
            grace_minutes=30,
            dispatch_cooldown_minutes=10,
        )
        self.assertEqual(result["action"], "dispatch")
        self.assertEqual(result["reason"], "slot_missing")


if __name__ == "__main__":
    unittest.main()
