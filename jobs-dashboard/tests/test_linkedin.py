# -*- coding: utf-8 -*-
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

DASHBOARD = Path(__file__).resolve().parents[1]
REPO_ROOT = DASHBOARD.parent
sys.path.insert(0, str(DASHBOARD))
sys.path.insert(0, str(REPO_ROOT))

from sources import linkedin  # noqa: E402
from tools import collect_linkedin  # noqa: E402


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

    def test_normalize_maps_brazil_location_as_remote(self):
        """Vagas onde o LinkedIn retorna apenas Brazil como localização devem ser mapeadas como remotas."""
        today = date.today().isoformat()
        row = linkedin._normalize(
            {
                "source": "linkedin",
                "sourceLabel": "LinkedIn",
                "native_id": "li-9999",
                "title": "Analista de Suporte Técnico",
                "company": "Empresa SaaS",
                "url": "https://www.linkedin.com/jobs/view/9999",
                "location": "Brazil",
                "workplaceType": "on-site",  # vindo erroneamente do parser legado
                "publishedAt": today,
                "easyApply": True,
            }
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brazil")
        self.assertEqual(row["market"], "BR")
        self.assertEqual(row["country"], "BR")

    def test_normalize_regression_for_job_4483475105_remote_easy_apply(self):
        """Teste de regressão específico para a vaga ID 4483475105 (Tryp.com Operations Assistant)."""
        today = date.today().isoformat()
        job_payload = {
            "source": "linkedin",
            "sourceLabel": "LinkedIn",
            "native_id": "li-4483475105",
            "title": "Operations Assistant",
            "company": "Tryp.com",
            "url": "https://www.linkedin.com/jobs/view/4483475105",
            "location": "Brazil",
            "workplaceType": "remote",
            "publishedAt": today,
            "easyApply": True,
            "salaryMin": 2500.0,
            "salaryMax": None,
            "currency": "BRL",
        }
        path = self._write_snapshot(self._payload(job=job_payload))
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
        target = rows[0]
        self.assertEqual(target["native_id"], "li-4483475105")
        self.assertEqual(target["title"], "Operations Assistant")
        self.assertEqual(target["company"], "Tryp.com")
        self.assertEqual(target["work_model"], "remote")
        self.assertEqual(target["city"], "Brazil")
        self.assertEqual(target["country"], "BR")
        self.assertEqual(target["market"], "BR")
        self.assertEqual(target["url"], "https://www.linkedin.com/jobs/view/4483475105")
        self.assertEqual(target["salary_min"], 2500.0)

    def test_normalize_accepts_country_subdomain_url(self):
        row = linkedin._normalize(
            self._payload()["jobs"][0]
            | {
                "url": "https://br.linkedin.com/jobs/view/4483475105?position=1&pageNum=0",
                "native_id": "li-4483475105",
            }
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["url"], "https://www.linkedin.com/jobs/view/4483475105")
        self.assertEqual(row["native_id"], "li-4483475105")

    def test_collect_linkedin_normalize_job_mappings(self):
        """Valida que normalize_linkedin_job categoriza corretamente remoto/híbrido/presencial."""
        # 1. Localização "Brazil" -> remote
        job_br = {
            "job_url": "https://www.linkedin.com/jobs/view/4483475105",
            "title": "Operations Assistant",
            "company": "Tryp.com",
            "location": "Brazil",
            "date_posted": "2026-10-30",
            "description": "Trabalho 100% remoto.",
        }
        norm_br = collect_linkedin.normalize_linkedin_job(job_br)
        self.assertEqual(norm_br["workplaceType"], "remote")
        self.assertEqual(norm_br["native_id"], "li-4483475105")
        self.assertEqual(norm_br["url"], "https://www.linkedin.com/jobs/view/4483475105")

        # 2. Cidade específica com 'remoto' no título -> remote
        job_city_rem = {
            "job_url": "https://www.linkedin.com/jobs/view/4481001",
            "title": "Desenvolvedor Backend (Remoto)",
            "company": "Tech Corp",
            "location": "São Paulo, São Paulo, Brazil",
        }
        norm_city_rem = collect_linkedin.normalize_linkedin_job(job_city_rem)
        self.assertEqual(norm_city_rem["workplaceType"], "remote")

        # 3. Cidade específica com 'híbrido' -> hybrid
        job_hybrid = {
            "job_url": "https://www.linkedin.com/jobs/view/4481002",
            "title": "Analista de Suporte Híbrido",
            "company": "Tech Corp",
            "location": "São Paulo, São Paulo, Brazil",
        }
        norm_hybrid = collect_linkedin.normalize_linkedin_job(job_hybrid)
        self.assertEqual(norm_hybrid["workplaceType"], "hybrid")

        # 4. Cidade específica presencial -> on-site
        job_onsite = {
            "job_url": "https://www.linkedin.com/jobs/view/4481003",
            "title": "Analista de Suporte Presencial",
            "company": "Tech Corp",
            "location": "Curitiba, Paraná, Brazil",
        }
        norm_onsite = collect_linkedin.normalize_linkedin_job(job_onsite)
        self.assertEqual(norm_onsite["workplaceType"], "on-site")

        # 5. Busca remota dedicada (flag is_remote_search) -> remote
        job_remote_pass = {
            "job_url": "https://www.linkedin.com/jobs/view/4481004",
            "title": "Analista de Suporte",
            "company": "Tech Corp",
            "location": "Belo Horizonte, Minas Gerais, Brazil",
        }
        norm_remote_pass = collect_linkedin.normalize_linkedin_job(
            job_remote_pass, is_remote_search=True
        )
        self.assertEqual(norm_remote_pass["workplaceType"], "remote")

    def test_jobspy_patched_search_params_adds_remote_filter(self):
        """Garante que a busca remota dedicada do JobSpy injeta f_WT=2 no LinkedIn."""
        from jobspy.linkedin import LinkedIn

        mock_scraper = MagicMock()
        mock_scraper.scraper_input.search_term = "Suporte"
        mock_scraper.scraper_input.location = "Brazil"
        mock_scraper.scraper_input.distance = 50
        mock_scraper.scraper_input.easy_apply = True
        mock_scraper.scraper_input.linkedin_company_ids = None
        mock_scraper.scraper_input.hours_old = 720
        mock_scraper.scraper_input.is_remote = True

        params = LinkedIn._search_params(mock_scraper)
        self.assertEqual(params.get("f_WT"), "2")
        self.assertEqual(params.get("f_AL"), "true")
        self.assertEqual(params.get("f_TPR"), "r2592000")


if __name__ == "__main__":
    unittest.main()
