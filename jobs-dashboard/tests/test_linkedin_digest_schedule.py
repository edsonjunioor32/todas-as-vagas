# -*- coding: utf-8 -*-
"""Travas de agenda do digest diário do LinkedIn (sem rede)."""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
sys.path.insert(0, str(TOOLS))

import publish_linkedin_daily as daily  # noqa: E402


class _NetworkCalled(Exception):
    pass


def _fixed_now(year, month, day, hour, minute):
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(year, month, day, hour, minute, tzinfo=tz)

    return _FixedDateTime


class DailyDigestWeekdayGuardTests(unittest.TestCase):
    def _run(self, now_cls, **kwargs):
        with patch.object(daily, "datetime", now_cls), \
             patch.object(daily, "is_already_posted_today", return_value=False), \
             patch.object(daily.urllib.request, "urlopen", side_effect=_NetworkCalled):
            return daily.publish_daily(dry_run=True, **kwargs)

    def test_saturday_inside_window_exits_without_network(self):
        # 14/11/2026 é sábado; 19h00 BRT está dentro da janela de horário.
        self.assertEqual(self._run(_fixed_now(2026, 11, 14, 19, 0)), 0)

    def test_sunday_inside_window_exits_without_network(self):
        self.assertEqual(self._run(_fixed_now(2026, 11, 15, 19, 0)), 0)

    def test_weekday_inside_window_reaches_catalog(self):
        # 16/11/2026 é segunda-feira: segue para buscar o catálogo.
        with self.assertRaises(_NetworkCalled):
            self._run(_fixed_now(2026, 11, 16, 19, 0))

    def test_force_bypasses_weekend_guard(self):
        with self.assertRaises(_NetworkCalled):
            self._run(_fixed_now(2026, 11, 14, 19, 0), force=True)


class DigestTriggerFanOutTests(unittest.TestCase):
    """O recuperador encadeado não deve acionar os digests em duplicidade."""

    def test_digests_do_not_chain_on_catchup_workflow(self):
        for name in (
            "linkedin-daily-digest.yml",
            "linkedin-morning-desperta.yml",
            "linkedin-weekly-digest.yml",
        ):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            triggers = text.split("workflow_run:", 1)[1].split("workflow_dispatch:", 1)[0]
            with self.subTest(workflow=name):
                self.assertIn('"Atualizar vagas multiportal e publicar GitHub Pages"', triggers)
                self.assertNotIn("recuperar agenda perdida", triggers)


if __name__ == "__main__":
    unittest.main()
