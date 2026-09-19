import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "docs" / "styles.css").read_text(encoding="utf-8")


def css_rule(selector):
    match = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", CSS, re.DOTALL)
    if not match:
        raise AssertionError(f"Regra CSS ausente: {selector}")
    return match.group(1)


class HeroCtaStyleTests(unittest.TestCase):
    def test_ctas_use_balanced_two_column_grid_and_proportional_dock(self):
        grid = css_rule(".hero .hero-access-grid")
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", grid)

        card = css_rule(".hero .hero-access-grid > .hero-cta")
        self.assertIn("grid-template-columns: 52px minmax(0, 1fr) auto", card)
        self.assertIn("min-height: 82px", card)

        icon = css_rule(".hero .hero-access-grid > .hero-cta .hero-cta-icon")
        self.assertIn("width: 52px", icon)
        self.assertIn("height: 52px", icon)
        self.assertIn("border-radius: 14px", icon)

    def test_mobile_ctas_use_responsive_single_column_and_compact_dock(self):
        self.assertIn("grid-template-columns: 44px minmax(0, 1fr) auto;", CSS)
        self.assertIn("width: 44px;", CSS)
        self.assertIn("height: 44px;", CSS)


if __name__ == "__main__":
    unittest.main()
