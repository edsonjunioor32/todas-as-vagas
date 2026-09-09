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

    def test_retained_state_keys_drop_rows_outside_current_snapshot(self):
        current_rows = [row("active-a"), row("active-b")]
        retained = notify_telegram._retained_state_keys(current_rows, {"active-a", "old"})
        self.assertEqual(retained, {"active-a"})
        self.assertEqual(notify_telegram._current_keys(current_rows), {"active-a", "active-b"})

    def test_message_contains_portal_link(self):
        message = notify_telegram._text([row("vaga")], 1, 1)
        self.assertIn(notify_telegram.PORTAL_URL, message)

    def test_message_uses_requested_fields_in_order(self):
        vacancy = row("vaga", ti=True)
        vacancy.update({
            "company": "Empresa & Filhos",
            "category": "TI e Desenvolvimento",
            "source_label": "Gupy",
            "pcd": True,
        })
        message = notify_telegram._text([vacancy], 1, 1)
        labels = ["Cargo:", "Portal:", "Empresa:", "PCD:", "Área de atuação:"]
        for label in labels:
            self.assertIn(label, message)
        positions = [message.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Portal:</b> Gupy", message)
        self.assertIn("PCD:</b> Sim", message)
        self.assertIn("Área de atuação:</b> TI e Desenvolvimento", message)

    def test_message_separates_vacancies_and_uses_requested_footer(self):
        message = notify_telegram._text([row("primeira"), row("segunda")], 1, 1)
        self.assertEqual(message.count("━━━━━━━━━━━━━━━━━━━━"), 1)
        self.assertIn(
            f'Não encontrou o que queria? <a href="{notify_telegram.PORTAL_URL}">Acesse o portal Todas as Vagas</a>',
            message,
        )
        self.assertNotIn("Modalidade:", message)
        self.assertNotIn("Mercado:", message)


if __name__ == "__main__":
    unittest.main()
