# -*- coding: utf-8 -*-
"""Regression tests for the Spassu, InfoVagas and Experian adapters."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import experian, quickin, spassu  # noqa: E402
import pipeline  # noqa: E402


class SpassuTests(unittest.TestCase):
    def test_catalog_links_extract_zoho_detail_ids(self):
        markup = """
        <a href="/jobs/Careers/678402000031758219/Desenvolvedor">
          Desenvolvedor
        </a>
        <a href="/jobs/Careers">Página inicial</a>
        """
        links = spassu._catalog_links(markup)
        self.assertEqual(len(links), 1)
        self.assertEqual(
            links[0][0],
            "https://spassu.zohorecruit.com/jobs/Careers/678402000031758219/Desenvolvedor",
        )

    def test_schema_job_posting_preserves_remote_location(self):
        posting = {
            "@type": "JobPosting",
            "title": "Desenvolvedor ABAP",
            "datePosted": "2026-08-20",
            "employmentType": "FULL_TIME",
            "jobLocationType": "TELECOMMUTE",
            "hiringOrganization": {"name": "Spassu"},
            "jobLocation": {"address": {
                "addressLocality": "Brasil",
                "addressCountry": "BR",
            }},
            "description": "Desenvolvimento de sistemas.",
        }
        markup = (
            '<h1>Desenvolvedor ABAP</h1>'
            '<script type="application/ld+json">'
            + json.dumps(posting)
            + "</script>"
        )
        row = spassu._normalize(
            "https://spassu.zohorecruit.com/jobs/Careers/123/Desenvolvedor",
            markup,
        )
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brasil")
        self.assertEqual(row["published_date"], "2026-08-20")


class QuickinTests(unittest.TestCase):
    def test_catalog_page_separates_vacancies_from_pagination(self):
        markup = """
        <a href="/infovagas/jobs/69a587bccb1f7a00136d29fa">Gerente de Inovação</a>
        <a href="/infovagas/jobs?page=2">2</a>
        """
        details, pages = quickin._catalog_page(markup)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0][0], "https://jobs.quickin.io/infovagas/jobs/69a587bccb1f7a00136d29fa")
        self.assertEqual(pages, ["https://jobs.quickin.io/infovagas/jobs?page=2"])

    def test_detail_header_normalizes_work_model_and_location(self):
        markup = """
        <h1>Consultor ABAP Sênior</h1>
        <h5>CLT, São Paulo Remote</h5>
        <p>Atuação em projetos de tecnologia.</p>
        """
        row = quickin._normalize(
            "https://jobs.quickin.io/infovagas/jobs/69a587bccb1f7a00136d29fa",
            markup,
        )
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "São Paulo")
        self.assertEqual(row["contract_types"], ["CLT"])


class ExperianTests(unittest.TestCase):
    def test_role_type_field_maps_hybrid_and_home(self):
        hybrid = """
        <li>__vacancyopjusttionswidget.opt-Role Type__</li><li>Hybrid</li>
        """
        home = """
        <li>__vacancyopjusttionswidget.opt-Role Type__</li><li>Home</li>
        """
        self.assertEqual(experian._parse_work_model(hybrid), "hybrid")
        self.assertEqual(experian._parse_work_model(home), "remote")

    def test_fetch_hydrates_role_type_from_detail_page(self):
        listing = (
            '<a href="/job/especialista-de-produtos-de-adquirencia-in-'
            'sao-paulo-brazil-jid-5424">Especialista de Produtos de Adquirência</a>'
        )
        detail = """
        <h1>Especialista de Produtos de Adquirência</h1>
        <ol>
          <li>__vacancyopjusttionswidget.opt-Location__</li><li>Sao Paulo</li>
          <li>__vacancyopjusttionswidget.opt-Role Type__</li><li>Hybrid</li>
        </ol>
        """
        def fake_get_text(url, *args, **kwargs):
            return listing if "/jobs?" in url else detail

        with patch.object(experian, "get_text", side_effect=fake_get_text):
            rows = experian.fetch()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], "5424")
        self.assertEqual(rows[0]["work_model"], "hybrid")

    def test_legacy_marker_is_a_fallback(self):
        self.assertEqual(experian._parse_work_model("#LI-HYBRID"), "hybrid")
        self.assertEqual(experian._parse_work_model("#LI-REMOTE"), "remote")


class RegistryTests(unittest.TestCase):
    def test_new_sources_are_registered_and_guarded(self):
        selected = pipeline.selected_registry("spassu,infovagas")
        self.assertEqual([name for name, _fetch in selected], ["spassu", "infovagas"])
        self.assertTrue({"spassu", "infovagas"}.issubset(pipeline.NONEMPTY_SOURCES))


if __name__ == "__main__":
    unittest.main()
