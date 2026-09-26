import sys
import unittest
from unittest.mock import patch
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

    def test_failed_automatic_recovery_is_alerted_without_a_dispatch_loop(self):
        now = datetime(2026, 9, 24, 11, 45, tzinfo=timezone.utc)
        runs = [
            {
                "id": 789,
                "event": "schedule",
                "status": "completed",
                "conclusion": "failure",
                "created_at": "2026-09-24T11:07:00Z",
            },
            {
                "id": 790,
                "event": "repository_dispatch",
                "status": "completed",
                "conclusion": "failure",
                "created_at": "2026-09-24T11:35:00Z",
            },
        ]

        result = catalog_catchup.decide(now, runs)

        self.assertEqual(result["action"], "alert")
        self.assertEqual(result["reason"], "recovery_attempt_failed")

    def test_automatic_recovery_event_counts_as_a_catalog_run(self):
        self.assertTrue(catalog_catchup.is_collection_run({
            "event": "repository_dispatch",
            "action": "catalog_recovery",
        }))


    def test_alerts_when_a_collection_is_queued_too_long_without_duplicating_it(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        runs = [{
            "id": 456,
            "event": "schedule",
            "status": "queued",
            "created_at": "2026-09-24T11:05:00Z",
            "html_url": "https://github.com/example/repo/actions/runs/456",
        }]
        result = catalog_catchup.decide(now, runs)
        self.assertEqual(result["action"], "alert")
        self.assertEqual(result["reason"], "run_queued_too_long")

    def test_short_queue_wait_does_not_create_an_alert(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        runs = [{
            "event": "schedule",
            "status": "queued",
            "created_at": "2026-09-24T11:45:00Z",
        }]
        result = catalog_catchup.decide(now, runs)
        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "collection_active")

    def test_delay_issue_is_created_once_then_updated(self):
        slot = datetime(2026, 9, 24, 11, 0, tzinfo=timezone.utc)
        issue = {"number": 17, "title": catalog_catchup.DELAY_ISSUE_TITLE}
        calls = []

        def fake_api(repository, token, path, method="GET", payload=None):
            calls.append((path, method, payload))
            if method == "GET":
                return [] if len([call for call in calls if call[1] == "GET"]) == 1 else [issue]
            return issue

        with patch.object(catalog_catchup, "_api_json", side_effect=fake_api):
            catalog_catchup.upsert_delay_issue("owner/repo", "token", slot, "recovery_dispatched", [])
            catalog_catchup.upsert_delay_issue("owner/repo", "token", slot, "run_queued_too_long", [])

        self.assertEqual([call[1] for call in calls], ["GET", "POST", "GET", "PATCH"])
        self.assertEqual(calls[1][0], "issues")
        self.assertEqual(calls[3][0], "issues/17")


    def test_delayed_success_counts_for_the_slot_it_actually_started_in(self):
        now = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
        slot = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)
        runs = [{
            "id": 123,
            "event": "schedule",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-09-24T11:07:00Z",
            "run_started_at": "2026-09-24T14:40:00Z",
        }]
        result = catalog_catchup.decide(now, runs)
        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "slot_succeeded")
        self.assertEqual(catalog_catchup.resume_key_for_slot(runs, slot), "run-123")

    def test_overdue_queue_alert_links_the_queued_run_even_if_older_than_slot(self):
        slot = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)
        url = "https://github.com/example/repo/actions/runs/456"
        body = catalog_catchup._incident_body(slot, "run_queued_too_long", [{
            "id": 456,
            "event": "schedule",
            "status": "queued",
            "created_at": "2026-09-24T11:07:00Z",
            "html_url": url,
        }])
        self.assertIn(url, body)



if __name__ == "__main__":
    unittest.main()
