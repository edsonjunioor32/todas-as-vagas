import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_fit_assets as assets


class PublicAnalyzerEntryPointTests(unittest.TestCase):
    def test_accepts_current_access_grid_layout(self):
        html = """
        <link rel="stylesheet" href="./fit-entry.css">
        <p class="hero-fit-lead">Encontre a vaga ideal.</p>
        <div class="hero-access-grid">
          <a class="hero-cta hero-cta-fit" data-fit-entry href="./aderencia/">Analisar currículo</a>
        </div>
        """
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            index.write_text(html, encoding="utf-8")
            with patch.object(assets, "INDEX", index):
                assets.verify_public_entry_point()


if __name__ == "__main__":
    unittest.main()
