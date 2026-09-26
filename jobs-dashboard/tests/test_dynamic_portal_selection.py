import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validate_dynamic_portals import SOURCES, select_sources


class DynamicPortalSelectionTests(unittest.TestCase):
    def test_targeted_selection_only_returns_requested_sources(self):
        fetch_a = lambda: []
        fetch_b = lambda: []
        fetch_c = lambda: []
        sources = (("alpha", fetch_a), ("beta", fetch_b), ("gamma", fetch_c))

        selected = select_sources(sources, ["gamma,alpha"])

        self.assertEqual(
            selected,
            (("alpha", fetch_a), ("gamma", fetch_c)),
        )

    def test_unknown_source_is_rejected_before_any_fetch(self):
        with self.assertRaisesRegex(ValueError, "fontes desconhecidas: missing"):
            select_sources((("alpha", lambda: []),), ["missing"])

    def test_empty_selection_never_defaults_to_full_scan(self):
        with self.assertRaisesRegex(ValueError, "informe --sources ou --all"):
            select_sources(SOURCES)

    def test_full_scan_requires_explicit_flag(self):
        selected = select_sources((("alpha", lambda: []),), include_all=True)
        self.assertEqual([name for name, _fetch in selected], ["alpha"])

    def test_all_and_targeted_selection_are_mutually_exclusive(self):
        with self.assertRaisesRegex(ValueError, "use --all ou --sources"):
            select_sources((("alpha", lambda: []),), ["alpha"], include_all=True)


if __name__ == "__main__":
    unittest.main()
