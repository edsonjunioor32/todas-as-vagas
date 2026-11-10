# -*- coding: utf-8 -*-
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import github_boards  # noqa: E402


class GitHubBoardsSourceTests(unittest.TestCase):
    def test_repositories_include_expanded_tech_community_boards(self):
        """Verifica se os novos murais de tecnologia foram adicionados aos repositórios monitorados."""
        expected_new_boards = [
            "soujava/vagas-java",
            "datascience-br/vagas",
            "androiddevbr/vagas",
            "qa-brasil/vagas",
        ]
        for board in expected_new_boards:
            with self.subTest(board=board):
                self.assertIn(board, github_boards.REPOSITORIES)

    def test_token_injection_when_github_token_is_present(self):
        """Injeta cabeçalho Authorization: Bearer {token} quando GITHUB_TOKEN está configurado."""
        mock_issues = [
            {
                "id": 1001,
                "number": 42,
                "title": "[Remoto] Desenvolvedor Java Pleno",
                "html_url": "https://github.com/soujava/vagas-java/issues/42",
                "created_at": "2026-11-01T12:00:00Z",
                "labels": [{"name": "Remoto"}, {"name": "CLT"}, {"name": "Java"}],
                "body": "Descrição da vaga Java",
            }
        ]
        sent_headers = []

        def mock_get_json(url, headers=None, timeout=30, retries=2):
            sent_headers.append(dict(headers or {}))
            return mock_issues

        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_secret_token_123"}, clear=False), \
             patch.object(github_boards, "get_json", side_effect=mock_get_json):
            rows = github_boards.fetch()

        self.assertTrue(len(sent_headers) > 0)
        for headers in sent_headers:
            self.assertEqual(headers.get("Authorization"), "Bearer ghp_secret_token_123")
            self.assertEqual(headers.get("Accept"), "application/vnd.github+json")

        self.assertTrue(len(rows) > 0)
        # Verifica normalização do job
        first = rows[0]
        self.assertEqual(first["source"], "github")
        self.assertEqual(first["work_model"], "remote")
        self.assertIn("Java", first["skills"])

    def test_no_token_injection_when_github_token_is_absent(self):
        """Não envia Authorization quando GITHUB_TOKEN não está presente no ambiente."""
        sent_headers = []

        def mock_get_json(url, headers=None, timeout=30, retries=2):
            sent_headers.append(dict(headers or {}))
            return []

        env = dict(os.environ)
        env.pop("GITHUB_TOKEN", None)
        with patch.dict(os.environ, env, clear=True), \
             patch.object(github_boards, "get_json", side_effect=mock_get_json):
            github_boards.fetch()

        self.assertTrue(len(sent_headers) > 0)
        for headers in sent_headers:
            self.assertNotIn("Authorization", headers)
            self.assertEqual(headers.get("Accept"), "application/vnd.github+json")

    def test_repo_failure_is_isolated(self):
        """Falha transitória em um repositório não impede a coleta dos demais."""
        def mock_get_json(url, headers=None, timeout=30, retries=2):
            if "soujava/vagas-java" in url:
                raise RuntimeError("503 Service Unavailable")
            return [
                {
                    "id": 2001,
                    "number": 10,
                    "title": "[Remoto] QA Engineer",
                    "html_url": "https://github.com/qa-brasil/vagas/issues/10",
                    "created_at": "2026-11-02T10:00:00Z",
                    "labels": [{"name": "Remoto"}, {"name": "QA"}],
                    "body": "Vaga QA",
                }
            ]

        with patch.object(github_boards, "get_json", side_effect=mock_get_json):
            rows = github_boards.fetch()

        self.assertTrue(len(rows) > 0)
        self.assertTrue(any("qa-brasil" in r["native_id"] for r in rows))


if __name__ == "__main__":
    unittest.main()
