# -*- coding: utf-8 -*-
"""Regressão: o webhook do Make que publica no LinkedIn vem só da configuração.

O repositório é público; quem tiver a URL do webhook consegue publicar no
LinkedIn. Os publicadores exigem MAKE_LINKEDIN_WEBHOOK_URL (ou --webhook-url)
fora do --dry-run, e nenhum arquivo do repositório pode embutir a URL.

Nenhum teste acessa a rede: toda chamada a urllib.request.urlopen é substituída.
"""
import io
import os
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import publish_linkedin_daily as daily  # noqa: E402
import publish_linkedin_morning as morning  # noqa: E402
import publish_linkedin_weekly as weekly  # noqa: E402

ENV_VAR = "MAKE_LINKEDIN_WEBHOOK_URL"
FAKE_TOKEN = "token-de-teste-nao-real"
FAKE_WEBHOOK = f"https://webhook.example.invalid/{FAKE_TOKEN}"
CLI_TOKEN = "token-da-linha-de-comando"
CLI_WEBHOOK = f"https://webhook.example.invalid/{CLI_TOKEN}"

# Montado em partes para que este arquivo não contenha o próprio padrão procurado.
MAKE_HOOK_PATTERN = re.compile(
    "hook" + r"\.(?:[a-z0-9-]+\.)?(?:" + "make" + "|" + "integ" + "romat" + r")\.com",
    re.IGNORECASE,
)
SCANNED_SUFFIXES = {
    ".bat", ".cfg", ".css", ".env", ".html", ".ini", ".js", ".json", ".md", ".mjs",
    ".ps1", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml",
}
SKIPPED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

WORKFLOWS = (
    "linkedin-daily-digest.yml",
    "linkedin-morning-desperta.yml",
    "linkedin-weekly-digest.yml",
)

# (rótulo, módulo, publicador, seleção, composição, registro de estado)
PUBLISHERS = (
    ("diário", daily, "publish_daily", "select_daily_vacancies", "compose_daily_digest", "mark_posted_today"),
    ("matinal", morning, "publish_morning", "select_morning_vacancies", "compose_morning_digest", "mark_posted_this_morning"),
    ("semanal", weekly, "publish_weekly", "select_weekly_vacancies", "compose_weekly_digest", "mark_posted_this_week"),
)


def _repository_files():
    """Arquivos rastreados pelo Git; sem Git disponível, percorre a árvore inteira.

    Usar o índice do Git evita falsos positivos com cópias locais não rastreadas.
    """
    try:
        listed = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
    except (OSError, subprocess.CalledProcessError):
        return [
            path
            for path in REPO_ROOT.rglob("*")
            if not any(part in SKIPPED_DIRS for part in path.relative_to(REPO_ROOT).parts)
        ]
    return [REPO_ROOT / name for name in listed.split("\0") if name]


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeNetwork:
    """Substitui urlopen: responde ao snapshot (GET) e registra os POSTs ao webhook."""

    def __init__(self):
        self.gets = []
        self.posts = []

    def __call__(self, request, timeout=None):
        if request.data is None:
            self.gets.append(request.full_url)
            return _FakeResponse(b"{}")
        self.posts.append(request.full_url)
        return _FakeResponse(b"Accepted")


def _run_publisher(spec, *, env_value, dry_run, cli_url=None):
    """Executa o publicador com --force, sem rede e sem gravar estado em disco."""
    _label, module, publish_name, select_name, compose_name, mark_name = spec
    network = _FakeNetwork()
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.dict(os.environ), \
            patch("urllib.request.urlopen", side_effect=network) as urlopen, \
            patch.object(module, select_name, return_value=[{"title": "Vaga"}] * 5), \
            patch.object(module, compose_name, return_value="Post de teste"), \
            patch.object(module, mark_name) as mark, \
            redirect_stdout(stdout), redirect_stderr(stderr):
        os.environ.pop(ENV_VAR, None)
        if env_value is not None:
            os.environ[ENV_VAR] = env_value
        code = getattr(module, publish_name)(dry_run=dry_run, force=True, webhook_url=cli_url)
    return code, network, urlopen, mark, stdout.getvalue(), stderr.getvalue()


class NoEmbeddedWebhookTests(unittest.TestCase):
    def test_publishers_have_no_default_webhook(self):
        for label, module, *_ in PUBLISHERS:
            with self.subTest(publicador=label):
                self.assertFalse(hasattr(module, "DEFAULT_WEBHOOK_URL"))

    def test_workflows_read_webhook_only_from_secret(self):
        for name in WORKFLOWS:
            with self.subTest(workflow=name):
                text = (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
                values = [
                    line.split(":", 1)[1].strip()
                    for line in text.splitlines()
                    if line.strip().startswith(f"{ENV_VAR}:")
                ]
                self.assertEqual(values, ["${{ secrets.MAKE_LINKEDIN_WEBHOOK_URL }}"])

    def test_repository_contains_no_make_webhook_url(self):
        offenders = []
        for path in _repository_files():
            relative = path.relative_to(REPO_ROOT)
            if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.splitlines(), start=1):
                if MAKE_HOOK_PATTERN.search(line):
                    # Só o caminho e a linha: a URL nunca aparece na mensagem de falha.
                    offenders.append(f"{relative.as_posix()}:{number}")
        self.assertEqual(offenders, [], "URL de webhook do Make embutida no repositório")


class WebhookResolutionTests(unittest.TestCase):
    def test_command_line_takes_precedence_over_environment(self):
        self.assertEqual(weekly.resolve_webhook_url(CLI_WEBHOOK, env={ENV_VAR: FAKE_WEBHOOK}), CLI_WEBHOOK)

    def test_environment_is_used_without_command_line(self):
        self.assertEqual(weekly.resolve_webhook_url(None, env={ENV_VAR: f"  {FAKE_WEBHOOK}\n"}), FAKE_WEBHOOK)

    def test_missing_or_blank_values_resolve_to_none(self):
        self.assertIsNone(weekly.resolve_webhook_url(None, env={}))
        self.assertIsNone(weekly.resolve_webhook_url("", env={ENV_VAR: ""}))
        self.assertIsNone(weekly.resolve_webhook_url("   ", env={ENV_VAR: " \t"}))

    def test_missing_webhook_message_names_the_secret_and_dry_run(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = weekly.report_missing_webhook()
        self.assertEqual(code, 2)
        self.assertIn(ENV_VAR, stderr.getvalue())
        self.assertIn("--webhook-url", stderr.getvalue())
        self.assertIn("--dry-run", stderr.getvalue())


class PublisherWebhookGateTests(unittest.TestCase):
    def test_missing_webhook_fails_before_any_network_call(self):
        for spec in PUBLISHERS:
            for env_value in (None, "", "   "):
                with self.subTest(publicador=spec[0], env=repr(env_value)):
                    code, network, urlopen, mark, _out, err = _run_publisher(
                        spec, env_value=env_value, dry_run=False
                    )
                    self.assertEqual(code, 2)
                    urlopen.assert_not_called()
                    mark.assert_not_called()
                    self.assertIn(ENV_VAR, err)

    def test_dry_run_works_without_webhook(self):
        for spec in PUBLISHERS:
            with self.subTest(publicador=spec[0]):
                code, network, _urlopen, mark, out, _err = _run_publisher(spec, env_value=None, dry_run=True)
                self.assertEqual(code, 0)
                self.assertEqual(network.posts, [])
                self.assertEqual(len(network.gets), 1)
                mark.assert_not_called()
                self.assertIn("DRY-RUN", out)

    def test_configured_secret_is_used_and_never_logged(self):
        for spec in PUBLISHERS:
            with self.subTest(publicador=spec[0]):
                code, network, _urlopen, mark, out, err = _run_publisher(
                    spec, env_value=FAKE_WEBHOOK, dry_run=False
                )
                self.assertEqual(code, 0)
                self.assertEqual(network.posts, [FAKE_WEBHOOK])
                mark.assert_called_once()
                self.assertNotIn(FAKE_TOKEN, out + err)
                self.assertNotIn(FAKE_WEBHOOK[:35], out + err)

    def test_command_line_webhook_overrides_secret(self):
        for spec in PUBLISHERS:
            with self.subTest(publicador=spec[0]):
                code, network, _urlopen, _mark, out, err = _run_publisher(
                    spec, env_value=FAKE_WEBHOOK, dry_run=False, cli_url=CLI_WEBHOOK
                )
                self.assertEqual(code, 0)
                self.assertEqual(network.posts, [CLI_WEBHOOK])
                self.assertNotIn(CLI_TOKEN, out + err)

    def test_cli_exits_with_error_when_webhook_is_missing(self):
        for _label, module, *_ in PUBLISHERS:
            with self.subTest(publicador=_label):
                stderr = io.StringIO()
                with patch.dict(os.environ), \
                        patch.object(sys, "argv", [module.__name__, "--force"]), \
                        patch("urllib.request.urlopen", side_effect=AssertionError("rede acessada")), \
                        redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    os.environ.pop(ENV_VAR, None)
                    with self.assertRaises(SystemExit) as raised:
                        module.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(ENV_VAR, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
