# -*- coding: utf-8 -*-
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import recrutei  # noqa: E402


class RecruteiPaginationTests(unittest.TestCase):
    @staticmethod
    def _card(vacancy_id, title, published="Publicada há 2 dias"):
        return f"""
        <div class="list-grid-item rounded position-relative">
          <div class="grid-item-content p-3">
            <a class="job-title" href="/vaga/empresa/{vacancy_id}-{title.lower().replace(' ', '-')}">{title}</a>
            <p class="text-muted f-14 mb-1">Empresa</p>
            <p class="text-muted mb-1">São Paulo, SP, Brasil</p>
            <p class="text-muted mb-1 small">{published}</p>
            <span class="badge bg-primary-light">CLT</span>
            <span class="badge bg-primary">Presencial</span>
          </div>
        </div>
        """

    def test_public_rows_fetches_every_announced_page(self):
        page1 = (
            "<p>Exibindo Resultados 1 - 1 de um total de 3 vagas</p>"
            + self._card(101, "Vaga Um")
        )
        page2 = (
            "<p>Exibindo Resultados 2 - 2 de um total de 3 vagas</p>"
            + self._card(102, "Vaga Dois")
        )
        page3 = (
            "<p>Exibindo Resultados 3 - 3 de um total de 3 vagas</p>"
            + self._card(103, "Vaga Tres")
        )
        requested = []

        def fake_get_text(url, *args, **kwargs):
            requested.append(url)
            if "page=2" in url:
                return page2
            if "page=3" in url:
                return page3
            return page1

        with patch.object(recrutei, "get_text", side_effect=fake_get_text):
            rows = recrutei._public_rows()

        self.assertEqual(len(rows), 3)
        self.assertIn(f"{recrutei.PUBLIC}?page=2", requested)
        self.assertIn(f"{recrutei.PUBLIC}?page=3", requested)

    def test_full_page_without_counter_stops_when_last_page_repeats(self):
        page1 = "".join(
            self._card(200 + index, f"Vaga {index}") for index in range(10)
        )
        page2 = self._card(999, "Vaga Final")
        requested = []

        def fake_get_text(url, *args, **kwargs):
            requested.append(url)
            if "?page=" in url:
                return page2
            return page1

        with patch.object(recrutei, "get_text", side_effect=fake_get_text):
            rows = recrutei._public_rows()

        self.assertEqual(len(rows), 11)
        self.assertIn(f"{recrutei.PUBLIC}?page=2", requested)
        self.assertIn(f"{recrutei.PUBLIC}?page=3", requested)

    def test_relative_publication_date_is_normalized(self):
        self.assertEqual(
            recrutei._relative_publication_date("Publicada há 2 semanas", today=date(2026, 9, 5)),
            "2026-08-22",
        )
        self.assertEqual(
            recrutei._relative_publication_date("Publicada há 3 dias", today=date(2026, 9, 5)),
            "2026-09-02",
        )

    def test_remote_brazil_card_does_not_require_detail_request(self):
        card = {
            "url": "https://empregos.recrutei.com.br/vaga/empresa/123-analista",
            "location": "Brasil",
            "badges": ["Pessoa Jurídica", "Remoto"],
            "publication": "Publicada há 2 dias",
        }
        self.assertFalse(recrutei._needs_detail(card))

    def test_old_generic_card_does_not_require_detail_request(self):
        card = {
            "url": "https://empregos.recrutei.com.br/vaga/empresa/124-analista",
            "location": "Brasil",
            "badges": ["CLT", "Presencial"],
            "publication": "Publicada há 3 meses",
        }
        self.assertFalse(recrutei._needs_detail(card))


if __name__ == "__main__":
    unittest.main()
