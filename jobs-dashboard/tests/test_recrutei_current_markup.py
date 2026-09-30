"""Regression tests for the current Recrutei public listing markup."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import recrutei  # noqa: E402


class RecruteiCurrentMarkupTests(unittest.TestCase):
    def test_d2_job_rows_include_numeric_and_uuid_vacancy_ids(self):
        markup = """
        <article class="d2-card d2-jobrow">
          <div class="d2-jobrow__main">
            <h3 class="d2-jobrow__title">
              <a href="https://empregos.recrutei.com.br/vaga/bm-vagas/160116-vendedor">VENDEDOR</a>
            </h3>
            <p class="d2-jobrow__meta">BM VAGAS · Poços de Caldas, MG</p>
            <div class="d2-badges">
              <span class="d2-badge d2-badge--success">Vaga nova</span>
              <span class="d2-badge d2-badge--default">CLT</span>
              <span class="d2-badge d2-badge--default">Presencial</span>
            </div>
          </div>
          <div class="d2-jobrow__side">
            <span class="d2-jobrow__time">Publicada há 4 horas</span>
            <a href="https://empregos.recrutei.com.br/vaga/bm-vagas/160116-vendedor">Candidatar-se</a>
          </div>
        </article>
        <article class="d2-card d2-jobrow">
          <div class="d2-jobrow__main">
            <h3 class="d2-jobrow__title">
              <a href="https://empregos.recrutei.com.br/vaga/anonimo/94fbea43-0fa8-43d7-bc42-5ca9f53981af">Consultor Comercial I</a>
            </h3>
            <p class="d2-jobrow__meta">Empresa anônima · São Paulo, SP</p>
            <div class="d2-badges">
              <span class="d2-badge d2-badge--success">Vaga nova</span>
              <span class="d2-badge d2-badge--default">Pessoa Jurídica</span>
              <span class="d2-badge d2-badge--default">Remoto</span>
            </div>
          </div>
          <div class="d2-jobrow__side">
            <span class="d2-jobrow__time">Publicada há 5 horas</span>
          </div>
        </article>
        """

        with patch.object(recrutei, "get_text", return_value=markup):
            rows = recrutei._public_rows()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "VENDEDOR")
        self.assertEqual(rows[0]["company"], "BM VAGAS")
        self.assertEqual((rows[0]["city"], rows[0]["state"]), ("Poços de Caldas", "MG"))
        self.assertEqual(rows[0]["contract_types"], ["CLT"])
        self.assertEqual(rows[0]["work_model"], "on-site")
        self.assertEqual(rows[1]["native_id"], "anonimo:94fbea43-0fa8-43d7-bc42-5ca9f53981af")
        self.assertEqual(rows[1]["contract_types"], ["Pessoa Jurídica"])
        self.assertEqual(rows[1]["work_model"], "remote")


if __name__ == "__main__":
    unittest.main()

