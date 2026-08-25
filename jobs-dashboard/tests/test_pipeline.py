# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import time
from datetime import date
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

import pipeline  # noqa: E402
import storage  # noqa: E402
from sources import ats_boards, infojobs, nerdin  # noqa: E402
from discover_greenhouse_br import is_brazilian  # noqa: E402


def sample_job(source, native_id, *, work_model="", city="São Paulo", country="BR"):
    return {
        "source": source,
        "native_id": native_id,
        "title": f"Vaga {native_id}",
        "company": "Empresa",
        "url": f"https://example.com/{native_id}",
        "work_model": work_model,
        "city": city,
        "state": "SP",
        "country": country,
        "market": "BR",
        "skills": [],
        "contract_types": [],
    }


class CollectionTests(unittest.TestCase):
    def test_parallel_collection_preserves_registry_order_and_isolates_failure(self):
        def fetch(source, delay=0.02):
            time.sleep(delay)
            return [sample_job(source, "1")]

        def fail():
            raise RuntimeError("portal indisponível")

        registry = [
            ("first", lambda: fetch("first")),
            ("broken", fail),
            ("last", lambda: fetch("last")),
        ]
        with patch.dict(os.environ, {"JOBS_SOURCE_WORKERS": "3"}):
            rows, failed, metrics = pipeline.collect(registry)

        self.assertEqual([row["source"] for row in rows], ["first", "last"])
        self.assertEqual(failed, ["broken"])
        self.assertEqual([item["name"] for item in metrics], ["first", "broken", "last"])

    def test_partial_source_failure_keeps_rows_and_marks_source_failed(self):
        def partial_failure():
            raise ats_boards.GreenhouseCollectionError(
                "1 Greenhouse board failed",
                rows=[sample_job("greenhouse", "1")],
                failed_boards=["example"],
            )

        rows, failed, metrics = pipeline.collect([("greenhouse", partial_failure)])

        self.assertEqual([row["native_id"] for row in rows], ["1"])
        self.assertEqual(failed, ["greenhouse"])
        self.assertEqual(metrics[0]["status"], "falha")


class GreenhouseLocationTests(unittest.TestCase):
    def test_discovery_does_not_mistake_foreign_state_codes_for_brazil(self):
        def item(location):
            return {"location": {"name": location}}

        self.assertFalse(is_brazilian(item("Boston, MA")))
        self.assertFalse(is_brazilian(item("San Juan, PR")))
        self.assertTrue(is_brazilian(item("São Paulo, SP")))
        self.assertTrue(is_brazilian(item("Brasil")))

    def test_infer_work_models_only_fills_missing_brazilian_values(self):
        rows = [
            sample_job("a", "1", city="Brasil"),
            sample_job("b", "2", city="São Paulo"),
            sample_job("c", "3", work_model="hybrid", city="Recife"),
            sample_job("d", "4", city="", country="US"),
        ]
        self.assertEqual(pipeline.infer_work_models(rows), 2)
        self.assertEqual(rows[0]["work_model"], "remote")
        self.assertEqual(rows[1]["work_model"], "on-site")
        self.assertEqual(rows[2]["work_model"], "hybrid")
        self.assertEqual(rows[3]["work_model"], "")


class StorageTests(unittest.TestCase):
    def test_upsert_preserves_known_modality_and_bulk_inference_repairs_legacy(self):
        with tempfile.TemporaryDirectory() as temporary:
            conn = storage.connect(str(Path(temporary) / "jobs.db"))
            known = sample_job("portal", "1", work_model="remote", city="Brasil")
            storage.upsert(conn, [known], today="2026-08-20")
            storage.upsert(
                conn,
                [sample_job("portal", "1", work_model="", city="Brasil")],
                today="2026-08-20",
            )
            self.assertEqual(
                conn.execute("SELECT work_model FROM jobs WHERE job_uid = 'portal:1'").fetchone()[0],
                "remote",
            )

            legacy = sample_job("portal", "2", work_model="", city="Curitiba")
            storage.upsert(conn, [legacy], today="2026-08-20")
            self.assertEqual(storage.infer_missing_work_models(conn), 1)
            self.assertEqual(
                conn.execute("SELECT work_model FROM jobs WHERE job_uid = 'portal:2'").fetchone()[0],
                "on-site",
            )
            conn.close()

    def test_failed_source_keeps_last_valid_rows_beyond_fresh_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            conn = storage.connect(str(Path(temporary) / "jobs.db"))
            storage.upsert(conn, [sample_job("greenhouse", "1")], today="2026-08-20")
            out = Path(temporary) / "vagas.json"
            count, _ = storage.export_snapshot(
                conn,
                str(out),
                fresh_days=3,
                today="2026-08-25",
                failed_sources=["greenhouse"],
            )
            self.assertEqual(count, 1)
            conn.close()


class NerdinTests(unittest.TestCase):
    def test_public_card_is_normalized_by_shared_adapter(self):
        markup = """
        <div class="vaga-card" data-href="vaga_emprego/vaga-analista-123.php">
          <h3 class="vaga-titulo">Analista de Suporte</h3>
          <span class="vaga-empresa-nome">Empresa Teste</span>
          <div class="vaga-local-linha">Recife • PE</div>
          <p class="vaga-resumo-linha">CLT • Pleno • Presencial</p>
          <p class="vaga-meta-extra">Sistemas • hoje</p>
          <time datetime="2026-08-20T12:30:00-03:00"></time>
          <a class="hashtag">#suporte</a>
        </div>
        Página 1 de 1
        """
        rows, pages = nerdin._parse_page(markup)
        self.assertEqual(pages, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_id"], "123")
        self.assertEqual(rows[0]["work_model"], "on-site")
        self.assertEqual(rows[0]["contract_types"], ["CLT"])


class InfoJobsTests(unittest.TestCase):
    def test_job_identifiers_deduplicates_and_ignores_invalid_urls(self):
        identifiers = infojobs._job_identifiers([
            {"href": "https://www.infojobs.com.br/vaga-de-emprego-a__101.aspx"},
            {"href": "https://www.infojobs.com.br/vaga-de-emprego-a__101.aspx?ref=x"},
            {"href": "https://www.infojobs.com.br/empregos.aspx"},
            {"href": "https://www.infojobs.com.br/vaga-de-emprego-b__202.aspx"},
        ])
        self.assertEqual(identifiers, {"101", "202"})

    def test_general_listing_keeps_non_remote_vacancies_and_parses_modality(self):
        raw = {
            "href": "https://www.infojobs.com.br/vaga-de-emprego-analista__987654.aspx?x=1",
            "title": "Analista de Dados",
            "text": "Analista de Dados\nHoje\nEmpresa Teste\nSão Paulo - SP\nPresencial\nCLT",
        }
        row = infojobs._normalize(raw, today=date(2026, 8, 20))
        self.assertIsNotNone(row)
        self.assertEqual(row["native_id"], "987654")
        self.assertEqual(row["work_model"], "on-site")
        self.assertEqual((row["city"], row["state"]), ("São Paulo", "SP"))

    def test_nationwide_result_is_not_labeled_remote_without_an_explicit_tag(self):
        raw = {
            "href": "https://www.infojobs.com.br/vaga-de-emprego-consultor__123456.aspx",
            "title": "Consultor Comercial",
            "text": "Consultor Comercial\nOntem\nEmpresa Teste\nTodo Brasil\nCLT",
        }
        row = infojobs._normalize(raw, today=date(2026, 8, 20))
        self.assertEqual(row["work_model"], "")
        self.assertEqual((row["city"], row["state"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
