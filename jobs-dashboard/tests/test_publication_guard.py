# -*- coding: utf-8 -*-
"""Guarda de publicação do catálogo e robustez do deploy no pages.yml."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1]
ROOT = DASHBOARD.parent
sys.path.insert(0, str(DASHBOARD))

import publication_guard as guard  # noqa: E402

PAGES = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")


class BlockingPathsTests(unittest.TestCase):
    def test_automatic_data_and_documentation_do_not_block(self):
        changed = [
            "docs/data/linkedin_vagas.json",
            "docs/data/linkedin_digest_state.json",
            "jobs-dashboard/data/greenhouse_br_companies.json",
            "busca_vagas/inhire_tenants_seed.json",
            "ops/OPERATIONS_CHANGELOG.md",
            "",
        ]
        self.assertEqual(guard.blocking_paths(changed), [])

    def test_code_and_other_files_block(self):
        changed = [
            "jobs-dashboard/sources/gupy.py",
            "docs/data/linkedin_vagas.json",
            ".github/workflows/pages.yml",
            "docs/data/fit-taxonomy.json",
        ]
        self.assertEqual(
            guard.blocking_paths(changed),
            [".github/workflows/pages.yml", "docs/data/fit-taxonomy.json",
             "jobs-dashboard/sources/gupy.py"],
        )

    def test_forbidden_data_file_blocks(self):
        changed = ["jobs-dashboard/data/greenhouse_br_companies.json"]
        self.assertEqual(
            guard.blocking_paths(changed, forbid=changed), changed
        )


class GuardCommandTests(unittest.TestCase):
    """Um único repositório temporário: base -> só dados -> código."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name)
        cls._git("init", "-q")
        cls._git("config", "user.email", "teste@example.com")
        cls._git("config", "user.name", "Teste")
        # Repositório descartável: sem assinatura nem hooks herdados da máquina,
        # senão um commit.gpgsign global espera a senha da chave e trava o teste.
        cls._git("config", "commit.gpgsign", "false")
        cls._git("config", "tag.gpgsign", "false")
        cls._git("config", "core.hooksPath", os.devnull)
        cls._write("jobs-dashboard/pipeline.py", "print('v1')\n")
        cls._write("docs/data/linkedin_vagas.json", "[]\n")
        cls.base = cls._commit("base")
        cls._write("docs/data/linkedin_vagas.json", "[1]\n")
        cls._write("README.md", "doc\n")
        cls.data_only = cls._commit("dados")
        cls._write("jobs-dashboard/pipeline.py", "print('v2')\n")
        cls.code = cls._commit("codigo")
        cls.cwd = os.getcwd()
        os.chdir(cls.repo)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.cwd)
        cls.tmp.cleanup()

    @classmethod
    def _git(cls, *args):
        return subprocess.run(["git", *args], cwd=cls.repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    @classmethod
    def _write(cls, path, text):
        target = cls.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    @classmethod
    def _commit(cls, message):
        cls._git("add", "-A")
        cls._git("commit", "-q", "-m", message)
        return cls._git("rev-parse", "HEAD")

    def test_same_commit_is_safe(self):
        self.assertEqual(guard.main(["--base", self.base, "--head", self.base]), 0)

    def test_data_only_advance_is_safe(self):
        self.assertEqual(guard.main(["--base", self.base, "--head", self.data_only]), 0)

    def test_code_advance_blocks(self):
        self.assertEqual(guard.main(["--base", self.base, "--head", self.code]), 1)

    def test_forbid_blocks_when_that_data_file_changed(self):
        self.assertEqual(
            guard.main(["--base", self.base, "--head", self.data_only,
                        "--forbid", "docs/data/linkedin_vagas.json"]), 1)

    def test_unknown_reference_is_an_error(self):
        self.assertEqual(guard.main(["--base", self.base, "--head", "nao-existe"]), 2)


class PagesWorkflowTests(unittest.TestCase):
    def test_pre_publication_check_uses_the_guard(self):
        start = PAGES.index("- name: Confirmar que o código da coleta ainda é o commit disparador")
        step = PAGES[start:PAGES.index("- name: Publicar snapshots no ramo dedicado")]
        self.assertIn('publication_guard.py --base "$GITHUB_SHA" --head origin/main', step)
        self.assertNotIn('!= "$GITHUB_SHA"', step)

    def test_index_commit_is_non_blocking_and_never_overwrites_newer_indexes(self):
        start = PAGES.index("- name: Preservar histórico e fotografia pública")
        step = PAGES[start:PAGES.index("- name: Preparar analisador para o site")]
        self.assertIn("continue-on-error: true", step)
        self.assertIn('--forbid "${index_files[@]}"', step)
        self.assertIn("git worktree add --detach \"$index_worktree\" origin/main", step)
        self.assertNotIn("não faremos rebase silencioso", step)

    def test_both_deploys_wait_for_the_artifact_and_retry_once(self):
        self.assertEqual(PAGES.count("- name: Aguardar o artefato do Pages na API"), 2)
        self.assertEqual(PAGES.count("id: deployment-retry"), 2)
        self.assertEqual(PAGES.count("if: steps.deployment.outcome == 'failure'"), 4)
        self.assertEqual(
            PAGES.count("url: ${{ steps.deployment.outputs.page_url || "
                        "steps.deployment-retry.outputs.page_url }}"),
            2,
        )


if __name__ == "__main__":
    unittest.main()
