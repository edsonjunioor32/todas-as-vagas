# -*- coding: utf-8 -*-
"""Regression tests for the configured dynamic portal adapters."""
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import (  # noqa: E402
    bradesco,
    experian,
    geekhunter,
    infojobs,
    quickin,
    requested_careers,
    requested_portals_27082026,
    requested_portals_28082026,
    requested_portals_29082026,
    requested_portals_03092026,
    recrutei,
    levva,
    spassu,
    journy,
    wellfound,
    workable,
    workable_brazil,
)
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

    def test_visible_geographic_location_maps_to_onsite(self):
        markup = """
        <h1>Coordenador Compras e Logística</h1>
        <strong>Vitória, Espírito Santo, Brazil</strong>
        """
        row = spassu._normalize(
            "https://spassu.zohorecruit.com/jobs/Careers/678402000029887215/Coordenador-Compras-e-Logística",
            markup,
        )
        self.assertEqual(row["city"], "Vitória")
        self.assertEqual(row["state"], "Espírito Santo")
        self.assertEqual(row["country"], "BR")
        self.assertEqual(row["work_model"], "on-site")

    def test_visible_remote_label_maps_to_remote(self):
        markup = """
        <h1>Consultor Power Platform (PL-400) – PJ</h1>
        <strong>Trabalho remoto</strong>
        """
        row = spassu._normalize(
            "https://spassu.zohorecruit.com/jobs/Careers/678402000031822205/Consultor-Power-Platform-PL-400",
            markup,
        )
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brasil")

    def test_zoho_remote_job_boolean_maps_remote_without_rendered_text(self):
        markup = r'''<h1>Analista</h1><script>
          var jobs = JSON.parse('[{\x22Remote_Job\x22:true,\x22Posting_Title\x22:\x22Analista\x22,\x22City\x22:null}]');
        </script>'''
        row = spassu._normalize(
            "https://spassu.zohorecruit.com/jobs/Careers/123/Analista",
            markup,
        )
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brasil")

    def test_zoho_fields_map_city_state_and_contract_without_rendered_text(self):
        markup = r'''<h1>Analista de Qualidade</h1><script>
          var jobs = JSON.parse('[{\x22Remote_Job\x22:false,\x22City\x22:\x22Itaboraí\x22,\x22State\x22:\x22Rio de Janeiro\x22,\x22Country\x22:\x22Brasil\x22,\x22Job_Type\x22:\x22Efetivo\x22}]');
        </script>'''
        row = spassu._normalize(
            "https://spassu.zohorecruit.com/jobs/Careers/123/Analista",
            markup,
        )
        self.assertEqual(row["work_model"], "on-site")
        self.assertEqual(row["city"], "Itaboraí")
        self.assertEqual(row["state"], "Rio de Janeiro")
        self.assertIn("Efetivo", row["contract_types"])

    def test_missing_spassu_location_does_not_become_remote(self):
        row = spassu._normalize(
            "https://spassu.zohorecruit.com/jobs/Careers/123/Analista",
            "<h1>Analista de suporte</h1>",
        )
        self.assertEqual(row["work_model"], "")
        self.assertEqual(row["city"], "")

    def test_zoho_header_metadata_supplies_model_and_contract(self):
        markup = """
        <html>
          <head>
            <title>spassu - Agile Master - Trabalho remoto</title>
            <meta property="og:title"
                  content="spassu - Agile Master - Trabalho remoto">
            <meta name="description" content="Tipo de emprego Efetivo">
          </head>
          <body><h1>Agile Master</h1></body>
        </html>
        """
        row = spassu._normalize(
            "https://spassu.zohorecruit.com/jobs/Careers/123/Agile-Master",
            markup,
        )
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["contract_types"], ["Efetivo"])


class CloudWalkTests(unittest.TestCase):
    def test_current_listing_extracts_jobs_links_and_ignores_listing_cta(self):
        markup = """
        <a href="/jobs"><span>View openings</span></a>
        <article>
          <a href="/jobs/1082">
            <h3>Security Engineer</h3>
            <span>Risk and Compliance</span>
            <span>Apply</span>
          </a>
          <a href="/jobs/1082"><span>Apply</span></a>
          <a href="/jobs/1083">Brand Designer Apply</a>
        </article>
        """
        with patch.object(requested_careers, "get_text", return_value=markup):
            rows = requested_careers.fetch_cloudwalk()

        self.assertEqual([row["native_id"] for row in rows], ["1082", "1083"])
        self.assertEqual(rows[0]["title"], "Security Engineer")
        self.assertEqual(rows[0]["url"], "https://lp.cloudwalk.io/jobs/1082")
        self.assertEqual(rows[1]["title"], "Brand Designer")


class InfoJobsTests(unittest.TestCase):
    def test_location_slug_fills_missing_card_location(self):
        row = infojobs._normalize(
            {
                "href": "https://www.infojobs.com.br/vaga-de-analista-em-sao-paulo__123.aspx",
                "title": "Analista de suporte",
                "text": "Analista de suporte\nHoje\nEmpresa confidencial\nBR\nPresencial",
            },
            today=date(2026, 9, 4),
        )
        self.assertEqual(row["city"], "São Paulo")
        self.assertEqual(row["state"], "SP")


class RecruteiTests(unittest.TestCase):
    def test_public_card_keeps_location_and_authoritative_model(self):
        markup = """
        <div class="list-grid-item rounded position-relative">
          <div class="grid-item-content p-3">
            <div class="grid-list-desc mt-3">
              <h6><a class="job-title"
                href="https://empregos.recrutei.com.br/vaga/inovar/123-assistente">
                Assistente Financeiro
              </a></h6>
              <p class="text-muted f-14 mb-1">Inovar Consultoria RH</p>
              <p class="text-muted mb-1">Manaus, AM, Brasil</p>
            </div>
            <ul class="list-inline">
              <li><span class="badge bg-primary-light text-white">CLT</span></li>
              <li><span class="badge bg-primary text-white">Presencial</span></li>
            </ul>
          </div>
        </div>
        """
        with patch.object(recrutei, "get_text", return_value=markup):
            rows = recrutei._public_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["city"], "Manaus")
        self.assertEqual(rows[0]["state"], "AM")
        self.assertEqual(rows[0]["work_model"], "on-site")
        self.assertEqual(rows[0]["contract_types"], ["CLT"])

    def test_public_card_without_city_does_not_invent_onsite(self):
        markup = """
        <div class="list-grid-item">
          <a class="job-title"
             href="/vaga/empresa/124-analista">Analista de Suporte</a>
          <p class="text-muted f-14 mb-1">Empresa</p>
          <p class="text-muted mb-1">Não informado</p>
          <span class="badge bg-primary">Remoto</span>
        </div>
        """
        with patch.object(recrutei, "get_text", return_value=markup):
            rows = recrutei._public_rows()
        self.assertEqual(rows[0]["city"], "Brasil")
        self.assertEqual(rows[0]["work_model"], "remote")


class LevvaTests(unittest.TestCase):
    def test_rendered_cards_map_location_and_work_model(self):
        rows = levva._rows_from_cards([
            {
                "title": "Data Product Manager",
                "city": "SP - Hortolândia",
                "model": "Híbrido",
                "url": "https://levva.izirh.io/visualizar-vaga/12345678-1234-1234-1234-123456789012",
                "native_id": "12345678-1234-1234-1234-123456789012",
            },
            {
                "title": "Engenheiro de Dados Sênior",
                "city": "",
                "model": "Remoto",
                "url": "https://levva.izirh.io/visualizar-vaga/22345678-1234-1234-1234-123456789012",
                "native_id": "22345678-1234-1234-1234-123456789012",
            },
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["city"], rows[0]["state"]), ("Hortolândia", "SP"))
        self.assertEqual(rows[0]["work_model"], "hybrid")
        self.assertEqual(rows[1]["city"], "Brasil")
        self.assertEqual(rows[1]["work_model"], "remote")
        self.assertTrue(all(row["market"] == "BR" for row in rows))


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


    def test_finayatech_uses_the_board_specific_quickin_path(self):
        markup = """
        <a href="/finayatech/jobs/69e8a992b7f40200135a75e8">
          Analista de Suporte
        </a>
        """
        details, pages = quickin._catalog_page(markup, board="finayatech")
        self.assertEqual(len(details), 1)
        self.assertEqual(
            details[0][0],
            "https://jobs.quickin.io/finayatech/jobs/69e8a992b7f40200135a75e8",
        )
        self.assertEqual(pages, [])
        row = quickin._normalize(
            details[0][0],
            "<h1>Analista de Suporte</h1><p>Remoto</p>",
            details[0][1],
            source="finayatech",
            detail_re=quickin._detail_pattern("finayatech"),
        )
        self.assertEqual(row["source"], "finayatech")

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


class SalecoTests(unittest.TestCase):
    def test_listing_heading_is_used_instead_of_button_label(self):
        markup = """
        <h3>Assistente Administrativo Junior</h3>
        <a href="/jobs/assistente-administrativo-junior">
          <span>Exibir vaga</span>
        </a>
        """
        parser = requested_portals_27082026._SalecoListingParser()
        parser.feed(markup)
        self.assertEqual(
            parser.links,
            [("/jobs/assistente-administrativo-junior", "Exibir vaga",
              "Assistente Administrativo Junior")],
        )

        with patch.object(requested_portals_27082026, "get_text", return_value=markup):
            rows = requested_portals_27082026.fetch_saleco()
        self.assertEqual(rows[0]["title"], "Assistente Administrativo Junior")
        self.assertNotEqual(rows[0]["title"], "Exibir vaga")


    def test_contact_links_are_ignored(self):
        markup = """
        <h3>Analista de Operações</h3>
        <a href="/jobs/analista-de-operacoes">Exibir vaga</a>
        <a href="mailto:contato@saleco.com.br?subject=Contato">Fale conosco</a>
        """
        with patch.object(requested_portals_27082026, "get_text", return_value=markup):
            rows = requested_portals_27082026.fetch_saleco()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Analista de Operações")


class RegistryTests(unittest.TestCase):
    def test_new_sources_are_registered_and_guarded(self):
        selected = pipeline.selected_registry("spassu,infovagas")
        self.assertEqual([name for name, _fetch in selected], ["spassu", "infovagas"])
        selected_new = pipeline.selected_registry("esig,azify,finayatech,yellowipe,tivit")
        self.assertEqual([name for name, _fetch in selected_new], ["esig", "azify", "finayatech", "yellowipe", "tivit"])
        selected_levva = pipeline.selected_registry("levva")
        self.assertEqual([name for name, _fetch in selected_levva], ["levva"])
        self.assertTrue({"spassu", "infovagas", "bradesco", "nttdata", "btg", "luza", "levva", "esig", "azify", "finayatech", "yellowipe", "tivit"}.issubset(pipeline.NONEMPTY_SOURCES))


    def test_tarken_is_kept_in_seeded_inhire_tenants(self):
        seed_path = DASHBOARD.parent / "busca_vagas" / "inhire_tenants_seed.json"
        data = json.loads(seed_path.read_text(encoding="utf-8"))
        self.assertIn("tarken", {item["slug"] for item in data})



class JournyTests(unittest.TestCase):
    def test_extracts_rsc_vacancies_and_deduplicates_by_uuid(self):
        markup = StringRSC = (
            '<script>self.__next_f.push([1,"\\\"vagas\\\":[{'
            '\\"id\\\":\\"c823cdd1-6cf6-4c72-9684-749b42c987b8\\",'
            '\\"title\\\":\\"Analista\\",'
            '\\"contratante_name\\\":\\"Empresa\\",'
            '\\"location_type\\\":\\"remote\\",'
            '\\"location_label\\\":\\"Remoto\\",'
            '\\"required_skills\\\":[\\"Python\\"]}, {'
            '\\"id\\\":\\"c823cdd1-6cf6-4c72-9684-749b42c987b8\\",'
            '\\"title\\\":\\"Analista\\",'
            '\\"contratante_name\\\":\\"Empresa\\",'
            '\\"location_type\\\":\\"remote\\",'
            '\\"location_label\\\":\\"Remoto\\",'
            '\\"required_skills\\\":[\\"Python\\"]}]"])</script>'
        )
        rows = journy._extract_vacancies(markup)
        self.assertEqual(len(rows), 2)
        normalized = journy._unique_rows(rows)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["id"], "c823cdd1-6cf6-4c72-9684-749b42c987b8")

    def test_normalize_preserves_public_keywords_and_valid_detail_url(self):
        item = {
            "id": "c823cdd1-6cf6-4c72-9684-749b42c987b8",
            "title": "Desenvolvedor Full Stack",
            "contratante_name": "Empresa Teste",
            "location_type": "remote",
            "location_label": "Remoto",
            "seniority_label": "Sênior",
            "contract_type_label": "PJ",
            "required_skills": ["Python", "React"],
            "desired_skills": ["AWS"],
            "min_salary": 5000,
            "max_salary": 8000,
        }
        row = journy._normalize(item, "Descrição <strong>pública</strong>")
        self.assertEqual(row["source"], "journy")
        self.assertEqual(row["native_id"], item["id"])
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brasil")
        self.assertEqual(row["skills"], ["Python", "React", "AWS"])
        self.assertEqual(row["levels"], ["Sênior"])
        self.assertEqual(row["contract_types"], ["PJ"])
        self.assertEqual(row["description"], "Descrição pública")
        self.assertEqual(row["url"], "https://main.d3mg4gpkl052zo.amplifyapp.com/carreiras/" + item["id"])

    def test_detail_description_parser_reads_marked_div(self):
        markup = '<div data-testid="vaga-descricao"><p>Requisitos</p><ul><li>Python</li></ul></div>'
        self.assertEqual(
            journy._description(markup),
            "Requisitos Python",
        )

    def test_rejects_malformed_or_empty_listing(self):
        with self.assertRaises(RuntimeError):
            journy._unique_rows([{"id": "not-a-uuid", "title": "Vaga"}])


class GeekHunterTests(unittest.TestCase):
    def test_ntt_data_adapter_keeps_company_and_source(self):
        item = {
            "id": "ntt-1",
            "atsJob": {
                "id": "ntt-1",
                "jobSlug": "analista-qa",
                "company": {"slug": "ntt-data"},
                "atsJobDetail": {
                    "title": "Analista QA",
                    "workModality": "Remote",
                    "description": "Qualidade de software.",
                },
            },
        }
        row = geekhunter._normalize(
            item,
            source="nttdata",
            company_override="NTT DATA",
        )
        self.assertEqual(row["source"], "nttdata")
        self.assertEqual(row["company"], "NTT DATA")
        self.assertEqual(row["work_model"], "remote")
        self.assertIn("/pt/ntt-data/jobs/analista-qa", row["url"])


class BradescoTests(unittest.TestCase):
    def test_site_two_requisition_url_is_preserved(self):
        item = {
            "requisitionId": "55585",
            "displayJobTitle": "Analista de Sistemas",
            "locations": [
                {"city": "São Paulo", "state": "SP", "country": "BR"},
            ],
        }
        row = bradesco._row(item, site_id=2)
        self.assertEqual(row["source"], "bradesco")
        self.assertEqual(row["title"], "Analista de Sistemas")
        self.assertIn("/careersite/2/home/requisition/55585", row["url"])


class RequestedPortalBatchTests(unittest.TestCase):
    def test_luza_listing_pairs_title_and_location(self):
        markup = """
        <ul>
          <li class="media">
            <div class="media-body">
              <a href="/luza-group/job/ABC123"><h5>Analista de Dados</h5></a>
              <span class="text-secondary">
                <span><i class="fas fa-map-marker-alt"></i> São Paulo, State of São Paulo, Brazil </span>
                <br>
              </span>
            </div>
            <a href="/luza-group/job/ABC123"><button>Aplicar</button></a>
          </li>
        </ul>
        """
        parser = requested_portals_28082026._LuzaListingParser()
        parser.feed(markup)
        self.assertEqual(
            parser.rows,
            [("/luza-group/job/ABC123", "Analista de Dados",
              "São Paulo, State of São Paulo, Brazil")],
        )
        row = requested_portals_28082026._luza_row(parser.rows[0])
        self.assertEqual(row["source"], "luza")
        self.assertEqual(row["city"], "São Paulo")

    def test_btg_rendered_card_extracts_title_and_location(self):
        markup = """
        <div class="card-job">
          <div class="btg-grid">
            <h3><a href="/vagas/tech-data/analista-de-dados/6007277004">
              Analista de Dados
            </a></h3>
            <p class="subtitle">São Paulo</p>
          </div>
        </div>
        """
        rows = requested_portals_28082026._btg_listing_rows(markup)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "btg")
        self.assertEqual(rows[0]["title"], "Analista de Dados")
        self.assertEqual(rows[0]["native_id"], "6007277004")
        self.assertEqual(rows[0]["city"], "São Paulo")




class CompanyBatchTests(unittest.TestCase):
    def test_requested_company_boards_are_unique_and_not_global_infovagas(self):
        names = [name for name, _fetch in requested_portals_03092026.TARGETS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 158)
        self.assertIn("meutudo", names)
        self.assertIn("minsait", names)
        self.assertIn("emphasys", names)
        for tenant in ("evoluetreinamento", "levelcinco", "lotusict", "postogalo", "xlevel"):
            self.assertIn(tenant, names)
        self.assertNotIn("infovagas", names)

    def test_minsait_pandape_card_preserves_company_location_and_modality(self):
        row = requested_portals_03092026._pandape_row({
            "href": "https://minsaitbrasil.pandape.infojobs.com.br/Detail/3680944",
            "title": "Técnico de suporte jr - Rio de Janeiro",
            "text": (
                "Técnico de suporte jr - Rio de Janeiro\n"
                "Rio de Janeiro - RJ\nPresencial\nParcial tardes\n02 set"
            ),
        })
        self.assertEqual(row["source"], "minsait")
        self.assertEqual(row["company"], "Minsait Brasil")
        self.assertEqual(row["city"], "Rio de Janeiro")
        self.assertEqual(row["state"], "RJ")
        self.assertEqual(row["work_model"], "on-site")
        self.assertEqual(row["market"], "BR")


class JournyScheduleTests(unittest.TestCase):
    def test_journy_is_excluded_from_daytime_registry_but_explicitly_selectable(self):
        regular_names = {name for name, _fetch in pipeline.selected_registry("")}
        nightly_names = {name for name, _fetch in pipeline.selected_registry("journy")}
        self.assertNotIn("journy", regular_names)
        self.assertEqual(nightly_names, {"journy"})


class WellfoundTests(unittest.TestCase):
    def test_location_pages_are_paginated_and_job_links_are_canonicalized(self):
        markup = """
        <h2>Page 1 of 2</h2>
        <a href="/jobs/12345-analista-de-dados">Analista de Dados</a>
        <a href="https://wellfound.com/jobs/12345-analista-de-dados?utm_source=x">duplicada</a>
        <a href="/company/example">Empresa</a>
        """
        links = wellfound._listing_links(
            markup, "https://wellfound.com/location/brazil"
        )
        self.assertEqual(wellfound._page_count(markup), 2)
        self.assertEqual(len(links), 1)
        self.assertEqual(
            links[0][0], "https://wellfound.com/jobs/12345"
        )

    def test_jobposting_preserves_company_location_salary_and_description(self):
        posting = {
            "@type": "JobPosting",
            "title": "Senior Data Engineer",
            "identifier": {"@type": "PropertyValue", "value": "98765"},
            "employmentType": "FULL_TIME",
            "hiringOrganization": {"name": "Startup Brasil"},
            "jobLocationType": "TELECOMMUTE",
            "jobLocation": [{
                "address": {
                    "addressLocality": "São Paulo",
                    "addressRegion": "State of São Paulo",
                    "addressCountry": "Brazil",
                }
            }],
            "datePosted": "2026-09-10T12:00:00Z",
            "baseSalary": {
                "currency": "USD",
                "value": {"minValue": 90000, "maxValue": 120000},
            },
            "industry": "SaaS, Data",
            "description": "<p>Construir pipelines de dados.</p>",
        }
        markup = (
            "<h1>Senior Data Engineer</h1>"
            '<script type="application/ld+json">'
            + json.dumps(posting, ensure_ascii=False)
            + "</script>"
        )
        row = wellfound._normalize_detail(
            "https://wellfound.com/jobs/98765-senior-data-engineer",
            markup,
        )
        self.assertEqual(row["native_id"], "98765")
        self.assertEqual(row["company"], "Startup Brasil")
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "São Paulo")
        self.assertEqual(row["state"], "State of São Paulo")
        self.assertEqual(row["country"], "Brazil")
        self.assertEqual(row["market"], "BR")
        self.assertEqual(row["salary_min"], 90000)
        self.assertEqual(row["salary_max"], 120000)
        self.assertEqual(row["published_date"], "2026-09-10T12:00:00+00:00")
        self.assertEqual(row["description"], "Construir pipelines de dados.")
        self.assertEqual(row["categories"], ["SaaS", "Data"])


class RecargaPayWorkableTests(unittest.TestCase):
    def test_workable_server_markup_recovers_accessible_job_labels(self):
        markup = """
        <a aria-labelledby="job-1 job-1-posted job-1-details"
           href="/recargapay/j/ABC123/"></a>
        <h3 id="job-1">Analista de Risco</h3>
        <small id="job-1-posted">Posted 2 days ago</small>
        <div id="job-1-details"><strong>Remote</strong> · Risks · Full time Brazil</div>
        """
        links = workable._listing_links_from_markup(markup)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][0], "https://apply.workable.com/recargapay/j/ABC123/")
        self.assertIn("Analista de Risco", links[0][1])
        self.assertIn("Posted 2 days ago", links[0][1])

    def test_workable_detail_preserves_description_and_remote_market(self):
        markup = """
        <h1>Analista de Risco</h1>
        <p><strong>Remote</strong> · Risks · Full time</p>
        <div>Brazil</div>
        <section data-ui="job-description">
          <h2>Description</h2>
          <div><p>Monitorar riscos e indicadores.</p></div>
        </section>
        <section data-ui="job-requirements">
          <h2>Requirements</h2>
          <ul><li>SQL</li><li>Python</li></ul>
        </section>
        <section data-ui="job-benefits">
          <h2>Benefits</h2>
          <ul><li>Trabalho remoto</li></ul>
        </section>
        """
        row = workable._normalize_detail(
            "https://apply.workable.com/recargapay/j/ABC123/",
            markup,
            "Analista de Risco Posted 2 days ago Remote Risks Full time Brazil",
        )
        self.assertEqual(row["native_id"], "ABC123")
        self.assertEqual(row["company"], "RecargaPay")
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brasil")
        self.assertEqual(row["country"], "BR")
        self.assertEqual(row["market"], "BR")
        self.assertEqual(row["published_date"], (date.today() - timedelta(days=2)).isoformat())
        self.assertIn("Monitorar riscos e indicadores.", row["description"])
        self.assertIn("SQL", row["description"])
        self.assertEqual(row["contract_types"], ["Full time"])



class WorkableBrazilTests(unittest.TestCase):
    def test_public_json_normalizes_metadata_and_description(self):
        item = {
            "id": "workable-1",
            "title": "Analista de Dados",
            "state": "published",
            "url": "https://jobs.workable.com/view/workable-1/analista-de-dados",
            "department": "Data",
            "employmentType": "Full-time",
            "workplace": "remote",
            "created": "2026-09-15T12:34:56.000Z",
            "locations": ["TELECOMMUTE", "Brazil"],
            "location": {"city": "", "subregion": None, "countryName": "Brazil"},
            "description": "<p>Construir relatórios.</p>",
            "requirementsSection": "<ul><li>SQL</li></ul>",
            "benefitsSection": "<p>Plano de saúde</p>",
            "company": {"title": "Empresa Teste"},
        }
        row = workable_brazil._normalize(item)
        self.assertEqual(row["source"], "workable_brazil")
        self.assertEqual(row["native_id"], "workable-1")
        self.assertEqual(row["company"], "Empresa Teste")
        self.assertEqual(row["work_model"], "remote")
        self.assertEqual(row["city"], "Brasil")
        self.assertEqual(row["country"], "BR")
        self.assertEqual(row["market"], "BR")
        self.assertEqual(row["categories"], ["Data"])
        self.assertEqual(row["contract_types"], ["Full-time"])
        self.assertEqual(row["published_date"], "2026-09-15T12:34:56+00:00")
        self.assertIn("Construir relatórios.", row["description"])
        self.assertIn("SQL", row["description"])

    def test_fetch_follows_cursor_and_deduplicates_ids(self):
        first = {
            "id": "workable-1",
            "title": "Analista de Dados",
            "state": "published",
            "url": "https://jobs.workable.com/view/workable-1/analista-de-dados",
            "company": {"title": "Empresa Teste"},
            "location": {"countryName": "Brazil"},
            "locations": ["Brazil"],
        }
        duplicate = dict(first, title="Título antigo")
        second = dict(
            first,
            id="workable-2",
            title="Engenheiro de Dados",
            url="https://jobs.workable.com/view/workable-2/engenheiro-de-dados",
        )
        pages = [
            {"jobs": [first], "nextPageToken": "cursor-2"},
            {"jobs": [duplicate, second], "nextPageToken": ""},
        ]
        with patch.object(workable_brazil, "get_json", side_effect=pages) as request:
            with patch.object(workable_brazil.time, "sleep"):
                rows = workable_brazil.fetch()

        self.assertEqual([row["native_id"] for row in rows], ["workable-1", "workable-2"])
        self.assertEqual(rows[0]["title"], "Analista de Dados")
        self.assertEqual(request.call_count, 2)
        self.assertIn("location=Brazil", request.call_args_list[0][0][0])
        self.assertIn("location=Brazil&pageToken=cursor-2", request.call_args_list[1][0][0])


class NewSourceRegistryTests(unittest.TestCase):
    def test_wellfound_and_recargapay_are_registered_and_guarded(self):
        names = {name for name, _fetch in pipeline.REGISTRY}
        self.assertIn("wellfound", names)
        self.assertIn("recargapay", names)
        self.assertIn("workable_brazil", names)
        self.assertIn("wellfound", pipeline.NONEMPTY_SOURCES)
        self.assertIn("recargapay", pipeline.NONEMPTY_SOURCES)
        self.assertIn("workable_brazil", pipeline.NONEMPTY_SOURCES)


if __name__ == "__main__":
    unittest.main()
