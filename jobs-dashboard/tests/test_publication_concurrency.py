import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PublicationConcurrencyTests(unittest.TestCase):
    def test_every_catalog_writer_uses_the_same_queued_publication_lock(self):
        for name in (
            "pages.yml",
            "merge-dynamic-portals.yml",
            "journy-nightly.yml",
            "telegram.yml",
        ):
            with self.subTest(workflow=name):
                workflow = (ROOT / ".github" / "workflows" / name).read_text(
                    encoding="utf-8"
                )
                self.assertIn("group: catalog-publication", workflow)
                self.assertIn("queue: max", workflow)
                self.assertNotIn("cancel-in-progress: true", workflow)


if __name__ == "__main__":
    unittest.main()
