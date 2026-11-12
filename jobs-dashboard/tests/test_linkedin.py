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
            "workplaceEvidence": "linkedin_badge",
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
            "filter": "public_brazil",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "jobs": [row],
        }
        payload.update(overrides)
        return payload

    def test_fetch_normalizes_valid_public_snapshot(self):
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

    def test_fetch_rejects_unsupported_snapshot_filter(self):
        path = self._write_snapshot(self._payload(filter="all"))
        try:
            with patch.dict(
                os.environ, {"LINKEDIN_SNAPSHOT_PATH": str(path)}, clear=False
            ):
                with self.assertRaisesRegex(RuntimeError, "filter is unsupported"):
                    linkedin.fetch()
        finally:
            path.unlink(missing_ok=True)

    def test_fetch_accepts_public_and_legacy_non_easy_apply_snapshots(self):
        for snapshot_filter in ("public_brazil", "easy_apply"):
            with self.subTest(snapshot_filter=snapshot_filter):
                path = self._write_snapshot(
                    self._payload(
                        filter=snapshot_filter,
                        job={"easyApply": False},
                    )
                )
                try:
                    with patch.dict(
                        os.environ,
                        {"LINKEDIN_SNAPSHOT_PATH": str(path)},
                        clear=False,
                    ):
                        rows = linkedin.fetch()
                finally:
                    path.unlink(missing_ok=True)

                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["work_model"], "remote")

    def test_unknown_application_type_remains_in_snapshot_and_catalog(self):
        record = {
            "id": "li-99001",
            "job_url": "https://www.linkedin.com/jobs/view/99001",
            "title": "Analista de Suporte",
            "company": "Empresa Teste",
            "location": "São Paulo, São Paulo, Brazil",
            "date_posted": date.today().isoformat(),
        }

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            summary_path = Path(temporary) / "summary.md"
            summary_path.write_text("", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "LINKEDIN_SNAPSHOT_PATH": str(snapshot_path),
                    "LINKEDIN_MAX_AGE_DAYS": "60",
                    "LINKEDIN_SNAPSHOT_MAX_AGE_HOURS": "36",
                    "GITHUB_STEP_SUMMARY": str(summary_path),
                },
                clear=False,
            ), patch.object(
                collect_linkedin, "scrape_jobs", return_value=MockDataFrame([record])
            ), patch.object(collect_linkedin.time, "sleep"):
                collect_linkedin.collect_linkedin(
                    results_limit=1,
                    remote_results_limit=0,
                    include_remote_pass=False,
                    out_path=str(snapshot_path),
                )
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                snapshot_row = payload["jobs"][0]
                self.assertEqual(snapshot_row["applicationType"], "unknown")
                self.assertIs(snapshot_row["applicationVerified"], False)
                self.assertEqual(
                    snapshot_row["applicationEvidence"], "no_public_evidence"
                )
                self.assertIn("desconhecida 1", summary_path.read_text(encoding="utf-8"))
                self.assertEqual(len(linkedin.fetch()), 1)

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
            "workplaceVerified": True,
            "workplaceEvidence": "description_explicit",
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
            '<button class="jobs-apply-button">Easy Apply</button>'
        )
        session = MagicMock()
        session.get.return_value = response

        details = collect_linkedin._fetch_details_with_workplace_capture(
            session,
            job_id,
            lambda: {"description": session.get(request_url).text},
        )

        self.assertEqual(
            collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE[job_id], "remote"
        )
        self.assertEqual(
            collect_linkedin.CAPTURED_LINKEDIN_APPLICATION[job_id],
            ("easy_apply", True, "easy_apply_badge"),
        )
        self.assertNotIn("work_from_home_type", details)
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

        self.assertEqual(
            collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE[job_id], "on-site"
        )

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
                self.assertNotIn(
                    "4486898930", collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE
                )

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

        self.assertNotIn("4486898930", collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE)

        response.url = "https://www.linkedin.com/jobs/view/123456"
        details = collect_linkedin._fetch_details_with_workplace_capture(
            session,
            job_id,
            lambda: {"description": session.get(
                "https://www.linkedin.com/jobs/view/4486898930"
            ).text},
        )
        self.assertNotIn("4486898930", collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE)

        response.url = ""
        details = collect_linkedin._fetch_details_with_workplace_capture(
            session,
            job_id,
            lambda: {"description": session.get(
                "https://www.linkedin.com/jobs/view/4486898930"
            ).text},
        )
        self.assertNotIn("4486898930", collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE)

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

    def test_extracts_explicit_easy_apply_cta(self):
        for html in (
            '<button aria-label="Easy Apply">Easy Apply</button>',
            '<button>Candidatura simplificada</button>',
        ):
            with self.subTest(html=html):
                self.assertEqual(
                    collect_linkedin._extract_application_evidence_from_html(html),
                    ("easy_apply", True, "easy_apply_badge"),
                )

    def test_external_application_requires_explicit_external_evidence(self):
        html = '<a href="https://careers.example/jobs/1/apply">Candidatar-se</a>'
        self.assertEqual(
            collect_linkedin._extract_application_evidence_from_html(html),
            ("external", True, "external_apply_link"),
        )
        marker = '<button>Apply on company website</button>'
        self.assertEqual(
            collect_linkedin._extract_application_evidence_from_html(marker),
            ("external", True, "external_apply_marker"),
        )
        portuguese_marker = (
            '<button>Candidatar-se no site da empresa</button>'
        )
        self.assertEqual(
            collect_linkedin._extract_application_evidence_from_html(
                portuguese_marker
            ),
            ("external", True, "external_apply_marker"),
        )

    def test_generic_apply_cta_without_external_target_is_unknown(self):
        html = '<button class="jobs-apply-button">Apply</button>'
        self.assertEqual(
            collect_linkedin._extract_application_evidence_from_html(html),
            ("unknown", False, "no_public_evidence"),
        )
        linkedin_url = (
            '<a href="https://www.linkedin.com/jobs/view/123/apply">Apply</a>'
        )
        self.assertEqual(
            collect_linkedin._extract_application_evidence_from_html(linkedin_url),
            ("unknown", False, "no_public_evidence"),
        )

    def test_conflicting_easy_apply_and_external_ctas_are_unknown(self):
        html = (
            '<button>Easy Apply</button>'
            '<a href="https://careers.example/jobs/1/apply">Apply</a>'
        )
        self.assertEqual(
            collect_linkedin._extract_application_evidence_from_html(html),
            ("unknown", False, "conflicting_signals"),
        )

    def test_dexian_screenshot_verifies_easy_apply_without_public_cta(self):
        collect_linkedin.CAPTURED_LINKEDIN_APPLICATION.clear()
        normalized = collect_linkedin.normalize_linkedin_job({
            "job_url": "https://www.linkedin.com/jobs/view/4479109326",
            "title": "Senior Application Support Analyst",
            "company": "Dexian Brasil",
            "location": "Brazil",
        })
        self.assertEqual(normalized["applicationType"], "easy_apply")
        self.assertTrue(normalized["applicationVerified"])
        self.assertEqual(
            normalized["applicationEvidence"],
            "user_screenshot_2026-11-03",
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
        self_closing_void = """
        <li class="job-details-jobs-unified-top-card__job-insight">
          <span>Tempo integral</span><br/><span>Remote</span>
        </li>
        """
        self.assertEqual(
            collect_linkedin._extract_workplace_type_from_html(self_closing_void),
            "remote",
        )

    def test_collect_linkedin_normalize_job_mappings(self):
        """Selo, descrição explícita e override confirmam modalidade."""
        collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE.clear()
        generic_remote = {
            "job_url": "https://www.linkedin.com/jobs/view/4481004",
            "title": "Analista de Suporte",
            "company": "Tech Corp",
            "location": "Brazil",
            "date_posted": "2026-10-30",
            "description": "Experiência com trabalho remoto será um diferencial.",
            "work_from_home_type": "remote",
            "is_remote": True,
        }
        norm_generic = collect_linkedin.normalize_linkedin_job(generic_remote)
        self.assertEqual(norm_generic["workplaceType"], "")
        self.assertEqual(norm_generic["workplaceEvidence"], "")
        self.assertFalse(norm_generic["workplaceVerified"])

        explicit_remote = generic_remote | {
            "job_url": "https://www.linkedin.com/jobs/view/4481006",
            "title": "Senior Application Support Analyst",
            "company": "Tech Corp",
            "description": "No conforto da sua casa! Regime 100% Home Office.",
        }
        norm_explicit = collect_linkedin.normalize_linkedin_job(explicit_remote)
        self.assertEqual(norm_explicit["workplaceType"], "remote")
        self.assertEqual(norm_explicit["workplaceEvidence"], "description_explicit")
        self.assertTrue(norm_explicit["workplaceVerified"])

        ambiguous = explicit_remote | {
            "job_url": "https://www.linkedin.com/jobs/view/4481008",
            "description": "Modelo de trabalho remoto ou presencial, conforme a equipe."
        }
        norm_ambiguous = collect_linkedin.normalize_linkedin_job(ambiguous)
        self.assertEqual(norm_ambiguous["workplaceType"], "")
        self.assertFalse(norm_ambiguous["workplaceVerified"])

        # O selo da página individual prevalece sobre campos genéricos e descrição.
        collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE["4481007"] = "hybrid"
        badge_job = generic_remote | {
            "job_url": "https://www.linkedin.com/jobs/view/4481007",
            "description": "Regime 100% Home Office.",
            "work_from_home_type": "on-site",
        }
        norm_badge = collect_linkedin.normalize_linkedin_job(badge_job)
        self.assertEqual(norm_badge["workplaceType"], "hybrid")
        self.assertEqual(norm_badge["workplaceEvidence"], "linkedin_badge")
        self.assertTrue(norm_badge["workplaceVerified"])
        collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE.clear()

        # Exceções confirmadas por evidência fornecida pelo usuário.
        examples = [
            ("4486898930", "remote"),
            ("4478138443", "on-site"),
        ]
        for job_id, expected in examples:
            with self.subTest(job_id=job_id):
                normalized = collect_linkedin.normalize_linkedin_job({
                    "job_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                    "title": "Vaga de exemplo",
                    "company": "Empresa",
                    "location": "Brazil",
                })
                self.assertEqual(normalized["workplaceType"], expected)
                self.assertEqual(normalized["workplaceEvidence"], "manual_override")
                self.assertTrue(normalized["workplaceVerified"])

    def test_screenshot_verified_workplace_overrides_apply_without_page_badge(self):
        examples = [
            (
                "4486898930",
                "(1608) Forward Deployed Engineer",
                "Nortal",
                "Greater Rio de Janeiro",
                "remote",
            ),
            (
                "4478138443",
                "Açougueiro(a) - Vila Mascote",
                "St Marche",
                "São Paulo, São Paulo, Brazil",
                "on-site",
            ),
            (
                "4479109326",
                "Senior Application Support Analyst",
                "Dexian Brasil",
                "Brazil",
                "remote",
            ),
        ]
        for job_id, title, company, location, expected in examples:
            with self.subTest(job_id=job_id):
                normalized = collect_linkedin.normalize_linkedin_job({
                    "job_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                    "title": title,
                    "company": company,
                    "location": location,
                })
                self.assertEqual(normalized["workplaceType"], expected)
                self.assertTrue(normalized["workplaceVerified"])

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
                "description": "Modalidade de trabalho: presencial.",
            },
            {
                "id": "li-102",
                "job_url": "https://www.linkedin.com/jobs/view/102",
                "title": "Product Designer Híbrido",
                "company": "Design Lab",
                "location": "Curitiba, Paraná, Brazil",
                "date_posted": "2026-10-30",
                "description": "Modelo de trabalho: híbrido.",
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
                "description": "Regime 100% Home Office.",
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
            if kwargs.get("search_term") == collect_linkedin.REMOTE_SEARCH_TERM:
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
            self.assertEqual(calls[1]["search_term"], collect_linkedin.REMOTE_SEARCH_TERM)
            self.assertTrue(all("easy_apply" not in call for call in calls))

            # Valida presença dos três modelos de trabalho: presencial, híbrido e remoto
            types = {r["workplaceType"] for r in results}
            self.assertEqual(types, {"on-site", "hybrid", "remote"})

            with open(tmp_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["count"], 3)
            self.assertEqual(saved["filter"], "public_brazil")
            self.assertEqual(len(saved["coverage"]), 2)
            self.assertFalse(any(item["limit_reached"] for item in saved["coverage"]))
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
                "company": f"Empresa {index}",
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
                [100, 100, 5],
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_pagination_reports_when_result_cap_is_reached(self):
        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        records = [
            {
                "id": f"li-{index}",
                "job_url": f"https://www.linkedin.com/jobs/view/{index}",
                "title": f"Vaga {index}",
                "company": "Empresa Teste",
            }
            for index in range(200)
        ]

        def mock_scrape(**kwargs):
            start = kwargs["offset"]
            size = kwargs["results_wanted"]
            return MockDataFrame(records[start : start + size])

        coverage = {}
        with patch.object(collect_linkedin, "scrape_jobs", side_effect=mock_scrape):
            rows = collect_linkedin._scrape_jobs_in_pages(
                results_limit=200, coverage=coverage, site_name=["linkedin"]
            )

        self.assertEqual(len(rows), 200)
        self.assertEqual(coverage["returned"], 200)
        self.assertTrue(coverage["limit_reached"])
        self.assertFalse(coverage["source_exhausted"])

    def test_scrape_jobs_in_pages_continues_when_batch_smaller_than_results_wanted(self):
        records = [
            {
                "id": f"li-{index}",
                "job_url": f"https://www.linkedin.com/jobs/view/{index}",
                "title": f"Vaga {index}",
                "company": "Empresa Teste",
            }
            for index in range(118)
        ]

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(**kwargs):
            offset = kwargs["offset"]
            if offset == 0:
                return MockDataFrame(records[:59])
            elif offset == 100:
                return MockDataFrame(records[59:118])
            return MockDataFrame([])

        coverage = {}
        with patch.object(
            collect_linkedin, "scrape_jobs", side_effect=mock_scrape
        ), patch.object(collect_linkedin.time, "sleep"):
            rows = collect_linkedin._scrape_jobs_in_pages(
                results_limit=300, coverage=coverage, site_name=["linkedin"]
            )

        self.assertEqual(len(rows), 118)
        self.assertEqual(coverage["returned"], 118)
        self.assertTrue(coverage["source_exhausted"])

    def test_query_limit_clamps_at_jobspy_max_and_reports_requested_effective(self):
        records = [
            {
                "id": f"li-{index}",
                "job_url": f"https://www.linkedin.com/jobs/view/{index}",
                "title": f"Vaga {index}",
                "company": "Empresa Teste",
            }
            for index in range(1000)
        ]

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        calls = []

        def mock_scrape(**kwargs):
            calls.append(dict(kwargs))
            start = kwargs["offset"]
            size = kwargs["results_wanted"]
            return MockDataFrame(records[start : start + size])

        coverage = {}
        with patch.object(
            collect_linkedin, "scrape_jobs", side_effect=mock_scrape
        ), patch.object(collect_linkedin.time, "sleep"):
            rows = collect_linkedin._scrape_jobs_in_pages(
                results_limit=1200, coverage=coverage, site_name=["linkedin"]
            )

        self.assertEqual(len(rows), 1000)
        self.assertEqual(coverage["requested_limit"], 1200)
        self.assertEqual(coverage["effective_limit"], 1000)
        self.assertTrue(coverage["clamped_by_query_limit"])
        self.assertFalse(coverage["clamped_by_pass_budget"])
        self.assertEqual([call["offset"] for call in calls], list(range(0, 1000, 100)))
        self.assertTrue(all(call["results_wanted"] <= 100 for call in calls))

    def test_aggregate_cap_applies_to_open_general_and_remote_dispatch_limits(self):
        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(**kwargs):
            prefix = (
                "R"
                if kwargs.get("search_term") == collect_linkedin.REMOTE_SEARCH_TERM
                else "G"
            )
            start = kwargs["offset"]
            size = kwargs["results_wanted"]
            return MockDataFrame([
                {
                    "id": f"li-{prefix}{index}",
                    "job_url": f"https://www.linkedin.com/jobs/view/{prefix}{index}",
                    "title": f"Vaga {prefix}{index}",
                    "company": f"Empresa {prefix}{index}",
                    "location": "Brazil",
                    "date_posted": date.today().isoformat(),
                }
                for index in range(start, start + size)
            ])

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            summary_path = Path(temporary) / "summary.md"
            summary_path.write_text("", encoding="utf-8")
            with patch.dict(
                os.environ, {"GITHUB_STEP_SUMMARY": str(summary_path)}, clear=False
            ), patch.object(
                collect_linkedin, "scrape_jobs", side_effect=mock_scrape
            ), patch.object(collect_linkedin.time, "sleep"), patch(
                "builtins.print"
            ) as log_print:
                rows = collect_linkedin.collect_linkedin(
                    results_limit=1200,
                    remote_results_limit=1200,
                    out_path=str(snapshot_path),
                )

            limit_log = "\n".join(
                str(call.args[0])
                for call in log_print.call_args_list
                if call.args
            )
            self.assertIn("Busca 'general': solicitado=1200, efetivo=1000", limit_log)
            self.assertIn("Busca 'remote_keyword_candidates': solicitado=1200, efetivo=200", limit_log)
            self.assertIn("orçamento da busca (200)", limit_log)

            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 1200)
            self.assertEqual(payload["count"], 1200)
            self.assertEqual(payload["limits"]["max_results_per_query"], 1000)
            self.assertEqual(payload["limits"]["max_unique_per_run"], 1200)
            self.assertEqual(
                [(item["requested_limit"], item["effective_limit"])
                 for item in payload["coverage"]],
                [(1200, 1000), (1200, 200)],
            )
            self.assertTrue(payload["coverage"][0]["clamped_by_query_limit"])
            self.assertTrue(payload["coverage"][1]["clamped_by_pass_budget"])
            self.assertEqual(
                [item["added_unique"] for item in payload["coverage"]], [1000, 200]
            )
            # Elimination of wasted downloads: 0 records skipped beyond the aggregate cap!
            self.assertEqual(
                [item["skipped_after_unique_cap"] for item in payload["coverage"]],
                [0, 0],
            )
            self.assertEqual(
                len({job["native_id"] for job in payload["jobs"]}), 1200
            )
            summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("Easy Apply 0", summary)
            self.assertIn("externa 0", summary)
            self.assertIn("desconhecida 1200", summary)

    def test_remote_pass_budget_is_applied_after_cross_pass_deduplication(self):
        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(**kwargs):
            start = kwargs["offset"]
            size = kwargs["results_wanted"]
            if kwargs.get("search_term") == collect_linkedin.REMOTE_SEARCH_TERM:
                rows = []
                for index in range(start, start + size):
                    job_id = (
                        4470000000 + index
                        if index < 288
                        else 4480000000 + index
                    )
                    rows.append({
                        "id": str(job_id),
                        "job_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                        "title": f"Vaga {job_id}",
                        "company": f"Empresa {job_id}",
                        "location": "Brazil",
                        "date_posted": date.today().isoformat(),
                    })
                return MockDataFrame(rows)

            end = min(start + size, 290)
            rows = [
                {
                    "id": str(4470000000 + index),
                    "job_url": f"https://www.linkedin.com/jobs/view/{4470000000 + index}",
                    "title": f"Vaga {4470000000 + index}",
                    "company": f"Empresa {4470000000 + index}",
                    "location": "Brazil",
                    "date_posted": date.today().isoformat(),
                }
                for index in range(start, end)
            ]
            return MockDataFrame(rows)

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", side_effect=mock_scrape
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    results_limit=1200,
                    remote_results_limit=1200,
                    out_path=str(snapshot_path),
                )

            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 912)
            self.assertEqual(payload["count"], 912)
            self.assertEqual(
                [item["returned"] for item in payload["coverage"]],
                [290, 910],
            )
            self.assertEqual(
                [item["remaining_unique_before_pass"] for item in payload["coverage"]],
                [1200, 910],
            )
            self.assertEqual(
                [item["duplicates"] for item in payload["coverage"]],
                [0, 288],
            )
            self.assertEqual(
                [item["added_unique"] for item in payload["coverage"]],
                [290, 622],
            )
            self.assertEqual(
                [item["effective_limit"] for item in payload["coverage"]],
                [1000, 910],
            )
            self.assertTrue(payload["coverage"][1]["clamped_by_pass_budget"])
            self.assertFalse(payload["coverage"][1]["unique_cap_reached"])

    def test_aggregate_cap_also_applies_across_search_terms_and_deduplicates(self):
        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(**kwargs):
            term = kwargs["search_term"]
            start = kwargs["offset"]
            size = kwargs["results_wanted"]
            base = 1000 if term == "last" else 0
            return MockDataFrame([
                {
                    "id": f"li-{base + index}",
                    "job_url": f"https://www.linkedin.com/jobs/view/{base + index}",
                    "title": f"Vaga {base + index}",
                    "company": f"Empresa {base + index}",
                    "location": "Brazil",
                    "date_posted": date.today().isoformat(),
                }
                for index in range(start, start + size)
            ])

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", side_effect=mock_scrape
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    terms=["first", "duplicates", "last"],
                    results_limit=1200,
                    remote_results_limit=1200,
                    out_path=str(snapshot_path),
                )

            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 1200)
            self.assertEqual(payload["count"], 1200)
            self.assertEqual(
                [item["effective_limit"] for item in payload["coverage"]],
                [1000, 1000, 1000],
            )
            self.assertEqual(
                len({job["native_id"] for job in payload["jobs"]}), 1200
            )

    def test_incomplete_linkedin_pass_preserves_previous_snapshot(self):
        for failed_pass in ("general", "remote"):
            with self.subTest(failed_pass=failed_pass):
                with tempfile.TemporaryDirectory() as temporary:
                    snapshot_path = Path(temporary) / "linkedin.json"
                    previous_snapshot = {
                        "schema_version": 1,
                        "source": "linkedin",
                        "filter": "easy_apply",
                        "generated_at": "2026-11-03T00:00:00+00:00",
                        "count": 1,
                        "jobs": [{"native_id": "li-previous"}],
                    }
                    snapshot_path.write_text(
                        json.dumps(previous_snapshot), encoding="utf-8"
                    )

                    class MockDataFrame(list):
                        @property
                        def empty(self):
                            return len(self) == 0

                        def to_dict(self, orient="records"):
                            return list(self)

                    record = {
                        "id": "li-123",
                        "job_url": "https://www.linkedin.com/jobs/view/123",
                        "title": "Pessoa Desenvolvedora",
                        "company": "Empresa Teste",
                        "location": "Brazil",
                        "date_posted": date.today().isoformat(),
                    }

                    def mock_scrape(*args, **kwargs):
                        current_pass = (
                            "remote"
                            if kwargs.get("search_term") == collect_linkedin.REMOTE_SEARCH_TERM
                            else "general"
                        )
                        if current_pass == failed_pass:
                            raise RuntimeError("temporary LinkedIn failure")
                        return MockDataFrame([record])

                    with patch.object(
                        collect_linkedin, "scrape_jobs", side_effect=mock_scrape
                    ), patch.object(collect_linkedin.time, "sleep"):
                        with self.assertRaisesRegex(RuntimeError, "incompleta"):
                            collect_linkedin.collect_linkedin(
                                results_limit=10,
                                remote_results_limit=5,
                                out_path=str(snapshot_path),
                            )

                    self.assertEqual(
                        json.loads(snapshot_path.read_text(encoding="utf-8")),
                        previous_snapshot,
                    )

    def test_normalize_accepts_job_within_two_month_window(self):
        today = date.today()
        row = linkedin._normalize(
            self._payload()["jobs"][0]
            | {"publishedAt": (today - timedelta(days=60)).isoformat()},
            today=today,
        )
        self.assertIsNotNone(row)

    def test_phase2_skipped_when_phase1_hits_aggregate_cap(self):
        """Se a Fase 1 já atinge o teto de únicos (remaining <= 0), a Fase 2 não é disparada."""
        calls = []

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(**kwargs):
            calls.append(dict(kwargs))
            start = kwargs["offset"]
            size = kwargs["results_wanted"]
            return MockDataFrame([
                {
                    "id": f"li-{start + index}",
                    "job_url": f"https://www.linkedin.com/jobs/view/{start + index}",
                    "title": f"Vaga {start + index}",
                    "company": f"Empresa {start + index}",
                    "location": "Brazil",
                    "date_posted": date.today().isoformat(),
                }
                for index in range(size)
            ])

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "MAX_UNIQUE_RESULTS_PER_RUN", 1000
            ), patch.object(
                collect_linkedin, "scrape_jobs", side_effect=mock_scrape
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    results_limit=1000,
                    remote_results_limit=1200,
                    out_path=str(snapshot_path),
                )

            # Fase 1 coletou 1000 vagas, atingindo o teto de 1000. Fase 2 NÃO foi disparada.
            self.assertEqual(len(rows), 1000)
            self.assertTrue(all(call.get("search_term") is None for call in calls))

    def test_application_parser_ignores_similar_jobs_and_carousels(self):
        """Parser ignora botões/links em seções de vagas similares e rodapé, priorizando top card."""
        html_with_similar = """
        <div class="top-card-layout">
            <h1 class="top-card-layout__title">Engenheiro de Software</h1>
            <a class="apply-button" href="https://external-company.com/apply/123">Candidatar-se no site da empresa</a>
        </div>
        <div class="similar-jobs">
            <div class="similar-jobs__item">
                <button class="jobs-apply-button">Candidatura simplificada</button>
            </div>
        </div>
        <div class="jobs-carousel">
            <button>Easy Apply</button>
        </div>
        """
        evidence = collect_linkedin._extract_application_evidence_from_html(html_with_similar)
        self.assertEqual(evidence, ("external", True, "external_apply_marker"))

        html_with_easy_apply_top_card = """
        <section class="top-card-layout">
            <button class="jobs-apply-button">Candidatura simplificada</button>
        </section>
        <section class="recommended-jobs">
            <a href="https://other.com/apply">Apply externally</a>
        </section>
        """
        evidence2 = collect_linkedin._extract_application_evidence_from_html(html_with_easy_apply_top_card)
        self.assertEqual(evidence2, ("easy_apply", True, "easy_apply_badge"))

        html_with_input_submit = """
        <div class="top-card-layout">
            <input type="submit" class="jobs-apply-button" value="Candidatura simplificada" />
        </div>
        """
        evidence3 = collect_linkedin._extract_application_evidence_from_html(html_with_input_submit)
        self.assertEqual(evidence3, ("easy_apply", True, "easy_apply_badge"))

    def test_linkedin_injects_brazil_geo_id_in_search_params(self):
        """LinkedIn scraper injeta geoId=106057199 para consultas no Brasil."""
        try:
            from jobspy.linkedin import LinkedIn
        except ImportError:
            self.skipTest("jobspy não instalado neste ambiente")
            return

        mock_input = MagicMock()
        mock_input.search_term = "python"
        mock_input.location = "Brazil"
        mock_input.distance = 50
        mock_input.easy_apply = True
        mock_input.linkedin_company_ids = None
        mock_input.hours_old = 24

        scraper = LinkedIn()
        scraper.scraper_input = mock_input
        params = scraper._search_params()
        self.assertEqual(params.get("geoId"), collect_linkedin.LINKEDIN_BRAZIL_GEO_ID)
        self.assertEqual(params.get("geoId"), "106057199")
        self.assertEqual(params.get("f_AL"), "true")

    def test_easy_apply_f_al_sets_query_filter_provenance(self):
        """Quando o filtro easy_apply está ativo, o snapshot recebe filter='easy_apply' e evidência query_filter_f_AL."""
        record = {
            "id": "li-8888",
            "job_url": "https://www.linkedin.com/jobs/view/8888",
            "title": "Analista de Dados",
            "company": "Empresa",
            "location": "São Paulo, São Paulo, Brazil",
            "date_posted": date.today().isoformat(),
        }

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        scrape_calls = []

        def mock_scrape(**kwargs):
            scrape_calls.append(dict(kwargs))
            return MockDataFrame([record])

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", side_effect=mock_scrape
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    results_limit=10,
                    remote_results_limit=0,
                    include_remote_pass=False,
                    easy_apply=True,
                    out_path=str(snapshot_path),
                )

            self.assertEqual(len(rows), 1)
            self.assertTrue(scrape_calls[0].get("easy_apply"))

            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["filter"], "easy_apply")
            self.assertTrue(payload["limits"]["easy_apply"])

            target_job = payload["jobs"][0]
            self.assertEqual(target_job["applicationType"], "easy_apply")
            self.assertTrue(target_job["applicationVerified"])
            self.assertEqual(target_job["applicationEvidence"], "query_filter_f_AL")

    def test_duplicate_job_enriches_application_evidence_when_higher_priority(self):
        """Varredura subsequente enriquece evidência de candidatura de vaga duplicada."""
        record = {
            "id": "li-9999",
            "job_url": "https://www.linkedin.com/jobs/view/9999",
            "title": "Analista",
            "company": "Empresa",
            "location": "Brazil",
            "date_posted": date.today().isoformat(),
        }

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(**kwargs):
            return MockDataFrame([record])

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", side_effect=mock_scrape
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    terms=["first", "second"],
                    results_limit=10,
                    remote_results_limit=0,
                    include_remote_pass=False,
                    easy_apply=True,
                    out_path=str(snapshot_path),
                )

            self.assertEqual(len(rows), 1)
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["jobs"][0]["applicationType"], "easy_apply")
            self.assertEqual(payload["jobs"][0]["applicationEvidence"], "query_filter_f_AL")

    def test_extracts_easy_apply_from_guest_tracking_control_name(self):
        """No HTML público guest, Easy Apply usa tracking-control-name onsite mesmo com label 'Candidatar-se'."""
        snippets = (
            '<a class="apply-button" data-tracking-control-name="public_jobs_apply-link-onsite" '
            'href="https://www.linkedin.com/jobs/view/4484683364/?trk=public_jobs_apply-link-onsite">Candidatar-se</a>',
            '<button class="apply-button" data-tracking-control-name="public_jobs_apply-link-simple_onsite">Apply</button>',
            '<button data-control-name="public_jobs_apply-link-onsite">Candidatar-se</button>',
        )
        for html in snippets:
            with self.subTest(html=html):
                self.assertEqual(
                    collect_linkedin._extract_application_evidence_from_html(html),
                    ("easy_apply", True, "easy_apply_badge"),
                )

    def test_extracts_external_apply_from_guest_attributes(self):
        """No HTML público guest, candidatura externa usa apply-link-offsite, data-modal ou icon SVG offsite."""
        snippets = (
            '<button class="apply-button" data-tracking-control-name="public_jobs_apply-link-offsite" '
            'data-modal="job-details-topcard-apply-modal">Candidatar-se <icon data-svg-class-name="apply-button__offsite-apply-icon-svg"></icon></button>',
            '<button data-modal="job-details-topcard-apply-modal">Candidatar-se</button>',
            '<button class="apply-button">Candidatar-se <icon data-svg-class-name="apply-button__offsite-apply-icon-svg"></icon></button>',
            '<a class="apply-button" data-tracking-control-name="public_jobs_apply-link-offsite" href="https://www.linkedin.com/jobs/view/123">Apply</a>',
        )
        for html in snippets:
            with self.subTest(html=html):
                self.assertEqual(
                    collect_linkedin._extract_application_evidence_from_html(html),
                    ("external", True, "external_apply_marker"),
                )

    def test_max_jobs_per_company_caps_aggregators(self):
        """O limite de vagas por anunciante/empresa evita monopólio de agregadores."""
        jobbol_records = [
            {
                "id": f"li-jobbol-{i}",
                "job_url": f"https://www.linkedin.com/jobs/view/1000{i}",
                "title": f"Operador de Logística {i}",
                "company": "Jobbol",
                "location": "São Paulo, Brazil",
                "date_posted": date.today().isoformat(),
            }
            for i in range(40)
        ]
        acme_records = [
            {
                "id": f"li-acme-{i}",
                "job_url": f"https://www.linkedin.com/jobs/view/2000{i}",
                "title": f"Engenheiro de Software {i}",
                "company": "Acme",
                "location": "São Paulo, Brazil",
                "date_posted": date.today().isoformat(),
            }
            for i in range(10)
        ]

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", return_value=MockDataFrame(jobbol_records + acme_records)
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    results_limit=100,
                    remote_results_limit=0,
                    include_remote_pass=False,
                    max_jobs_per_company=25,
                    out_path=str(snapshot_path),
                )

            # 25 vagas da Jobbol (15 podadas pelo teto) + 10 da Acme = 35 vagas totais
            self.assertEqual(len(rows), 35)
            jobbol_count = sum(1 for r in rows if r["company"] == "Jobbol")
            acme_count = sum(1 for r in rows if r["company"] == "Acme")
            self.assertEqual(jobbol_count, 25)
            self.assertEqual(acme_count, 10)

            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["coverage"][0]["skipped_company_cap"], 15)
            self.assertEqual(payload["limits"]["max_jobs_per_company"], 25)

    def test_english_workplace_patterns_and_benefit_resilience(self):
        """Padrões em inglês e benefícios (vale-transporte) não anulam trabalho remoto explícito."""
        collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE.clear()
        base_job = {
            "company": "CodeSpar",
            "location": "Brazil",
            "date_posted": date.today().isoformat(),
        }

        cases = [
            (
                "Deployment Engineer. Remote, full-time, Brazil. Join our team.",
                "remote",
            ),
            (
                "Senior Backend Engineer. Remote flexibility and competitive compensation.",
                "remote",
            ),
            (
                "Product Manager. Distributed team, work from anywhere in Brazil.",
                "remote",
            ),
            (
                "Engenheiro de Software. Regime 100% Home Office. "
                "Benefícios: Vale-transporte para visitas ocasionais à sede, auxílio home office, plano de saúde.",
                "remote",
            ),
            (
                "Analista de Sistemas. Oferecemos auxílio home office integral para todos os colaboradores.",
                "remote",
            ),
        ]

        for desc, expected in cases:
            with self.subTest(desc=desc[:40]):
                norm = collect_linkedin.normalize_linkedin_job(base_job | {
                    "job_url": "https://www.linkedin.com/jobs/view/99999",
                    "title": "Vaga Teste",
                    "description": desc,
                })
                self.assertEqual(norm["workplaceType"], expected)
                self.assertTrue(norm["workplaceVerified"])
                self.assertEqual(norm["workplaceEvidence"], "description_explicit")

    def test_priority_terms_collection_pass(self):
        """Execução com priority_terms realiza buscas direcionadas para empresas/termos prioritários."""
        scrape_calls = []

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(**kwargs):
            scrape_calls.append(dict(kwargs))
            term = kwargs.get("search_term")
            company = "Tech Corp"
            return MockDataFrame([
                {
                    "id": f"li-{term or 'general'}-1",
                    "job_url": f"https://www.linkedin.com/jobs/view/{len(scrape_calls)}",
                    "title": f"Vaga {term or 'Geral'}",
                    "company": company,
                    "location": "Brazil",
                    "date_posted": date.today().isoformat(),
                }
            ])

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", side_effect=mock_scrape
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    terms=None,
                    priority_terms=["Software", "Frontend"],
                    results_limit=10,
                    remote_results_limit=5,
                    out_path=str(snapshot_path),
                )

            searched_terms = [call.get("search_term") for call in scrape_calls]
            self.assertIn("Software", searched_terms)
            self.assertIn("Frontend", searched_terms)
            self.assertIn(None, searched_terms)
            self.assertIn(collect_linkedin.REMOTE_SEARCH_TERM, searched_terms)

            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            pass_names = [cov["name"] for cov in payload["coverage"]]
            self.assertIn("general", pass_names)
            self.assertIn("prioritario:Software", pass_names)
            self.assertIn("prioritario:Frontend", pass_names)
            self.assertIn("remote_keyword_candidates", pass_names)

    def test_priority_terms_run_before_general_sweep(self):
        """Termos prioritários executam ANTES da varredura geral para evitar sufocamento de vagas qualificadas."""
        scrape_calls = []

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(**kwargs):
            scrape_calls.append(dict(kwargs))
            term = kwargs.get("search_term")
            return MockDataFrame([
                {
                    "id": f"li-{term or 'general'}-{len(scrape_calls)}",
                    "job_url": f"https://www.linkedin.com/jobs/view/{len(scrape_calls)}",
                    "title": f"Vaga {term or 'Geral'}",
                    "company": f"Empresa {term or 'Geral'}",
                    "location": "Brazil",
                    "date_posted": date.today().isoformat(),
                }
            ])

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", side_effect=mock_scrape
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    terms=None,
                    priority_terms=["Software", "Frontend"],
                    results_limit=10,
                    remote_results_limit=5,
                    out_path=str(snapshot_path),
                )

            # Os dois primeiros scrapes DEVEM ser os termos prioritários (Software e Frontend)
            self.assertEqual(scrape_calls[0].get("search_term"), "Software")
            self.assertEqual(scrape_calls[1].get("search_term"), "Frontend")
            self.assertIsNone(scrape_calls[2].get("search_term"))  # general
            self.assertEqual(scrape_calls[3].get("search_term"), collect_linkedin.REMOTE_SEARCH_TERM)

    def test_english_workplace_patterns_comprehensive(self):
        """Classifica padrões em inglês como '100% remote', 'work model: remote', etc."""
        collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE.clear()
        base_job = {
            "company": "TechGlobal",
            "location": "Brazil",
            "date_posted": date.today().isoformat(),
        }

        cases = [
            ("This is a 100% remote role for engineers in Brazil.", "remote"),
            ("Work model: remote. We provide full equipment.", "remote"),
            ("Work mode: remote.", "remote"),
            ("We have a remote position in Brazil open immediately.", "remote"),
            ("Remote opportunity for senior developers.", "remote"),
            ("Job type: 100% remote.", "remote"),
            ("Work model: hybrid. 2 days office, 3 days home.", "hybrid"),
            ("100% híbrido com flexibilidade de horário.", "hybrid"),
            ("Hybrid role based in São Paulo.", "hybrid"),
            ("Work model: on-site. Presence required every day.", "on-site"),
            ("100% on-site presence mandatory.", "on-site"),
            ("On-site position in our headquarters.", "on-site"),
        ]

        for desc, expected in cases:
            with self.subTest(desc=desc[:40]):
                norm = collect_linkedin.normalize_linkedin_job(base_job | {
                    "job_url": "https://www.linkedin.com/jobs/view/88888",
                    "title": "Vaga Internacional",
                    "description": desc,
                })
                self.assertEqual(norm["workplaceType"], expected)
                self.assertTrue(norm["workplaceVerified"])
                self.assertEqual(norm["workplaceEvidence"], "description_explicit")

    def test_anonymous_company_exemptions_from_cap(self):
        """Postagens com 'Confidencial', 'Empresa Confidencial' ou não informadas não são sufocadas pelo teto por empresa."""
        anonymous_records = [
            {
                "id": f"li-anon-{i}",
                "job_url": f"https://www.linkedin.com/jobs/view/3000{i}",
                "title": f"Vaga Confidencial {i}",
                "company": "Confidencial" if i % 2 == 0 else "Empresa Confidencial",
                "location": "São Paulo, Brazil",
                "date_posted": date.today().isoformat(),
            }
            for i in range(35)
        ]

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", return_value=MockDataFrame(anonymous_records)
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    results_limit=50,
                    remote_results_limit=0,
                    include_remote_pass=False,
                    max_jobs_per_company=25,
                    out_path=str(snapshot_path),
                )

            # Todas as 35 vagas devem ser aceitas porque 'Confidencial' é isento do teto
            self.assertEqual(len(rows), 35)

    def test_apply_button_precedence_over_other_top_card_links(self):
        """Botão de apply explícito prevalece sobre links auxiliares do top-card, evitando sinais conflitantes."""
        html = (
            '<div class="top-card-layout">'
            '  <a class="topcard__org-name-link" href="https://company.com.br/apply">Visite nossa empresa</a>'
            '  <button class="apply-button apply-button--default" data-tracking-control-name="public_jobs_apply-link-onsite">Candidatar-se</button>'
            '</div>'
        )
        self.assertEqual(
            collect_linkedin._extract_application_evidence_from_html(html),
            ("easy_apply", True, "easy_apply_badge"),
        )

    def test_sources_linkedin_accepts_query_filter_f_wt_evidence(self):
        """jobs-dashboard/sources/linkedin.py aceita query_filter_f_WT para remote e hybrid."""
        for modality in ("remote", "hybrid"):
            with self.subTest(modality=modality):
                path = self._write_snapshot(
                    self._payload(
                        job={
                            "workplaceType": modality,
                            "workplaceVerified": True,
                            "workplaceEvidence": "query_filter_f_WT",
                        }
                    )
                )
                try:
                    with patch.dict(
                        os.environ,
                        {"LINKEDIN_SNAPSHOT_PATH": str(path)},
                        clear=False,
                    ):
                        rows = linkedin.fetch()
                finally:
                    path.unlink(missing_ok=True)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["work_model"], modality)

    def test_sources_linkedin_rejects_untrusted_workplace_evidence(self):
        """Evidence desconhecida ou não confiável não valida a modalidade."""
        path = self._write_snapshot(
            self._payload(
                job={
                    "workplaceType": "remote",
                    "workplaceVerified": True,
                    "workplaceEvidence": "untrusted_keyword",
                }
            )
        )
        try:
            with patch.dict(
                os.environ,
                {"LINKEDIN_SNAPSHOT_PATH": str(path)},
                clear=False,
            ):
                rows = linkedin.fetch()
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["work_model"], "")

    def test_collect_linkedin_normalize_with_query_filter_workplace(self):
        """normalize_linkedin_job gera query_filter_f_WT e prioridade 20."""
        record = {
            "id": "li-8888",
            "job_url": "https://www.linkedin.com/jobs/view/8888",
            "title": "Desenvolvedor Backend",
            "company": "Empresa Tech",
            "location": "São Paulo, Brazil",
            "date_posted": date.today().isoformat(),
        }
        collect_linkedin.CAPTURED_LINKEDIN_WORKPLACE.clear()
        normalized = collect_linkedin.normalize_linkedin_job(
            record, query_filter_workplace_type="remote"
        )
        self.assertEqual(normalized["workplaceType"], "remote")
        self.assertTrue(normalized["workplaceVerified"])
        self.assertEqual(normalized["workplaceEvidence"], "query_filter_f_WT")

    def test_collect_linkedin_evidence_priority_hierarchy(self):
        """Verifica que WORKPLACE_EVIDENCE_PRIORITY posiciona query_filter_f_WT (20) acima de description_explicit (10) e abaixo de manual_override (30)."""
        self.assertEqual(collect_linkedin.WORKPLACE_EVIDENCE_PRIORITY["linkedin_badge"], 40)
        self.assertEqual(collect_linkedin.WORKPLACE_EVIDENCE_PRIORITY["manual_override"], 30)
        self.assertEqual(collect_linkedin.WORKPLACE_EVIDENCE_PRIORITY["query_filter_f_WT"], 20)
        self.assertEqual(collect_linkedin.WORKPLACE_EVIDENCE_PRIORITY["description_explicit"], 10)

    def test_collect_linkedin_search_params_injection(self):
        """Parâmetros de busca injetam f_E, f_TPR, sortBy, f_AL e f_WT conforme especificado."""
        params = collect_linkedin.build_linkedin_search_params(
            location="Brazil", easy_apply=True, f_wt="2"
        )
        self.assertEqual(params.get("f_E"), "2,3,4")
        self.assertEqual(params.get("f_TPR"), "r604800")
        self.assertEqual(params.get("sortBy"), "DD")
        self.assertEqual(params.get("f_AL"), "true")
        self.assertEqual(params.get("f_WT"), "2")
        self.assertEqual(params.get("geoId"), collect_linkedin.LINKEDIN_BRAZIL_GEO_ID)

        # Teste híbrido f_WT=3
        params_hybrid = collect_linkedin.build_linkedin_search_params(
            location="Brazil", easy_apply=False, f_wt="3"
        )
        self.assertEqual(params_hybrid.get("f_WT"), "3")
        self.assertNotIn("f_AL", params_hybrid)

    def test_collect_linkedin_default_priority_terms_tech_clusters(self):
        """DEFAULT_PRIORITY_TERMS não contém Flash e define clusters de tecnologia."""
        self.assertNotIn("Flash", collect_linkedin.DEFAULT_PRIORITY_TERMS)
        expected_clusters = ("Software", "Frontend", "Dados", "Produto", "DevOps", "QA")
        for cluster in expected_clusters:
            self.assertIn(cluster, collect_linkedin.DEFAULT_PRIORITY_TERMS)

    def test_collect_linkedin_runs_hybrid_pass_when_enabled(self):
        """Quando include_hybrid_pass=True, executa passe separado para híbrido com f_WT=3."""
        scrape_calls = []

        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        def mock_scrape(**kwargs):
            scrape_calls.append(dict(kwargs))
            return MockDataFrame([
                {
                    "id": f"li-{len(scrape_calls)}",
                    "job_url": f"https://www.linkedin.com/jobs/view/{len(scrape_calls)}",
                    "title": f"Vaga {len(scrape_calls)}",
                    "company": "Tech Corp",
                    "location": "Brazil",
                    "date_posted": date.today().isoformat(),
                }
            ])

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", side_effect=mock_scrape
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    terms=None,
                    results_limit=10,
                    remote_results_limit=5,
                    include_remote_pass=True,
                    include_hybrid_pass=True,
                    hybrid_results_limit=5,
                    out_path=str(snapshot_path),
                )

            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            pass_names = [cov["name"] for cov in payload["coverage"]]
            self.assertIn("general", pass_names)
            self.assertIn("remote_keyword_candidates", pass_names)
            self.assertIn("hybrid_pass", pass_names)
            self.assertEqual(payload["limits"]["requested_hybrid"], 5)

    def test_inject_linkedin_search_params_cleans_inactive_filters(self):
        """_inject_linkedin_search_params injeta filtros canônicos e remove chaves inativas."""
        params = {"location": "Brazil", "f_WT": "99", "f_AL": "true"}
        collect_linkedin._CURRENT_PASS_F_WT = None
        collect_linkedin._CURRENT_EASY_APPLY = False
        injected = collect_linkedin._inject_linkedin_search_params(dict(params))
        self.assertEqual(injected["f_E"], "2,3,4")
        self.assertEqual(injected["f_TPR"], "r604800")
        self.assertEqual(injected["sortBy"], "DD")
        self.assertEqual(injected["geoId"], collect_linkedin.LINKEDIN_BRAZIL_GEO_ID)
        self.assertNotIn("f_WT", injected)
        self.assertNotIn("f_AL", injected)

        # Ativa f_WT=3 e f_AL
        collect_linkedin._CURRENT_PASS_F_WT = "3"
        collect_linkedin._CURRENT_EASY_APPLY = True
        try:
            injected_active = collect_linkedin._inject_linkedin_search_params(dict(params))
            self.assertEqual(injected_active["f_WT"], "3")
            self.assertEqual(injected_active["f_AL"], "true")
        finally:
            collect_linkedin._CURRENT_PASS_F_WT = None
            collect_linkedin._CURRENT_EASY_APPLY = False

    def test_collect_linkedin_hybrid_pass_produces_verified_hybrid_jobs(self):
        """Passe híbrido produz vagas com modalidade 'hybrid' e evidência 'query_filter_f_WT'."""
        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        raw_job = {
            "id": "li-hybrid-777",
            "job_url": "https://www.linkedin.com/jobs/view/777",
            "title": "Engenheiro de Dados",
            "company": "Data Corp",
            "location": "São Paulo, Brazil",
            "date_posted": date.today().isoformat(),
        }

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            with patch.object(
                collect_linkedin, "scrape_jobs", return_value=MockDataFrame([raw_job])
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    terms=None,
                    results_limit=0,
                    remote_results_limit=0,
                    include_remote_pass=False,
                    include_hybrid_pass=True,
                    hybrid_results_limit=10,
                    out_path=str(snapshot_path),
                )

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["workplaceType"], "hybrid")
            self.assertTrue(row["workplaceVerified"])
            self.assertEqual(row["workplaceEvidence"], "query_filter_f_WT")

    def test_collect_linkedin_duplicate_enrichment_from_hybrid_pass(self):
        """Vaga sem modalidade na busca geral é enriquecida quando reencontrada no passe híbrido."""
        class MockDataFrame(list):
            @property
            def empty(self):
                return len(self) == 0

            def to_dict(self, orient="records"):
                return list(self)

        raw_job = {
            "id": "li-shared-555",
            "job_url": "https://www.linkedin.com/jobs/view/555",
            "title": "Desenvolvedor Frontend",
            "company": "Front Corp",
            "location": "Brazil",
            "date_posted": date.today().isoformat(),
        }

        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "linkedin.json"
            # O mock retorna a mesma vaga em ambas as fases (geral e híbrida)
            with patch.object(
                collect_linkedin, "scrape_jobs", return_value=MockDataFrame([raw_job])
            ), patch.object(collect_linkedin.time, "sleep"):
                rows = collect_linkedin.collect_linkedin(
                    terms=None,
                    results_limit=1,
                    remote_results_limit=0,
                    include_remote_pass=False,
                    include_hybrid_pass=True,
                    hybrid_results_limit=1,
                    out_path=str(snapshot_path),
                )

            self.assertEqual(len(rows), 1)
            enriched = rows[0]
            self.assertEqual(enriched["workplaceType"], "hybrid")
            self.assertTrue(enriched["workplaceVerified"])
            self.assertEqual(enriched["workplaceEvidence"], "query_filter_f_WT")


if __name__ == "__main__":
    unittest.main()
