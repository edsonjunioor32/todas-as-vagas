# -*- coding: utf-8 -*-
"""Regression tests for the five portal adapters that load vacancies dynamically."""
import html
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import digisystem, requested_careers, sankhya_senior  # noqa: E402


class DigisystemTests(unittest.TestCase):
    def test_sitemap_keeps_only_digisystem_detail_urls(self):
        markup = """
        <url><loc>https://empregos.recrutei.com.br/vaga/digisystem/123-analista</loc></url>
        <url><loc>https://empregos.recrutei.com.br/vaga/outra/456-outra</loc></url>
        <url><loc>https://empregos.recrutei.com.br/vaga/digisystem/123-analista?utm_source=x</loc></url>
        """
        self.assertEqual(
            digisystem._sitemap_urls(markup),
            ["https://empregos.recrutei.com.br/vaga/digisystem/123-analista"],
        )

    def test_schema_jobposting_is_normalized(self):
        posting = {
            "@type": "JobPosting",
            "title": "Analista de Suporte Pleno",
            "datePosted": "2026-08-25T12:00:00Z",
            "validThrough": "2026-09-25T12:00:00Z",
            "employmentType": "FULL_TIME",
            "hiringOrganization": {"name": "Digisystem"},
            "jobLocation": {"address": {
                "addressLocality": "São Paulo", "addressRegion": "SP",
                "addressCountry": "BR",
            }},
            "description": "Requisitos: atendimento e suporte.",
        }
        page = (
            '<script type="application/ld+json">'
            + html.escape(json.dumps(posting, ensure_ascii=False))
            + "</script><span class='mdi-clipboard-text'><p>CLT</p></span>"
        )
        row = digisystem._normalize(
            "https://empregos.recrutei.com.br/vaga/digisystem/123-analista", page
        )
        self.assertEqual(row["native_id"], "123")
        self.assertEqual(row["title"], "Analista de Suporte Pleno")
        self.assertEqual(row["contract_types"], ["CLT"])
        self.assertEqual(row["published_date"], "2026-08-25T12:00:00+00:00")
        self.assertEqual((row["city"], row["state"]), ("São Paulo", "SP"))
        self.assertEqual(row["levels"], ["Pleno"])


class RequestedCareerTests(unittest.TestCase):
    def test_docusign_uses_jibe_api_records(self):
        payload = {"jobs": [{"data": {
            "slug": "12345", "title": "Support Engineer", "location_name": "BR-Remote",
            "country_code": "BR", "employment_type": "FULL_TIME",
            "posted_date": "2026-08-25T10:00:00Z", "tags1": ["Remote"],
            "categories": [{"name": "Engineering"}], "description": "Support APIs.",
        }}]}
        with patch.object(requested_careers, "get_json", return_value=payload):
            rows = requested_careers.fetch_docusign()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], "12345")
        self.assertEqual(rows[0]["work_model"], "remote")
        self.assertEqual(rows[0]["contract_types"], ["FULL_TIME"])

    def test_dbc_uses_smartrecruiters_api_records(self):
        payload = {"content": [{
            "id": "987", "name": "Platform Engineer",
            "location": {"city": "Anywhere", "country": "US", "remote": True},
            "releasedDate": "2026-08-24T10:00:00Z",
            "typeOfEmployment": {"label": "Full-time"},
            "experienceLevel": {"label": "Mid-Senior Level"},
            "department": {"label": "Engineering"},
        }]}
        with patch.object(requested_careers, "get_json", return_value=payload):
            rows = requested_careers.fetch_dbccompany()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], "987")
        self.assertEqual(rows[0]["work_model"], "remote")
        self.assertEqual(rows[0]["levels"], ["Mid-Senior Level"])
        self.assertEqual(rows[0]["contract_types"], ["Full-time"])


class SankhyaSeniorTests(unittest.TestCase):
    def test_sankhya_reads_next_data_payload(self):
        payload = {"props": {"pageProps": {"publicJobPostings": [{
            "id": 558, "name": "Data Scientist Pleno", "city": "Fortaleza",
            "state": "CE", "work_model": "REMOTE", "hire_model": "EFFECTIVE_CLT",
            "external_publication_start_at": "2026-08-25T00:00:00Z",
        }]}}}
        markup = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + "</script>"
        with patch.object(sankhya_senior, "get_text", return_value=markup):
            rows = sankhya_senior.fetch_sankhya()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], "558")
        self.assertEqual(rows[0]["work_model"], "remote")
        self.assertEqual(rows[0]["contract_types"], ["CLT"])

    def test_senior_combines_paginated_api_payloads(self):
        pages = {
            0: {"totalPages": 2, "contents": [{
                "vacancy": {"id": "a", "title": "Analista Pleno", "jobModel": ["REMOTE"],
                            "localization": {"city": "Brasil", "country": "Brasil"},
                            "publication": {"startDate": "2026-08-25"}},
                "company": {"name": "Senior", "sector": "Tecnologia"},
            }]},
            1: {"totalPages": 2, "contents": [{
                "vacancy": {"id": "b", "title": "Suporte", "jobModel": ["IN_PERSON"],
                            "localization": {"city": "Blumenau", "province": "SC", "country": "Brasil"}},
                "company": {"name": "Empresa", "sector": "Operações"},
            }]},
        }
        with patch.object(sankhya_senior, "_senior_page", side_effect=lambda page: pages[page]):
            rows = sankhya_senior._senior_rows()
        self.assertEqual({row["native_id"] for row in rows}, {"a", "b"})
        self.assertEqual(rows[0]["work_model"], "remote")
        self.assertEqual(rows[1]["work_model"], "on-site")


if __name__ == "__main__":
    unittest.main()
