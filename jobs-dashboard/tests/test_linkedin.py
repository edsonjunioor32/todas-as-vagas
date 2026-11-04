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
            "workplaceVerified": True,
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
                    "publishedAt": (today - timedelta(days=61)).isoformat()
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

    def test_unverified_workplace_is_not_inferred_from_legacy_fields(self):
        """Localização Brazil e modalidade legada não verificam o selo do LinkedIn."""
        today = date.today().isoformat()
        raw = {
            "source": "linkedin",
            "sourceLabel": "LinkedIn",
            "native_id": "li-9999",
            "title": "Analista de Suporte Técnico Remoto",
            "company": "Empresa SaaS",
            "url": "https://www.linkedin.com/jobs/view/9999",
            "location": "Brazil",
            "workplaceType": "remote",
            "workplaceVerified": False,
            "is_remote": True,
            "publishedAt": today,
            "easyApply": True,
        }
        row = linkedin._normalize(raw)
        self.assertIsNotNone(row)
        self.assertEqual(row["work_model"], "")
        self.assertEqual(row["city"], "Brazil")
        self.assertEqual(row["market"], "BR")
        self.assertEqual(row["country"], "BR")

        raw["workplaceVerified"] = "false"
        self.assertEqual(linkedin._normalize(raw)["work_model"], "")

    def test_verified_workplace_overrides_legacy_location_heuristic(self):
        today = date.today().isoformat()
        row = self._payload(
            job={
                "native_id": "li-4486898930",
                "title": "(1608) Forward Deployed Engineer",
                "company": "Nortal",
                "url": "https://www.linkedin.com/jobs/view/4486898930",
                "location": "Greater Rio de Janeiro",
                "workplaceType": "remote",
                "workplaceVerified": True,
                "publishedAt": today,
            }
        )["jobs"][0]
        normalized = linkedin._normalize(row, today=date.today())
        self.assertEqual(normalized["work_model"], "remote")

        row = self._payload(
            job={
                "native_id": "li-4478138443",
                "title": "Açougueiro(a) - Vila Mascote",
                "company": "St Marche",
                "url": "https://www.linkedin.com/jobs/view/4478138443",
                "location": "São Paulo, São Paulo, Brazil",
                "workplaceType": "on-site",
                "workplaceVerified": True,
                "publishedAt": today,
            }
        )["jobs"][0]
        normalized = linkedin._normalize(row, today=date.today())
        self.assertEqual(normalized["work_model"], "on-site")

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

    def test_fetch_details_capture_matches_tracking_query(self):
        job_id = "4486898930"
        request_url = (
            "https://www.linkedin.com/jobs/view/4486898930"
            "?trackingId=public-linkedin-test"
        )
        response = MagicMock()
        response.url = request_url
        response.text = (
            '<li class="job-details-jobs-unified-top-card__job-insight">'
            "<span>Remote</span></li>"
        )
        session = MagicMock()
        session.get.return_value = response

        details = collect_linkedin._fetch_details_with_workplace_capture(
            session,
            job_id,
            lambda: {"description": session.get(request_url).text},
        )

        self.assertEqual(details["work_from_home_type"], "remote")
        self.assertEqual(session.get.call_count, 1)

    def test_fetch_details_capture_uses_final_linkedin_url_after_redirect(self):
        job_id = "4478138443"
        response = MagicMock()
        response.url = (
            "https://www.linkedin.com/jobs/view/4478138443/"
            "?trackingId=redirected"
        )
        response.text = (
            '<li class="job-details-jobs-unified-top-card__job-insight">'
            "<span>Presencial</span></li>"
        )
        session = MagicMock()
        session.get.return_value = response

        details = collect_linkedin._fetch_details_with_workplace_capture(
            session,
            job_id,
            lambda: {"description": session.get("https://www.linkedin.com/login").text},
        )

        self.assertEqual(details["work_from_home_type"], "on-site")

    def test_fetch_details_capture_ignores_another_job_and_non_linkedin_hosts(self):
        for request_url, response_url in (
            (
                "https://www.linkedin.com/jobs/view/123456",
                "https://www.linkedin.com/jobs/view/123456",
            ),
            (
                "https://www.linkedin.com.evil.example/jobs/view/4486898930",
                "https://www.linkedin.com.evil.example/jobs/view/4486898930",
            ),
            ("/jobs/view/4486898930", "/jobs/view/4486898930"),
            (
                "https://www.linkedin.com/other/jobs/view/4486898930/extra",
                "https://www.linkedin.com/other/jobs/view/4486898930/extra",
            ),
        ):
            with self.subTest(url=request_url):
                response = MagicMock()
                response.url = response_url
                response.text = (
                    '<li class="job-details-jobs-unified-top-card__job-insight">'
                    "<span>Remote</span></li>"
                )
                session = MagicMock()
                session.get.return_value = response
                details = collect_linkedin._fetch_details_with_workplace_capture(
                    session,
                    "4486898930",
                    lambda: {"description": session.get(request_url).text},
                )
                self.assertEqual(details.get("work_from_home_type"), None)

    def test_fetch_details_capture_ignores_non_linkedin_redirect_destination(self):
        job_id = "4486898930"
        response = MagicMock()
        response.url = "https://example.com/jobs/view/4486898930"
        response.text = (
            '<li class="job-details-jobs-unified-top-card__job-insight">'
            "<span>Remote</span></li>"
        )
        session = MagicMock()
        session.get.return_value = response

        details = collect_linkedin._fetch_details_with_workplace_capture(
            session,
            job_id,
            lambda: {"description": session.get(
                "https://www.linkedin.com/jobs/view/4486898930"
            ).text},
        )

        self.assertNotIn("work_from_home_type", details)

        response.url = "https://www.linkedin.com/jobs/view/123456"
        details = collect_linkedin._fetch_details_with_workplace_capture(
            session,
            job_id,
            lambda: {"description": session.get(
                "https://www.linkedin.com/jobs/view/4486898930"
            ).text},
        )
        self.assertNotIn("work_from_home_type", details)

        response.url = ""
        details = collect_linkedin._fetch_details_with_workplace_capture(
            session,
            job_id,
            lambda: {"description": session.get(
                "https://www.linkedin.com/jobs/view/4486898930"
            ).text},
        )
        self.assertNotIn("work_from_home_type", details)

    def test_extracts_workplace_badge_from_linkedin_detail_html(self):
        remote_html = """
        <li class="job-details-jobs-unified-top-card__job-insight--highlight">
            <span class="job-details-jobs-unified-top-card__job-insight-text-button">Remote</span>
        </li>
        """
        onsite_html = """
        <li class="job-details-jobs-unified-top-card__job-insight">
            <span>Presencial</span>
        </li>
        """
        hybrid_html = """
        <li class="jobs-unified-top-card__job-insight">
            <span>Hybrid</span>
        </li>
        """
        self.assertEqual(
            collect_linkedin._extract_workplace_type_from_html(remote_html),
            "remote",
        )
        self.assertEqual(
            collect_linkedin._extract_workplace_type_from_html(onsite_html),
            "on-site",
        )
        self.assertEqual(
            collect_linkedin._extract_workplace_type_from_html(hybrid_html),
            "hybrid",
        )

    def test_workplace_parser_does_not_read_past_void_tags(self):
        html = """
        <li class="job-details-jobs-unified-top-card__job-insight">
          <span>Tempo integral</span><br>
        </li>
        <section><p>Descrição geral: trabalho remoto</p></section>
        """
        self.assertEqual(collect_linkedin._extract_workplace_type_from_html(html), "")
        void_container = """
        <img class="job-insight" aria-label="Remote">
        <section><p>Presencial no escritório</p></section>
        """
        self.assertEqual(
            collect_linkedin._extract_workplace_type_from_html(void_container), ""
        )

    def test_collect_linkedin_normalize_job_mappings(self):
        """Só o selo da página individual classifica o modelo de trabalho."""
        job_br_without_badge = {
            "job_url": "https://www.linkedin.com/jobs/view/4483475105",
            "title": "Operations Assistant",
            "company": "Tryp.com",
            "location": "Brazil",
            "date_posted": "2026-10-30",
            "description": "Trabalho 100% remoto.",
            "is_remote": True,
        }
        norm_unverified = collect_linkedin.normalize_linkedin_job(job_br_without_badge)
        self.assertEqual(norm_unverified["workplaceType"], "")
        self.assertFalse(norm_unverified["workplaceVerified"])

        job_remote_pass = {
            "job_url": "https://www.linkedin.com/jobs/view/4481004",
            "title": "Analista de Suporte",
            "company": "Tech Corp",
            "location": "Belo Horizonte, Minas Gerais, Brazil",
            "work_from_home_type": "remote",
        }
        norm_remote_pass = collect_linkedin.normalize_linkedin_job(
            job_remote_pass, is_remote_search=True
        )
        self.assertEqual(norm_remote_pass["workplaceType"], "remote")
        self.assertTrue(norm_remote_pass["workplaceVerified"])

        # A busca remota pode trazer backfill presencial; o filtro não classifica.
        job_backfilled = {
            "job_url": "https://www.linkedin.com/jobs/view/4481005",
            "title": "Analista de Suporte",
            "company": "Tech Corp",
            "location": "Brazil",
            "is_remote": True,
        }
        norm_backfilled = collect_linkedin.normalize_linkedin_job(
            job_backfilled, is_remote_search=True
        )
        self.assertEqual(norm_backfilled["workplaceType"], "")
        self.assertFalse(norm_backfilled["workplaceVerified"])

        # Regressão Nortal: o selo Remote prevalece sobre uma localização regional.
        job_nortal = {
            "job_url": "https://www.linkedin.com/jobs/view/4486898930",
            "title": "(1608) Forward Deployed Engineer",
            "company": "Nortal",
            "location": "Greater Rio de Janeiro",
            "work_from_home_type": "Remote",
        }
        norm_nortal = collect_linkedin.normalize_linkedin_job(job_nortal)
        self.assertEqual(norm_nortal["workplaceType"], "remote")
        self.assertTrue(norm_nortal["workplaceVerified"])

        # Regressão St Marche: o selo Presencial prevalece sobre qualquer heurística.
        job_st_marche = {
            "job_url": "https://www.linkedin.com/jobs/view/4478138443",
            "title": "Açougueiro(a) - Vila Mascote",
            "company": "St Marche",
            "location": "São Paulo, São Paulo, Brazil",
            "work_from_home_type": "Presencial",
        }
        norm_st_marche = collect_linkedin.normalize_linkedin_job(job_st_marche)
        self.assertEqual(norm_st_marche["workplaceType"], "on-site")
        self.assertTrue(norm_st_marche["workplaceVerified"])

    def test_jobspy_patched_search_params_adds_remote_filter(self):
        """Garante que a busca remota dedicada do JobSpy injeta f_WT=2 no LinkedIn."""
        try:
            from jobspy.linkedin import LinkedIn
        except (ImportError, Exception):
            self.skipTest("jobspy não instalado neste ambiente de teste")
            return

        mock_scraper = MagicMock()
        mock_scraper.scraper_input.search_term = "Suporte"
        mock_scraper.scraper_input.location = "Brazil"
        mock_scraper.scraper_input.distance = 50
        mock_scraper.scraper_input.easy_apply = True
        mock_scraper.scraper_input.linkedin_company_ids = None
        mock_scraper.scraper_input.hours_old = 1440
        mock_scraper.scraper_input.is_remote = True

        params = LinkedIn._search_params(mock_scraper)
        self.assertEqual(params.get("f_WT"), "2")
        self.assertEqual(params.get("f_AL"), "true")
        self.assertEqual(params.get("f_TPR"), "r5184000")


    def test_collect_linkedin_open_unrestricted_collection(self):
        """Garante que a coleta padrão do Todas as Vagas seja ampla (sem termos de busca fixos)
        e capture vagas remotas, híbridas e presenciais de áreas diversas.
        """
        records_general = [
            {
                "id": "li-101",
                "job_url": "https://www.linkedin.com/jobs/view/101",
                "title": "Advogado Corporativo",
                "company": "Escritório Brasil",
                "location": "São Paulo, São Paulo, Brazil",
                "date_posted": "2026-10-30",
                "work_from_home_type": "on-site",
            },
            {
                "id": "li-102",
                "job_url": "https://www.linkedin.com/jobs/view/102",
                "title": "Product Designer Híbrido",
                "company": "Design Lab",
                "location": "Curitiba, Paraná, Brazil",
                "date_posted": "2026-10-30",
                "work_from_home_type": "hybrid",
            },
        ]
        records_remote = [
            {
                "id": "li-103",
                "job_url": "https://www.linkedin.com/jobs/view/103",
                "title": "Operations Assistant",
                "company": "Tryp.com",
                "location": "Brazil",
                "date_posted": "2026-10-30",
                "work_from_home_type": "remote",
            }
        ]

        calls = []

        class MockDataFrame(list):
            def __init__(self, data):
                super().__init__(data)
                self.empty = len(data) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(*args, **kwargs):
            calls.append(kwargs)
            if kwargs.get("is_remote"):
                return MockDataFrame(records_remote)
            return MockDataFrame(records_general)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            with patch.object(collect_linkedin, "scrape_jobs", side_effect=mock_scrape):
                results = collect_linkedin.collect_linkedin(
                    terms=None,
                    results_limit=10,
                    remote_results_limit=5,
                    out_path=str(tmp_path),
                )

            self.assertEqual(len(results), 3)
            # Confirma que ambas as fases rodaram com search_term=None (sem filtro por cargo)
            self.assertIsNone(calls[0]["search_term"])
            self.assertFalse(calls[0].get("is_remote", False))
            self.assertIsNone(calls[1]["search_term"])
            self.assertTrue(calls[1].get("is_remote", False))

            # Valida presença dos três modelos de trabalho: presencial, híbrido e remoto
            types = {r["workplaceType"] for r in results}
            self.assertEqual(types, {"on-site", "hybrid", "remote"})

            with open(tmp_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["count"], 3)
            self.assertEqual(saved["filter"], "easy_apply")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_jobspy_adaptive_delay_and_429_backoff_handling(self):
        """Garante atraso adaptativo (2.5-3.0s) e tratamento resiliente de HTTP 429 com Retry-After."""
        try:
            from jobspy.linkedin import LinkedIn
            import jobspy.linkedin as jl
        except (ImportError, Exception):
            self.skipTest("jobspy não instalado neste ambiente")
            return

        # 1. Verifica delay adaptativo configurado
        self.assertEqual(LinkedIn.delay, (2.5, 3.0))

        # 2. Testa recuperação resiliente de 429 via create_session
        if not hasattr(jl, "create_session"):
            return

        mock_raw_session = MagicMock()
        mock_scraper_input = MagicMock()
        mock_scraper_input.ca_cert = None
        mock_scraper_input.user_agent = None

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "0"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}

        underlying_mock_get = MagicMock(side_effect=[resp_429, resp_200])
        mock_raw_session.get = underlying_mock_get

        session = jl.create_session(mock_raw_session, mock_scraper_input)
        
        with patch("time.sleep", return_value=None) as mock_sleep:
            result = session.get("https://www.linkedin.com/test", params={"start": 0})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(underlying_mock_get.call_count, 2)
            mock_sleep.assert_called_once_with(0.0)


    def test_collect_linkedin_paginates_beyond_legacy_limit(self):
        """A coleta usa offset em lotes e ultrapassa o limite legado de 100 resultados."""
        records = [
            {
                "id": f"li-{index}",
                "job_url": f"https://www.linkedin.com/jobs/view/{index}",
                "title": f"Vaga {index}",
                "company": "Empresa Teste",
                "location": "São Paulo, São Paulo, Brazil",
                "date_posted": "2026-11-03",
            }
            for index in range(205)
        ]
        calls = []

        class MockDataFrame(list):
            def __init__(self, data):
                super().__init__(data)
                self.empty = len(data) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(*args, **kwargs):
            calls.append(dict(kwargs))
            start = kwargs["offset"]
            size = kwargs["results_wanted"]
            return MockDataFrame(records[start : start + size])

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            with patch.object(collect_linkedin, "scrape_jobs", side_effect=mock_scrape):
                results = collect_linkedin.collect_linkedin(
                    terms=None,
                    results_limit=205,
                    remote_results_limit=0,
                    hours_old=1440,
                    out_path=str(tmp_path),
                    include_remote_pass=False,
                )

            self.assertEqual(len(results), 205)
            self.assertEqual([call["offset"] for call in calls], [0, 100, 200])
            self.assertEqual(
                [call["results_wanted"] for call in calls],
                [100, 100, 100],
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_normalize_accepts_job_within_two_month_window(self):
        today = date.today()
        row = linkedin._normalize(
            self._payload()["jobs"][0]
            | {"publishedAt": (today - timedelta(days=60)).isoformat()},
            today=today,
        )
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
