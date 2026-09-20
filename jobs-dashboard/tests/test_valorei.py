import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from sources import REGISTRY, valorei
from storage import ACTIVE_PUBLIC_FEED_SOURCES


class ValoreiTests(unittest.TestCase):
    def test_normalizes_public_card_and_detail(self):
        card = {
            "title": "Desenvolvedor Backend Python Pleno",
            "url": "https://vagas.valorei.tech/jobs/job-123",
            "text": (
                "Tecnologia\nCLT\nDesenvolvedor Backend Python Pleno\n"
                "Santo Amaro, SP · Híbrido\nR$ 8.000 – R$ 12.000\nVer vaga"
            ),
        }
        detail = {
            "title": "Desenvolvedor Backend Python Pleno",
            "text": (
                "Desenvolvedor Backend Python Pleno\nPublicada em 18/09/2026\n"
                "Sobre a vaga\nDesenvolver APIs e integrações."
            ),
            "description": "Desenvolver APIs e integrações em Python.",
        }

        row = valorei._normalize_card(card, detail)

        self.assertEqual(row["source"], "valorei")
        self.assertEqual(row["native_id"], "job-123")
        self.assertEqual(row["title"], "Desenvolvedor Backend Python Pleno")
        self.assertEqual(row["company"], "Valorei")
        self.assertEqual(row["url"], card["url"])
        self.assertEqual(row["work_model"], "hybrid")
        self.assertEqual(row["city"], "Santo Amaro")
        self.assertEqual(row["state"], "SP")
        self.assertEqual(row["country"], "BR")
        self.assertEqual(row["market"], "BR")
        self.assertEqual(row["contract_types"], ["CLT"])
        self.assertEqual(row["categories"], ["Tecnologia"])
        self.assertEqual(row["salary_min"], 8000)
        self.assertEqual(row["salary_max"], 12000)
        self.assertEqual(row["salary_currency"], "BRL")
        self.assertEqual(row["published_date"], date(2026, 9, 18).isoformat())
        self.assertIn("APIs e integrações", row["description"])
        self.assertIn("Mid-level", row["levels"])

    def test_card_validation_rejects_other_hosts_and_listing_root(self):
        self.assertIsNone(
            valorei._card_base({
                "url": "https://example.com/jobs/job-123",
                "text": "A public job",
            })
        )
        self.assertIsNone(
            valorei._card_base({
                "url": "https://vagas.valorei.tech/jobs",
                "text": "The listing page",
            })
        )

    def test_fetch_deduplicates_cards_and_keeps_card_when_detail_fails(self):
        driver = MagicMock()
        cards = [
            {
                "title": "IT Solutions Engineer",
                "url": "https://vagas.valorei.tech/jobs/job-1",
                "text": "Tecnologia\nPJ\nIT Solutions Engineer\nRemoto · Remoto",
            },
            {
                "title": "IT Solutions Engineer",
                "url": "https://vagas.valorei.tech/jobs/job-1",
                "text": "Tecnologia\nPJ\nIT Solutions Engineer\nRemoto · Remoto",
            },
            {
                "title": "Analista de Suporte",
                "url": "https://vagas.valorei.tech/jobs/job-2",
                "text": "Suporte\nCLT\nAnalista de Suporte\nPelotas, Rio Grande do Sul",
            },
        ]
        driver.execute_script.side_effect = [
            cards,
            {
                "title": "IT Solutions Engineer",
                "text": "Publicada em 18/09/2026\nIntegrações com clientes.",
                "description": "Integrações com clientes e APIs.",
            },
            TimeoutError("detail page unavailable"),
        ]

        with (
            patch.object(valorei, "_new_driver", return_value=driver),
            patch.object(valorei, "_wait_for_element"),
        ):
            rows = valorei.fetch()

        self.assertEqual([row["native_id"] for row in rows], ["job-1", "job-2"])
        self.assertEqual(rows[1]["title"], "Analista de Suporte")
        self.assertEqual(rows[1]["city"], "Pelotas")
        self.assertIn("Pelotas, Rio Grande do Sul", rows[1]["description"])
        self.assertEqual(driver.get.call_count, 3)
        driver.quit.assert_called_once()

    def test_fetch_fails_closed_when_listing_has_no_cards(self):
        driver = MagicMock()
        driver.execute_script.return_value = []
        with (
            patch.object(valorei, "_new_driver", return_value=driver),
            patch.object(valorei, "_wait_for_element"),
            self.assertRaisesRegex(RuntimeError, "no public vacancies"),
        ):
            valorei.fetch()

        driver.quit.assert_called_once()

    def test_valorei_is_registered_once(self):
        registry = dict(REGISTRY)
        self.assertIs(registry["valorei"], valorei.fetch)
        self.assertEqual(sum(name == "valorei" for name, _ in REGISTRY), 1)
        self.assertIn("valorei", ACTIVE_PUBLIC_FEED_SOURCES)


if __name__ == "__main__":
    unittest.main()
