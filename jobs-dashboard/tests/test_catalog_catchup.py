import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, "jobs-dashboard")

import catalog_catchup


UTC = timezone.utc


class CatalogCatchupTests(unittest.TestCase):
    def test_daily_schedule_uses_minute_seven(self):
        now = datetime(2026, 9, 24, 11, 6, tzinfo=UTC)
        self.assertEqual(
            catalog_catchup.latest_slot(now),
            datetime(2026, 9, 23, 23, 7, tzinfo=UTC),
        )
        now = datetime(2026, 9, 24, 11, 7, tzinfo=UTC)
        self.assertEqual(catalog_catchup.latest_slot(now), now)

    def test_weekly_sunday_slot_is_recognized(self):
        now = datetime(2026, 9, 27, 8, 10, tzinfo=UTC)
        self.assertEqual(
            catalog_catchup.latest_slot(now),
            datetime(2026, 9, 27, 7, 47, tzinfo=UTC),
        )

    def test_waits_for_grace_period(self):
        now = datetime(2026, 9, 24, 11, 20, tzinfo=UTC)
        result = catalog_catchup.decide(now, [])
        self.assertEqual(result["action"], "grace")
        self.assertEqual(result["reason"], "within_grace")

    def test_skips_when_slot_succeeded(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
        runs = [{
            "id": 123,
            "event": "schedule",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-09-24T11:08:00Z",
        }]
        result = catalog_catchup.decide(now, runs)
        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "slot_succeeded")

    def test_does_not_treat_previous_slot_success_as_current_success(self):
        now = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)
        runs = [{
            "id": 123,
            "event": "schedule",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-09-24T14:05:00Z",
        }]
        result = catalog_catchup.decide(now, runs)
        self.assertEqual(result["action"], "dispatch")
        self.assertEqual(result["reason"], "slot_missing")

    def test_active_collection_is_not_duplicated(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
        runs = [{
            "id": 456,
            "event": "workflow_dispatch",
            "status": "in_progress",
            "created_at": "2026-09-24T11:08:00Z",
        }]
        result = catalog_catchup.decide(now, runs)
        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "collection_active")

    def test_fresh_queued_collection_is_not_duplicated(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
        runs = [{
            "id": 460,
            "event": "schedule",
            "status": "queued",
            "created_at": "2026-09-24T11:50:00Z",
        }]
        result = catalog_catchup.decide(now, runs, queue_grace_minutes=15)
        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "collection_queued")

    def test_stale_queued_collection_alerts_without_dispatch(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
        queued = {
            "id": 461,
            "event": "schedule",
            "status": "queued",
            "created_at": "2026-09-24T11:35:00Z",
            "html_url": "https://github.com/example/run/461",
        }
        result = catalog_catchup.decide(now, [queued], queue_grace_minutes=15)
        self.assertEqual(result["action"], "alert")
        self.assertEqual(result["reason"], "queued_too_long")
        self.assertIs(result["run"], queued)

    def test_waiting_run_is_treated_as_queued_and_never_redispatched(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
        waiting = {
            "id": 463,
            "event": "schedule",
            "status": "waiting",
            "created_at": "2026-09-24T11:35:00Z",
        }
        result = catalog_catchup.decide(now, [waiting], queue_grace_minutes=15)
        self.assertEqual(result["action"], "alert")
        self.assertEqual(result["reason"], "queued_too_long")

    def test_stuck_active_collection_alerts_without_dispatch(self):
        now = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
        running = {
            "id": 462,
            "event": "workflow_dispatch",
            "status": "in_progress",
            "created_at": "2026-09-24T11:08:00Z",
        }
        result = catalog_catchup.decide(now, [running], max_active_minutes=120)
        self.assertEqual(result["action"], "alert")
        self.assertEqual(result["reason"], "run_too_long")

    def test_failed_or_missing_slot_dispatches_once_a_writer_is_free(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
        failed = {
            "id": 789,
            "event": "schedule",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-09-24T11:08:00Z",
        }
        result = catalog_catchup.decide(now, [failed])
        self.assertEqual(result["action"], "dispatch")
        self.assertEqual(result["reason"], "slot_failed")
        self.assertEqual(catalog_catchup.resume_key_for_slot([failed], result["slot"]), "run-789")

    def test_recent_catchup_dispatch_respects_cooldown(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
        run = {
            "id": 790,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-09-24T11:55:00Z",
        }
        result = catalog_catchup.decide(now, [run], dispatch_cooldown_minutes=10)
        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "dispatch_cooldown")

    def test_upsert_updates_existing_incident_instead_of_creating_duplicate(self):
        existing = {"number": 17, "body": catalog_catchup.INCIDENT_MARKER}
        with (
            patch.object(catalog_catchup, "_ensure_incident_label"),
            patch.object(catalog_catchup, "_open_incidents", return_value=[existing]),
            patch.object(catalog_catchup, "_api_json", return_value={"html_url": "issue-url"}) as api,
        ):
            result = catalog_catchup.upsert_delay_issue(
                "owner/repo", "token", datetime(2026, 9, 24, 11, 7, tzinfo=UTC),
                "queued_too_long",
            )
        self.assertEqual(result["html_url"], "issue-url")
        self.assertEqual(api.call_args.args[0:2], ("PATCH", "/repos/owner/repo/issues/17"))

    def test_upsert_creates_one_incident_when_none_is_open(self):
        with (
            patch.object(catalog_catchup, "_ensure_incident_label"),
            patch.object(catalog_catchup, "_open_incidents", return_value=[]),
            patch.object(catalog_catchup, "_api_json", return_value={"number": 18}) as api,
        ):
            result = catalog_catchup.upsert_delay_issue(
                "owner/repo", "token", datetime(2026, 9, 24, 11, 7, tzinfo=UTC),
                "slot_missing",
            )
        self.assertEqual(result["number"], 18)
        self.assertEqual(api.call_args.args[0:2], ("POST", "/repos/owner/repo/issues"))

    def test_alert_path_records_incident_without_dispatch(self):
        slot = datetime(2026, 9, 24, 11, 7, tzinfo=UTC)
        result = {
            "action": "alert",
            "reason": "queued_too_long",
            "slot": slot,
            "run": {"id": 463},
        }
        with (
            patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "token"}),
            patch.object(catalog_catchup, "fetch_collection_runs", return_value=[]),
            patch.object(catalog_catchup, "decide", return_value=result),
            patch.object(catalog_catchup, "upsert_delay_issue", return_value={"html_url": "issue-url"}),
            patch.object(catalog_catchup, "dispatch_collection") as dispatch,
        ):
            catalog_catchup.main()
        dispatch.assert_not_called()

    def test_success_closes_each_open_incident(self):
        with (
            patch.object(catalog_catchup, "_open_incidents", return_value=[{"number": 17}, {"number": 18}]),
            patch.object(catalog_catchup, "_api_json", return_value={}) as api,
        ):
            closed = catalog_catchup.close_delay_issues("owner/repo", "token")
        self.assertEqual(closed, 2)
        self.assertEqual(api.call_count, 2)


if __name__ == "__main__":
    unittest.main()
