# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import linkedin  # noqa: E402


class LinkedInSourceTests(unittest.TestCase):
    def _write_snapshot(self, payload):
        temporary = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        )
        try:
            json.dump(payload, temporary, ensure_ascii=False)
            return Path(temporary.name)
        finally:
            temporary.close()

    def _payload(self, **overrides):
        today = date.today().isoformat()
        row = {
            "source": "linkedin",
            "sourceLabel": "LinkedIn",
            "native_id": "li-123",
            "title": "Analista de Suporte",
            "company": "Empresa Teste",
            "url": "https://www.linkedin.com/jobs/view/123",
            "location": "São Paulo, São Paulo, Brazil",
            "workplaceType": "remote",
            "publishedAt": today,
            "easyApply": True,
            "salaryMin": 3000,
            "salaryMax": 4500,
            "currency": "BRL",
        }
        row.update(overrides.pop("job", {}))
        payload = {
            "schema_version": 1,
            "source": "linkedin",
            "filter": "easy_apply",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "jobs": [row],
        }
        payload.update(overrides)
        return payload

    def test_fetch_normalizes_valid_public_easy_apply_snapshot(self):
        path = self._write_snapshot(self._payload())
        try:
            with patch.dict(
                os.environ,
                {
                    "LINKEDIN_SNAPSHOT_PATH": str(path),
                    "LINKEDIN_MAX_AGE_DAYS": "30",
                },
                clear=False,
            ):
                rows = linkedin.fetch()
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "linkedin")
        self.assertEqual(rows[0]["native_id"], "li-123")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["work_model"], "remote")
        self.assertEqual(rows[0]["description"], "")
        self.assertEqual(rows[0]["salary_min"], 3000.0)

    def test_fetch_rejects_non_easy_apply_snapshot(self):
        path = self._write_snapshot(self._payload(filter="all"))
        try:
            with patch.dict(
                os.environ, {"LINKEDIN_SNAPSHOT_PATH": str(path)}, clear=False
            ):
                with self.assertRaisesRegex(RuntimeError, "Easy Apply"):
                    linkedin.fetch()
        finally:
            path.unlink(missing_ok=True)

    def test_normalize_excludes_non_brazil_and_old_jobs(self):
        today = date.today()
        self.assertIsNone(
            linkedin._normalize(
                self._payload()["jobs"][0]
                | {"location": "United States", "publishedAt": today.isoformat()},
                today=today,
            )
        )
        self.assertIsNone(
            linkedin._normalize(
                self._payload()["jobs"][0]
                | {
                    "publishedAt": (today - timedelta(days=31)).isoformat()
                },
                today=today,
            )
        )

    def test_fetch_rejects_stale_snapshot(self):
        path = self._write_snapshot(
            self._payload(
                generated_at=(
                    datetime.now(timezone.utc) - timedelta(hours=37)
                ).isoformat()
            )
        )
        try:
            with patch.dict(
                os.environ,
                {
                    "LINKEDIN_SNAPSHOT_PATH": str(path),
                    "LINKEDIN_SNAPSHOT_MAX_AGE_HOURS": "36",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    linkedin.fetch()
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
