# -*- coding: utf-8 -*-
"""Regression tests for the configured dynamic portal adapters."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import (  # noqa: E402
    bradesco,
    experian,
    geekhunter,
    quickin,
    requested_portals_27082026,
    requested_portals_28082026,
    requested_portals_29082026,
    recrutei,
    levva,
    spassu,
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


if __name__ == "__main__":
    unittest.main()


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


