import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "jobs-dashboard"))

from sources import trakstar  # noqa: E402
import pipeline  # noqa: E402


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:trakstar="https://hire.trakstar.com/xmlns">
  <channel>
    <title>Sensedia Careers</title>
    <item>
      <guid>sens-13443</guid>
      <title>Analista Operações Cloud (SRE) | Pleno</title>
      <link>https://sensedia.hire.trakstar.com/jobs/sens-13443</link>
      <pubDate>Tue, 08 Sep 2026 12:00:00 GMT</pubDate>
      <description><![CDATA[Atuação com cloud e operação de sistemas.]]></description>
      <trakstar:location>Campinas, São Paulo, Brasil</trakstar:location>
      <trakstar:work_mode>Fully remote</trakstar:work_mode>
      <trakstar:employment_type>Full-time</trakstar:employment_type>
      <trakstar:department>Product Engineering</trakstar:department>
    </item>
    <item>
      <guid>sens-13607</guid>
      <title>Analista de Suporte | Junior - Vaga Exclusiva PCD</title>
      <link>https://sensedia.hire.trakstar.com/jobs/sens-13607</link>
      <pubDate>Mon, 07 Sep 2026 12:00:00 GMT</pubDate>
      <description>Atendimento ao cliente.</description>
      <location>Campinas, São Paulo, Brasil</location>
      <remote>true</remote>
      <employment_type>Full-time</employment_type>
      <category>Support</category>
    </item>
  </channel>
</rss>
"""


class TrakstarTests(unittest.TestCase):
    def test_sensedia_feed_normalizes_public_fields(self):
        with patch.object(trakstar, "get_text", return_value=RSS):
            rows = trakstar.fetch()

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["source"], "sensedia")
        self.assertEqual(first["native_id"], "sens-13443")
        self.assertEqual(first["company"], "Sensedia")
        self.assertEqual(first["city"], "Campinas")
        self.assertEqual(first["state"], "São Paulo")
        self.assertEqual(first["country"], "Brasil")
        self.assertEqual(first["work_model"], "remote")
        self.assertEqual(first["published_date"], "2026-09-08T12:00:00+00:00")
        self.assertEqual(first["contract_types"], ["Full-time"])
        self.assertEqual(first["categories"], ["Product Engineering"])

        second = rows[1]
        self.assertTrue(second["pcd"])
        self.assertEqual(second["work_model"], "remote")
        self.assertEqual(second["categories"], ["Support"])

    def test_sensedia_is_registered_as_a_protected_source(self):
        selected = pipeline.selected_registry("sensedia")

        self.assertEqual([name for name, _fetch in selected], ["sensedia"])
        self.assertIn("sensedia", pipeline.NONEMPTY_SOURCES)


if __name__ == "__main__":
    unittest.main()
