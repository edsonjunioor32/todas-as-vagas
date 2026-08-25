# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

import notify_telegram  # noqa: E402


def row(key, *, remote=False, ti=False):
    return {
        "key": key,
        "title": key,
        "company": "Empresa",
        "source": "teste",
        "url": f"https://example.com/{key}",
        "work_model": "remote" if remote else "on-site",
        "city": "Brasil",
        "published": "2026-08-25",
        "remote": remote,
        "ti": ti,
    }


class TelegramNotificationTests(unittest.TestCase):
    def test_unnotified_rows_prioritize_remote_ti(self):
        rows = [row("other"), row("remote", remote=True), row("remote-ti", remote=True, ti=True)]
        with patch.object(notify_telegram, "_rows", return_value=rows):
            ordered = notify_telegram._unnotified_rows(object(), {"other"})
        self.assertEqual([item["key"] for item in ordered], ["remote-ti", "remote"])

    def test_state_round_trip(self):
        snapshot = {"generated_at": "2026-08-25T12:00:00+00:00"}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            notify_telegram._write_state(path, {"a", "b"}, snapshot)
            self.assertEqual(notify_telegram._load_state(path), {"a", "b"})
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["snapshot_generated_at"], snapshot["generated_at"])

    def test_message_contains_portal_link(self):
        message = notify_telegram._text([row("vaga")], 1, 1)
        self.assertIn(notify_telegram.PORTAL_URL, message)


if __name__ == "__main__":
    unittest.main()
