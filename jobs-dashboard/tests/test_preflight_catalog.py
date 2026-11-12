import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "jobs-dashboard")

import preflight_catalog


class CatalogPreflightTests(unittest.TestCase):
    REFERENCE = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)

    def snapshot(self, generated_at: str, count: int = 2) -> dict:
        columns = {
            name: [f"{name}-{index}" for index in range(count)]
            for name in preflight_catalog.REQUIRED_COLUMNS
        }
        columns["url"] = [
            f"https://example.test/jobs/{index}" for index in range(count)
        ]
        return {
            "count": count,
            "generated_at": generated_at,
            "generated_date": "2026-10-20",
            "max_age_months": 2,
            "publication_cutoff": "2026-08-20",
            "jobs": columns,
            "dict": {
                name: {"0": "valor"}
                for name in preflight_catalog.REQUIRED_DICTIONARIES
            },
        }

    def write(self, directory: Path, name: str, data: dict) -> Path:
        path = directory / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_before_collection_accepts_valid_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "previous.json",
                self.snapshot("2026-10-20T12:00:00+00:00"),
            )
            message = preflight_catalog.check_before_collection(
                path,
                minimum_count=1,
                expected_max_age_months=2,
                now=self.REFERENCE,
            )
        self.assertIn("fotografia anterior íntegra", message)

    def test_before_collection_rejects_private_root_field(self):
        with tempfile.TemporaryDirectory() as directory:
            data = self.snapshot("2026-10-20T12:00:00+00:00")
            data["description"] = "conteúdo privado"
            path = self.write(Path(directory), "previous.json", data)
            with self.assertRaisesRegex(
                preflight_catalog.PreflightError, "campos privados"
            ):
                preflight_catalog.check_before_collection(
                    path,
                    minimum_count=1,
                    expected_max_age_months=2,
                    now=self.REFERENCE,
                )

    def test_after_collection_requires_new_generated_at(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = self.write(
                Path(directory),
                "previous.json",
                self.snapshot("2026-10-20T12:00:00+00:00"),
            )
            current = self.write(
                Path(directory),
                "current.json",
                self.snapshot("2026-10-20T12:00:00+00:00"),
            )
            with self.assertRaisesRegex(
                preflight_catalog.PreflightError, "não foi renovado"
            ):
                preflight_catalog.check_after_collection(
                    current,
                    previous,
                    minimum_count=1,
                    expected_max_age_months=2,
                    minimum_ratio=0.5,
                    now=self.REFERENCE,
                )

    def test_after_collection_accepts_new_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = self.write(
                Path(directory),
                "previous.json",
                self.snapshot("2026-10-20T12:00:00+00:00"),
            )
            current = self.write(
                Path(directory),
                "current.json",
                self.snapshot("2026-10-20T14:00:00+00:00"),
            )
            message = preflight_catalog.check_after_collection(
                current,
                previous,
                minimum_count=1,
                expected_max_age_months=2,
                minimum_ratio=0.5,
                now=self.REFERENCE,
            )
        self.assertIn("novo snapshot aprovado", message)

    def test_after_collection_rejects_unsafe_drop_for_large_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_data = self.snapshot("2026-10-20T12:00:00+00:00", count=10000)
            current_data = self.snapshot("2026-10-20T14:00:00+00:00", count=4999)
            previous = self.write(Path(directory), "previous.json", previous_data)
            current = self.write(Path(directory), "current.json", current_data)
            with self.assertRaisesRegex(
                preflight_catalog.PreflightError, "redução insegura"
            ):
                preflight_catalog.check_after_collection(
                    current,
                    previous,
                    minimum_count=1,
                    expected_max_age_months=2,
                    minimum_ratio=0.5,
                    now=self.REFERENCE,
                )

    def test_rejects_future_generated_at(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "snapshot.json",
                self.snapshot("2026-10-20T15:11:00+00:00"),
            )
            with self.assertRaisesRegex(
                preflight_catalog.PreflightError, "no futuro"
            ):
                preflight_catalog.check_before_collection(
                    path,
                    minimum_count=1,
                    expected_max_age_months=2,
                    now=self.REFERENCE,
                )


if __name__ == "__main__":
    unittest.main()
