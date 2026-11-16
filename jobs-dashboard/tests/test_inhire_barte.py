import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class BarteInhireSeedTests(unittest.TestCase):
    def test_barte_is_seeded_for_the_shared_inhire_collector(self):
        seed_path = ROOT.parent / "busca_vagas" / "inhire_tenants_seed.json"
        data = json.loads(seed_path.read_text(encoding="utf-8"))
        tenants = {item["slug"]: item["tenantName"] for item in data}
        self.assertEqual(tenants.get("barte"), "Barte")


if __name__ == "__main__":
    unittest.main()
