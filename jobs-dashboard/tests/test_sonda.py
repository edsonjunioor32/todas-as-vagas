# -*- coding: utf-8 -*-
"""Regression tests for the public SONDA adapter."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from sources import sonda  # noqa: E402
import pipeline  # noqa: E402


LISTING = """
<table id="searchresults">
  <tr class="data-row">
    <td class="colTitle" headers="hdrTitle">
      <span class="jobTitle hidden-phone">
        <a href="/job/Analista-de-Suporte-Sao/1429637600/"
           class="jobTitle-link">Analista de Suporte</a>
      </span>
      <div class="jobdetail-phone visible-phone">
        <a class="jobTitle-link"
           href="/job/Analista-de-Suporte-Sao/1429637600/">
          Analista de Suporte
        </a>
      </div>
    </td>
    <td class="colLocation" headers="hdrLocation">
      <span class="jobLocation">São Paulo, Brasil</span>
    </td>
    <td class="colDepartment" headers="hdrDepartment">
      <span class="jobDepartment">Tecnologia</span>
    </td>
  </tr>
</table>
<span class="paginationLabel">Resultados <b>1 – 1</b> de <b>1</b></span>
"""


DETAIL = """
<div class="jobDisplayShell" itemscope itemtype="http://schema.org/JobPosting">
  <span itemprop="jobLocation" itemscope itemtype="http://schema.org/Place">
    <span itemprop="address" itemscope
          itemtype="http://schema.org/PostalAddress">
      <meta itemprop="addressLocality" content="São Paulo">
      <meta itemprop="addressRegion" content="SP">
      <meta itemprop="addressCountry" content="Br">
    </span>
  </span>
  <meta itemprop="datePosted" content="Wed Nov 11 08:00:00 UTC 2026">
  <span class="jobdescription">
    <p>Atuação presencial com suporte a aplicações.</p>
    <p>Conhecimentos em ITIL e SQL.</p>
  </span>
</div>
"""


class SondaTests(unittest.TestCase):
    def test_listing_parser_deduplicates_mobile_anchor_and_keeps_metadata(self):
        rows = sonda._listing_rows(LISTING)
        self.assertEqual(
            rows,
            [(
                "https://carrera.sonda.com/job/Analista-de-Suporte-Sao/1429637600/",
                "Analista de Suporte",
                "São Paulo, Brasil",
                "Tecnologia",
            )],
        )

    def test_detail_normalization_uses_schema_date_and_public_description(self):
        card = (
            "1429637600",
            "https://carrera.sonda.com/job/Analista-de-Suporte-Sao/1429637600/",
            "Analista de Suporte",
            "São Paulo, Brasil",
            "Tecnologia",
        )
        with patch.object(sonda, "get_text", return_value=DETAIL):
            row = sonda._normalize(card)

        self.assertEqual(row["source"], "sonda")
        self.assertEqual(row["native_id"], "1429637600")
        self.assertEqual(row["company"], "SONDA")
        self.assertEqual(row["published_date"], "2026-11-11")
        self.assertEqual(row["work_model"], "on-site")
        self.assertEqual(row["city"], "São Paulo")
        self.assertEqual(row["state"], "SP")
        self.assertEqual(row["country"], "BR")
        self.assertEqual(row["market"], "BR")
        self.assertEqual(row["categories"], ["Tecnologia"])
        self.assertIn("Conhecimentos em ITIL e SQL.", row["description"])

    def test_sonda_is_registered_and_selectable(self):
        names = {name for name, _fetch in pipeline.REGISTRY}
        self.assertIn("sonda", names)
        self.assertIn("sonda", pipeline.NONEMPTY_SOURCES)
        self.assertEqual(
            [name for name, _fetch in pipeline.selected_registry("sonda")],
            ["sonda"],
        )


if __name__ == "__main__":
    unittest.main()
