# -*- coding: utf-8 -*-
"""Regression tests for portal adapters that load vacancies dynamically."""
import html
import json
import sys
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import REGISTRY  # noqa: E402
from sources import (  # noqa: E402
    _http, compleo, digisystem, requested_careers, requested_portals_27082026,
    requested_portals_29082026, sankhya_senior,
)


class _Response:
    def __init__(self, payload, etag="W/\"test\""):
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = {"ETag": etag}
        self.status = 200

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class HttpCacheTests(unittest.TestCase):
    def test_get_json_persists_etag_and_reuses_304_payload(self):
        payload = {"data": ["unchanged"]}
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "page-0001.json"
            requests = []

            def first_request(request, timeout):
                requests.append(request)
                return _Response(payload)

            with patch.object(_http.urllib.request, "urlopen", side_effect=first_request):
                self.assertEqual(
                    _http.get_json("https://example.test/page", cache_file=cache_file),
                    payload,
                )
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            self.assertEqual(cached["etag"], 'W/"test"')

            def second_request(request, timeout):
                requests.append(request)
                raise urllib.error.HTTPError(
                    request.full_url, 304, "Not Modified", {}, None
                )

            with patch.object(_http.urllib.request, "urlopen", side_effect=second_request):
                stats = {}
                self.assertEqual(
                    _http.get_json(
                        "https://example.test/page",
                        cache_file=cache_file,
                        cache_stats=stats,
                        retries=1,
                    ),
                    payload,
                )
            self.assertEqual(stats["conditional_requests"], 1)
            self.assertEqual(stats["not_modified"], 1)
            headers = dict(requests[-1].header_items())
            self.assertEqual(headers.get("If-none-match"), 'W/"test"')


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


    def test_boschgroup_uses_shared_smartrecruiters_collector_and_filters_brazil(self):
        payload = {"content": [
            {
                "id": "br-987",
                "name": "Engenheiro de Software",
                "location": {
                    "city": "Campinas",
                    "region": "SP",
                    "country": "Brazil",
                    "fullLocation": "Campinas, SP, Brazil",
                    "remote": False,
                },
                "releasedDate": "2026-09-15T10:00:00Z",
                "typeOfEmployment": {"label": "Full-time"},
                "experienceLevel": {"label": "Professional"},
                "department": {"label": "Engineering"},
            },
            {
                "id": "de-654",
                "name": "Software Engineer",
                "location": {
                    "city": "Stuttgart",
                    "region": "BW",
                    "country": "Germany",
                    "fullLocation": "Stuttgart, Germany",
                },
            },
        ]}
        with patch.object(requested_careers, "get_json", return_value=payload):
            rows = requested_careers.fetch_boschgroup()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "boschgroup")
        self.assertEqual(rows[0]["native_id"], "br-987")
        self.assertEqual(rows[0]["company"], "Bosch")
        self.assertEqual(rows[0]["country"], "BR")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["city"], "Campinas")
        self.assertEqual(
            rows[0]["url"],
            "https://jobs.smartrecruiters.com/BoschGroup/br-987-engenheiro-de-software",
        )


class EdenredWorkdayTests(unittest.TestCase):
    def test_edenred_uses_public_tenant_and_detail_prefix(self):
        payload = {
            "total": 1,
            "jobPostings": [{
                "title": "Analista de Suporte",
                "locationsText": "São Paulo, Brazil",
                "externalPath": "/job/123/analista-de-suporte",
                "bulletFields": ["123"],
                "postedOn": "2026-09-01",
            }],
        }
        with patch.object(requested_portals_27082026, "post_json", return_value=payload) as request:
            rows = requested_portals_27082026.fetch_edenred()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "edenred")
        self.assertEqual(rows[0]["company"], "Edenred")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(
            rows[0]["url"],
            "https://wd3.myworkdaysite.com/recruiting/edenpeople/Edenred_Careers/1/job/123/analista-de-suporte",
        )
        self.assertIn(
            "https://wd3.myworkdaysite.com/wday/cxs/edenpeople/Edenred_Careers/jobs",
            request.call_args.args[0],
        )


class AccionaWorkdayTests(unittest.TestCase):
    def test_acciona_requests_brazil_facet_and_builds_detail_links(self):
        payload = {
            "total": 1,
            "jobPostings": [{
                "title": "ENGENHEIRO DE PLANEJAMENTO",
                "locationsText": "Guarapari",
                "externalPath": "/job/GUARAPARI/ENGENHEIRO_20102540",
                "bulletFields": ["20102540"],
                "postedOn": "2026-09-29",
            }],
        }
        with patch.object(
            requested_portals_27082026, "post_json", return_value=payload
        ) as request:
            rows = requested_portals_27082026.fetch_acciona()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "acciona")
        self.assertEqual(rows[0]["native_id"], "20102540")
        self.assertEqual(rows[0]["company"], "ACCIONA")
        self.assertEqual(rows[0]["country"], "BR")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["published_date"], "2026-09-29")
        self.assertEqual(
            rows[0]["url"],
            "https://acciona.wd3.myworkdayjobs.com/en-US/ACCIONA_Employment_Channel/job/GUARAPARI/ENGENHEIRO_20102540",
        )
        self.assertIn(
            "https://acciona.wd3.myworkdayjobs.com/wday/cxs/acciona/ACCIONA_Employment_Channel/jobs",
            request.call_args.args[0],
        )
        self.assertEqual(
            request.call_args.args[1]["appliedFacets"],
            {"Country": ["1a29bb1357b240ab99a2fa755cc87c0e"]},
        )

    def test_acciona_is_registered_as_a_source(self):
        self.assertIs(dict(REGISTRY)["acciona"], requested_portals_27082026.fetch_acciona)


class CompleoTests(unittest.TestCase):
    def test_sitemap_is_loaded_once_and_shared_between_company_boards(self):
        sitemap = (
            "<urlset><url><loc>https://jobs.compleo.app/mootit/jobdetail/1</loc></url>"
            "<url><loc>https://jobs.compleo.app/harpiait/jobdetail/2</loc></url></urlset>"
        )
        with patch.object(compleo, "_SITEMAP_URLS", None), patch.object(
            compleo, "get_text", return_value=sitemap
        ) as request:
            first = compleo._sitemap_urls()
            second = compleo._sitemap_urls()

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        request.assert_called_once_with(compleo.SITEMAP_URL, timeout=45, retries=2)

    def test_board_parser_uses_exact_tenant_and_skips_closed_jobs(self):
        sitemap_urls = (
            "https://jobs.compleo.app/mootit/jobdetail/open-1",
            "https://jobs.compleo.app/mootit/jobdetail/closed-2",
            "https://jobs.compleo.app/mootit-extra/jobdetail/wrong-tenant",
            "https://jobs.compleo.app/mootit/jobapplication/not-a-vacancy",
        )

        def detail(url, **_kwargs):
            closed = url.endswith("closed-2")
            data = {"props": {"pageProps": {"jobViewData": {
                "pk": "JOB:COM-1",
                "title": "Pessoa Desenvolvedora",
                "isAvailableOnCareersSite": not closed,
                "location": {
                    "city": {"label": "São Paulo", "uf": "SP"},
                    "country": {"label": "Brasil"},
                },
                "description": "<p>Descrição da oportunidade</p>",
                "openingDate": "2026-09-25T03:00:00.000Z",
            }}}}
            return '<script id="__NEXT_DATA__">' + json.dumps(data) + "</script>"

        with patch.object(compleo, "_sitemap_urls", return_value=sitemap_urls), patch.object(
            compleo, "get_text", side_effect=detail
        ) as request:
            rows = compleo.fetch_board("mootit", "mootit", "Moot It Consulting")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], "COM-1")
        self.assertEqual(rows[0]["source"], "mootit")
        self.assertEqual(rows[0]["company"], "Moot It Consulting")
        self.assertIn("Descrição da oportunidade", rows[0]["description"])
        self.assertEqual(request.call_count, 2)

    def test_detail_errors_raise_with_successful_rows_for_partial_publication(self):
        urls = (
            "https://jobs.compleo.app/mootit/jobdetail/good",
            "https://jobs.compleo.app/mootit/jobdetail/bad",
        )

        def detail(url, **_kwargs):
            if url.endswith("bad"):
                raise OSError("temporarily unavailable")
            data = {"props": {"pageProps": {"jobViewData": {
                "pk": "JOB:COM-2", "title": "Vaga válida",
                "location": {"country": {"label": "Brasil"}},
            }}}}
            return '<script id="__NEXT_DATA__">' + json.dumps(data) + "</script>"

        with patch.object(compleo, "_sitemap_urls", return_value=urls), patch.object(
            compleo, "get_text", side_effect=detail
        ):
            with self.assertRaisesRegex(RuntimeError, "1 of 2 detail requests failed") as caught:
                compleo.fetch_board("mootit", "mootit", "Moot It Consulting")

        self.assertEqual(len(caught.exception.rows), 1)
        self.assertEqual(caught.exception.rows[0]["native_id"], "COM-2")

    def test_all_detail_errors_raise_to_preserve_previous_snapshot(self):
        with patch.object(
            compleo, "_sitemap_urls",
            return_value=("https://jobs.compleo.app/mootit/jobdetail/1",),
        ), patch.object(compleo, "get_text", side_effect=OSError("temporarily unavailable")):
            with self.assertRaisesRegex(RuntimeError, "1 of 1 detail requests failed"):
                compleo.fetch_board("mootit", "mootit", "Moot It Consulting")

    def test_all_requested_boards_are_registered_once(self):
        names = [name for name, _fetch in REGISTRY]
        expected = {board for board, _company in compleo.COMPANIES}
        expected.add("grandy")
        self.assertTrue(expected <= set(names))
        for name in expected:
            self.assertEqual(names.count(name), 1)
        for name in ("providerit", "beq", "emphasys"):
            self.assertEqual(names.count(name), 1)

    def test_grandy_branded_boards_are_combined_and_duplicate_ids_collapsed(self):
        def duplicate(board, *_args):
            return [{"native_id": "HN15301T", "url": f"https://jobs.compleo.app/{board}/jobdetail/HN15301T"}]

        with patch.object(compleo, "fetch_board", side_effect=duplicate) as fetch:
            rows = compleo.fetch_grandy()

        self.assertEqual(len(rows), 1)
        self.assertEqual(fetch.call_args_list[0].args, ("grandy", "grandy", "Grandy"))
        self.assertEqual(
            [call.args[1] for call in fetch.call_args_list],
            ["grandy", "grandy.supermercadogule", "grandy.sanrafael"],
        )


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


    def test_mindsight_board_uses_shared_next_data_parser(self):
        payload = {"props": {"pageProps": {"publicJobPostings": [{
            "id": 901, "name": "Analista de Suporte", "city": "São Paulo",
            "state": "SP", "work_model": "HYBRID", "hire_model": "EFFECTIVE_CLT",
            "external_publication_start_at": "2026-08-28T00:00:00Z",
        }]}}}
        markup = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + "</script>"
        with patch.object(sankhya_senior, "get_text", return_value=markup):
            rows = sankhya_senior.fetch_azify()
        self.assertEqual(rows[0]["source"], "azify")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertEqual(rows[0]["title"], "Analista de Suporte")

    def test_quark_esig_parser_maps_public_processes(self):
        payload = {"processosSeletivos": [{
            "id": 63975497, "tituloProcesso": "Analista de Infraestrutura",
            "localidade": "NATAL", "vinculo": "CLT",
            "date_created": "2026-08-11 11:15:53.862",
        }]}
        with patch.object(requested_portals_29082026, "get_json", return_value=payload):
            rows = requested_portals_29082026.fetch_esig()
        self.assertEqual(rows[0]["source"], "esig")
        self.assertEqual(rows[0]["title"], "Analista de Infraestrutura")
        self.assertEqual(rows[0]["market"], "BR")
        self.assertIn("/esig/63975497", rows[0]["url"])

    def test_yellowipe_parser_reads_next_rsc_data(self):
        entries = [{
            "id": "yellow-1", "title": "Desenvolvedor RPA",
            "positionDescription": "", "location": ["Brazil - São Paulo - Franca"],
            "workplacePolicy": ["hybrid"], "updatedAt": "",
        }]
        rsc = 'b:["$","$L1a",null,{"data":' + json.dumps(entries) + ',"technologies":[]}'
        markup = "<script>self.__next_f.push([1," + json.dumps(rsc) + "])</script>"
        rows = requested_portals_29082026._yellow_rows(markup)
        self.assertEqual(rows[0]["source"], "yellowipe")
        self.assertEqual(rows[0]["city"], "Franca")
        self.assertEqual(rows[0]["market"], "Global - Portugal")

    def test_tivit_parser_maps_public_api_records(self):
        payload = [{"jobId": 4860, "companyName": "TIVIT",
                    "title": "Analista de Suporte Jr", "officeLocation": "",
                    "workMode": "Remoto", "employmentType": "Operacional",
                    "publicationDate": "2026-08-28",
                    "registrationUntil": "2026-09-28",
                    "totalPages": 1}]
        with patch.object(requested_portals_29082026, "get_json", return_value=payload):
            rows = requested_portals_29082026.fetch_tivit()
        self.assertEqual(rows[0]["source"], "tivit")
        self.assertEqual(rows[0]["work_model"], "remote")
        self.assertEqual(rows[0]["city"], "Brasil")
        self.assertEqual(rows[0]["market"], "BR")

    def test_senior_normalizes_detail_defaults(self):
        self.assertEqual(sankhya_senior._senior_work_model("Remote"), "remote")
        self.assertEqual(sankhya_senior._senior_work_model("Não informado"), "on-site")
        self.assertEqual(sankhya_senior._senior_contract_types("Não informado"), ["CLT"])
        self.assertEqual(sankhya_senior._senior_contract_types("CLT"), ["CLT"])

    def test_senior_combines_paginated_api_payloads_and_details(self):
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
        details = {
            "a": {"jobModel": ["Remote"], "hiringRegime": "Não informado",
                  "experience": ["Pleno"], "pcd": True},
            "b": {"jobModel": ["Não informado"], "hiringRegime": "CLT",
                  "experience": [], "pcd": False},
        }
        with patch.object(sankhya_senior, "_senior_page", side_effect=lambda page: pages[page]), \
             patch.object(sankhya_senior, "_senior_detail_vacancy", side_effect=lambda native_id: details[native_id]):
            rows = sankhya_senior._senior_rows()
        self.assertEqual({row["native_id"] for row in rows}, {"a", "b"})
        self.assertEqual(rows[0]["work_model"], "remote")
        self.assertEqual(rows[0]["contract_types"], ["CLT"])
        self.assertEqual(rows[0]["levels"], ["Pleno"])
        self.assertTrue(rows[0]["pcd"])
        self.assertEqual(rows[1]["work_model"], "on-site")
        self.assertEqual(rows[1]["contract_types"], ["CLT"])


if __name__ == "__main__":
    unittest.main()

class AdditionalMindsightTenantTests(unittest.TestCase):
    def test_requested_mindsight_tenants_are_registered_with_their_slugs(self):
        targets = dict(requested_portals_29082026.TARGETS)
        expected = {
            "overlabs": "Overlabs",
            "sicoobcocred": "Sicoob Cocred",
            "liquidz": "Liquidz",
            "btcreditos": "BT Créditos",
            "glcapital": "GL Capital",
            "grupoamigao": "Grupo Amigão",
            "true": "True",
        }
        self.assertTrue(set(expected).issubset(targets))
        fake_markup = (
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"publicJobPostings":['
            '{"id":1,"name":"Analista","city":"São Paulo","state":"SP",'
            '"work_model":"IN_PERSON","hire_model":"EFFECTIVE_CLT"}'
            ']}}}</script>'
        )
        with patch.object(sankhya_senior, "get_text", return_value=fake_markup):
            for slug, company in expected.items():
                rows = targets[slug]()
                self.assertEqual(rows[0]["source"], slug)
                self.assertEqual(rows[0]["company"], company)
                self.assertEqual(rows[0]["market"], "BR")

