import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

import storage  # noqa: E402
import validate_snapshot  # noqa: E402


def snapshot_with_preserved_jobs(count=2):
    today = "2026-09-26"
    columns = {
        "title": [f"Vaga {i}" for i in range(count)],
        "src": [0] * count,
        "cmp": [0] * count,
        "area": [0] * count,
        "sen": [0] * count,
        "wm": [0] * count,
        "mk": [0] * count,
        "co": [0] * count,
        "city": [""] * count,
        "pub": [today] * count,
        "seen": [today] * count,
        "exp": [""] * count,
        "url": [f"https://example.com/jobs/{i}" for i in range(count)],
        "np": [""] * count,
        "sk": [""] * count,
        "smin": [None] * count,
        "smax": [None] * count,
        "cur": [0] * count,
        "pcd": [False] * count,
        "blind": [False] * count,
        "ct": [""] * count,
    }
    return {
        "count": count,
        "generated_date": today,
        "max_age_months": 2,
        "publication_cutoff": storage.publication_cutoff(today, 2),
        "collected_count": 0,
        "preserved_count": count,
        "jobs": columns,
        "dict": {
            "source": ["example"],
            "company": ["Example"],
            "area": [""],
            "seniority": [""],
            "work_model": ["remote"],
            "market": ["BR"],
            "country": ["BR"],
            "currency": [""],
        },
    }


class PreservedSnapshotTests(unittest.TestCase):
    def test_high_preserved_ratio_warns_but_does_not_block_valid_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vagas.json"
            path.write_text(json.dumps(snapshot_with_preserved_jobs()), encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(validate_snapshot, "SNAPSHOT", path), patch.dict(
                os.environ,
                {"MIN_PUBLIC_JOBS": "1", "MAX_PRESERVED_PUBLIC_RATIO": "0.5", "PREVIOUS_SNAPSHOT_PATH": ""},
                clear=False,
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                validate_snapshot.main()

        self.assertIn("OK: 2 vagas", stdout.getvalue())
        self.assertIn("AVISO", stderr.getvalue())
        self.assertIn("100.00%", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
