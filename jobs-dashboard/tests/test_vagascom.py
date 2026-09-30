import unittest
from datetime import date
from unittest.mock import patch

from pipeline import NONEMPTY_SOURCES
from sources import REGISTRY, vagascom


PAGE_ONE = """
<ul>
  <li class="vaga odd">
    <figure class="logoEmpresa"><img src="https://cdn.example/logo.png"></figure>
    <div class="informacoes-header">
      <h2 class="cargo"><a class="link-detalhes-vaga" data-id-vaga="2829177"
        title="Consultor(a) de Vendas" href="/vagas/v2829177/consultor-vendas">
        Consultor(a) de Vendas</a></h2>
      <span class="emprVaga">Confidencial</span>
      <span class="nivelVaga">Júnior/Trainee</span>
    </div>
    <div class="detalhes"><p>Descrição: Atendimento de clientes e prospecção.</p></div>
    <div class="vaga-local">São Paulo / SP<div class="tooltip-place">São Paulo e cidades próximas</div></div>
    <span class="data-publicacao">28/09/2026</span>
  </li>
</ul>
<a id="maisVagas" data-total="2" data-url="/vagas-de-buscar?ordenar_por=mais_recentes&amp;pagina=2&amp;q=buscar">mostrar mais</a>
"""

PAGE_TWO = """
<li class="vaga even">
  <a class="link-detalhes-vaga" data-id-vaga="2829177" title="Consultor(a) de Vendas"
     href="/vagas/v2829177/consultor-vendas">Consultor(a) de Vendas</a>
  <span class="emprVaga">Confidencial</span>
  <div class="detalhes">Descrição: Atendimento de clientes e prospecção.</div>
  <div class="vaga-local">São Paulo / SP</div>
  <span class="data-publicacao">28/09/2026</span>
</li>
<li class="vaga odd">
  <a class="link-detalhes-vaga" data-id-vaga="2829001" title="Analista de Dados"
     href="/vagas/v2829001/analista-dados">Analista de Dados</a>
  <span class="emprVaga">Empresa Exemplo</span>
  <div class="detalhes">Descrição: SQL, Python e visualização de dados.</div>
  <div class="vaga-local">Remoto - Brasil</div>
  <span class="data-publicacao">27/09/2026</span>
</li>
"""

PAGE_TWO_CUTOFF = """
<li class="vaga odd">
  <a class="link-detalhes-vaga" data-id-vaga="2829001" title="Analista de Dados"
     href="/vagas/v2829001/analista-dados">Analista de Dados</a>
  <span class="emprVaga">Empresa Exemplo</span>
  <div class="detalhes">Descrição: SQL, Python e visualização de dados.</div>
  <div class="vaga-local">Remoto - Brasil</div>
  <span class="data-publicacao">27/09/2026</span>
</li>
"""

PAGE_THREE = """
<li class="vaga odd">
  <a class="link-detalhes-vaga" data-id-vaga="2828000" title="Vaga antiga"
     href="/vagas/v2828000/vaga-antiga">Vaga antiga</a>
  <span class="emprVaga">Empresa Exemplo</span>
  <div class="detalhes">Descrição: Uma oportunidade anterior ao corte.</div>
  <div class="vaga-local">Curitiba / PR</div>
  <span class="data-publicacao">28/07/2026</span>
</li>
"""


class VagasComTests(unittest.TestCase):
    def test_relative_publication_dates_use_the_collection_date(self):
        today = date(2026, 9, 29)
        self.assertEqual(vagascom._published_date("Hoje", today), "2026-09-29")
        self.assertEqual(vagascom._published_date("Ontem", today), "2026-09-28")
        self.assertEqual(vagascom._published_date("Há 4 dias", today), "2026-09-25")

    def test_parser_reads_card_fields_and_pagination_without_tooltip_noise(self):
        cards, total_pages, next_url = vagascom._parse_listing(PAGE_ONE)

        self.assertEqual(total_pages, 2)
        self.assertEqual(next_url, "/vagas-de-buscar?ordenar_por=mais_recentes&pagina=2&q=buscar")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["native_id"], "2829177")
        self.assertEqual(cards[0]["company"], "Confidencial")
        self.assertEqual(cards[0]["location"], "São Paulo / SP")
        self.assertNotIn("cidades próximas", cards[0]["location"])

    def test_normalize_maps_public_card_to_catalog_schema(self):
        cards, _, _ = vagascom._parse_listing(PAGE_ONE)
        row = vagascom._normalize_card(cards[0])

        self.assertEqual(row["source"], "vagascom")
        self.assertEqual(row["native_id"], "2829177")
        self.assertEqual(row["title"], "Consultor(a) de Vendas")
        self.assertEqual(row["company"], "Confidencial")
        self.assertEqual(row["city"], "São Paulo")
        self.assertEqual(row["state"], "SP")
        self.assertEqual(row["country"], "BR")
        self.assertEqual(row["market"], "BR")
        self.assertEqual(row["published_date"], "2026-09-28")
        self.assertIn("Atendimento de clientes", row["description"])

    def test_fetch_paginates_deduplicates_and_is_registered(self):
        with (
            patch.object(vagascom, "PAGE_SIZE", 1),
            patch.object(vagascom, "_collection_window", return_value=(date(2026, 9, 29), "2026-07-29")),
            patch.object(vagascom, "get_text", side_effect=[PAGE_ONE, PAGE_TWO]) as request,
        ):
            rows = vagascom.fetch()

        self.assertEqual([row["native_id"] for row in rows], ["2829177", "2829001"])
        self.assertEqual(rows[1]["work_model"], "remote")
        self.assertEqual(rows[1]["city"], "Brasil")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(rows[0]["published_date"], "2026-09-28")
        self.assertEqual(request.call_args_list[1].args[0],
                         "https://www.vagas.com.br/vagas-de-buscar?ordenar_por=mais_recentes&pagina=2")
        self.assertEqual(sum(name == "vagascom" for name, _ in REGISTRY), 1)
        self.assertIs(dict(REGISTRY)["vagascom"], vagascom.fetch)
        self.assertIn("vagascom", NONEMPTY_SOURCES)

    def test_fetch_stops_after_reaching_the_catalog_two_month_cutoff(self):
        first = PAGE_ONE.replace('data-total="2"', 'data-total="3"')

        with (
            patch.object(vagascom, "PAGE_SIZE", 1),
            patch.object(vagascom, "_collection_window", return_value=(date(2026, 9, 29), "2026-07-29")),
            patch.object(vagascom, "get_text", side_effect=[first, PAGE_TWO_CUTOFF, PAGE_THREE]) as request,
        ):
            rows = vagascom.fetch()

        self.assertEqual([row["native_id"] for row in rows], ["2829177", "2829001"])
        self.assertEqual(request.call_count, 3)

    def test_fetch_fails_closed_when_a_listed_page_is_empty(self):
        with (
            patch.object(vagascom, "PAGE_SIZE", 1),
            patch.object(vagascom, "get_text", side_effect=[PAGE_ONE, "<ul></ul>", "<ul></ul>"]),
            self.assertRaisesRegex(RuntimeError, "incompleta"),
        ):
            vagascom.fetch()

    def test_normalizer_rejects_non_vagas_com_links(self):
        self.assertIsNone(vagascom._normalize_card({
            "native_id": "123",
            "href": "https://example.com/vagas/v123/teste",
            "title": "Vaga",
            "company": "Empresa",
        }))


if __name__ == "__main__":
    unittest.main()
