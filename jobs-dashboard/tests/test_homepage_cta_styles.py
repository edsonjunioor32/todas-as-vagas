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
    def test_ctas_use_a_segmented_icon_rail_and_existing_surface_colors(self):
        card = css_rule(".hero .hero-access-grid > .hero-cta")
        self.assertIn("grid-template-columns: clamp(88px, 22%, 152px) minmax(0, 1fr) 32px", card)
        self.assertIn("background: linear-gradient(180deg, var(--surface-soft), var(--surface-alt))", card)

        icon = css_rule(".hero .hero-access-grid > .hero-cta .hero-cta-icon")
        self.assertIn("min-height: 112px", icon)
        self.assertIn("border-radius: 15px 0 0 15px", icon)

    def test_mobile_ctas_use_a_compact_segmented_icon_rail(self):
        self.assertIn("grid-template-columns: 64px minmax(0, 1fr) 28px;", CSS)


if __name__ == "__main__":
    unittest.main()
