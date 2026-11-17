# -*- coding: utf-8 -*-
"""Coleta incremental do LinkedIn: junção com o snapshot anterior (sem rede)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools import collect_linkedin  # noqa: E402

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "linkedin-jobs.yml").read_text(encoding="utf-8")


def job(native_id, published, title="Vaga"):
    return {"native_id": native_id, "url": f"https://www.linkedin.com/jobs/view/{native_id}",
            "title": title, "publishedAt": published}


class MergePreviousSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "linkedin_vagas.json")
        previous = [
            job("1", "2026-11-10T00:00:00Z", "antiga versão"),
            job("2", "2026-11-05T00:00:00Z"),
            job("3", "2026-09-01T00:00:00Z"),
            job("4", ""),
        ]
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"jobs": previous}, handle)

    def tearDown(self):
        self.tmp.cleanup()

    def test_keeps_recent_previous_jobs_and_prefers_new_versions(self):
        new = [job("1", "2026-11-10T00:00:00Z", "versão nova"), job("9", "2026-11-17T00:00:00Z")]
        merged, kept = collect_linkedin.merge_previous_snapshot(new, self.path, 30, now=NOW)
        self.assertEqual(kept, 1)
        self.assertEqual([j["native_id"] for j in merged], ["1", "9", "2"])
        self.assertEqual(merged[0]["title"], "versão nova")

    def test_disabled_or_missing_snapshot_returns_new_jobs_only(self):
        new = [job("9", "2026-11-17T00:00:00Z")]
        self.assertEqual(collect_linkedin.merge_previous_snapshot(new, self.path, 0, now=NOW), (new, 0))
        missing = os.path.join(self.tmp.name, "nao-existe.json")
        self.assertEqual(collect_linkedin.merge_previous_snapshot(new, missing, 30, now=NOW), (new, 0))

    def test_invalid_previous_file_is_ignored(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{quebrado")
        new = [job("9", "2026-11-17T00:00:00Z")]
        self.assertEqual(collect_linkedin.merge_previous_snapshot(new, self.path, 30, now=NOW), (new, 0))


class WorkflowModeTests(unittest.TestCase):
    def test_scheduled_runs_are_incremental_with_weekly_full_sweep(self):
        self.assertIn('--merge-previous-days "$MERGE_DAYS"', WORKFLOW)
        self.assertIn("HOURS=48", WORKFLOW)
        self.assertIn("MERGE_DAYS=30", WORKFLOW)
        self.assertIn('[ "$(date -u +%u)" = "7" ]', WORKFLOW)


if __name__ == "__main__":
    unittest.main()
