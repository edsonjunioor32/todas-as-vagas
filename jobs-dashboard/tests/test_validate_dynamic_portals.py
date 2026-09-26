import sys
import unittest
from pathlib import Path


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from validate_dynamic_portals import SOURCES, select_sources  # noqa: E402


class DynamicSourceSelectionTests(unittest.TestCase):
    def test_selects_only_requested_sources(self):
        selected = select_sources(["wellfound", "recargapay"])
        self.assertEqual([name for name, _fetch in selected], ["wellfound", "recargapay"])

    def test_full_scan_is_explicitly_represented_by_none(self):
        self.assertEqual(select_sources(None), SOURCES)

    def test_rejects_unknown_source_names(self):
        with self.assertRaisesRegex(ValueError, "desconhecida"):
            select_sources(["nao-existe"])

    def test_rejects_empty_targeted_selection(self):
        with self.assertRaisesRegex(ValueError, "pelo menos um"):
            select_sources([])


if __name__ == "__main__":
    unittest.main()
