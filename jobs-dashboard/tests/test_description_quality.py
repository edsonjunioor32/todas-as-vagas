import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from description_quality import assess_row


class DescriptionQualityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 11, 21, 0, tzinfo=timezone.utc)

    def row(self, **overrides):
        row = {
            "description": "",
            "status": "pending",
            "checked_at": "",
            "content_kind": "",
        }
        row.update(overrides)
        return row

    def test_empty_description_is_empty_not_complete(self):
        result = assess_row(self.row(status="no_description"), now=self.now)
        self.assertEqual(result.level, "empty")
        self.assertEqual(result.character_count, 0)

    def test_not_attempted_job_is_pending(self):
        result = assess_row(self.row(status="pending"), now=self.now)
        self.assertEqual(result.level, "pending")

    def test_blocked_job_preserves_blocking_reason(self):
        result = assess_row(
            self.row(status="http_403", error="access denied"),
            now=self.now,
        )
        self.assertEqual(result.level, "blocked")
        self.assertEqual(result.reason, "http_403")

    def test_short_text_is_not_usable(self):
        result = assess_row(
            self.row(status="fetched", description="x" * 199),
            now=self.now,
        )
        self.assertEqual(result.level, "short")

    def test_two_hundred_characters_are_usable(self):
        result = assess_row(
            self.row(status="fetched", description="x" * 200),
            now=self.now,
        )
        self.assertEqual(result.level, "usable")

    def test_old_fetched_text_is_stale(self):
        result = assess_row(
            self.row(
                status="fetched",
                description="Descrição antiga " + "x" * 300,
                checked_at="2026-10-01T21:00:00+00:00",
            ),
            now=self.now,
            stale_after_days=30,
        )
        self.assertEqual(result.level, "stale")

    def test_long_text_with_sections_is_complete_candidate(self):
        description = (
            "Responsabilidades\n"
            + ("Apoiar a operação e documentar ocorrências. " * 15)
            + "\nRequisitos\n"
            + ("Experiência com atendimento, análise e melhoria contínua. " * 15)
        )
        result = assess_row(
            self.row(status="fetched", description=description),
            now=self.now,
        )
        self.assertEqual(result.level, "complete_candidate")
        self.assertGreaterEqual(result.section_count, 2)

    def test_long_text_without_sections_remains_usable(self):
        result = assess_row(
            self.row(status="fetched", description="x" * 1500),
            now=self.now,
        )
        self.assertEqual(result.level, "usable")


if __name__ == "__main__":
    unittest.main()
