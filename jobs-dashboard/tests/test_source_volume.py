# -*- coding: utf-8 -*-
"""Detecção de queda silenciosa de volume por fonte."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

import pipeline  # noqa: E402
import storage  # noqa: E402


def _ts(day, hour=12):
    return f"2026-11-{day:02d}T{hour:02d}:00:00+00:00"


class SourceVolumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = storage.connect(os.path.join(self.tmp.name, "jobs.db"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _seed(self, source, values, start_day=8):
        for offset, jobs in enumerate(values):
            storage.record_source_volumes(
                self.conn, {source: jobs}, {source}, observed_at=_ts(start_day + offset)
            )

    def test_drop_below_half_of_median_is_flagged(self):
        self._seed("gupy", [100, 110, 90, 105])
        alerts = storage.source_volume_alerts(
            self.conn, {"gupy": 40}, {"gupy"}, observed_at=_ts(14)
        )
        self.assertEqual([a["source"] for a in alerts], ["gupy"])
        self.assertEqual(alerts[0]["baseline"], 102.5)
        self.assertEqual(alerts[0]["runs"], 4)

    def test_zero_jobs_from_healthy_source_is_flagged(self):
        self._seed("vagascom", [50, 60])
        alerts = storage.source_volume_alerts(
            self.conn, {}, {"vagascom"}, observed_at=_ts(14)
        )
        self.assertEqual(alerts[0]["jobs"], 0)

    def test_normal_variation_and_small_baselines_are_ignored(self):
        self._seed("gupy", [100, 100])
        self._seed("tiny", [4, 6])
        alerts = storage.source_volume_alerts(
            self.conn, {"gupy": 60, "tiny": 0}, {"gupy", "tiny"}, observed_at=_ts(14)
        )
        self.assertEqual(alerts, [])

    def test_samples_outside_window_or_without_history_are_ignored(self):
        self._seed("gupy", [100], start_day=1)  # 13 dias antes
        alerts = storage.source_volume_alerts(
            self.conn, {"gupy": 0, "nova": 0}, {"gupy", "nova"}, observed_at=_ts(14)
        )
        self.assertEqual(alerts, [])

    def test_old_samples_are_pruned(self):
        storage.record_source_volumes(self.conn, {"gupy": 10}, {"gupy"},
                                      observed_at="2026-10-01T00:00:00+00:00")
        storage.record_source_volumes(self.conn, {"gupy": 12}, {"gupy"},
                                      observed_at=_ts(14))
        rows = self.conn.execute("SELECT COUNT(*) FROM source_volume").fetchone()[0]
        self.assertEqual(rows, 1)


class ActionsSummaryVolumeTests(unittest.TestCase):
    def test_summary_lists_volume_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "summary.md")
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": path}):
                pipeline.write_actions_summary(
                    [], {"total": 1.0}, 10, [],
                    [{"source": "gupy", "jobs": 40, "baseline": 102.5, "runs": 4}],
                )
            text = Path(path).read_text(encoding="utf-8")
        self.assertIn("Fontes com queda de volume:** gupy", text)
        self.assertIn("| gupy | 40 | 102.5 | 4 |", text)

    def test_summary_without_alerts_says_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "summary.md")
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": path}):
                pipeline.write_actions_summary([], {"total": 1.0}, 10, [])
            text = Path(path).read_text(encoding="utf-8")
        self.assertIn("Fontes com queda de volume:** nenhuma", text)


if __name__ == "__main__":
    unittest.main()
