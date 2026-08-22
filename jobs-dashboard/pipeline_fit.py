# -*- coding: utf-8 -*-
"""Executa o pipeline público e gera o índice de aderência antes de descartar descrições."""
from pathlib import Path

import fit_requirements
import pipeline

ROOT = Path(__file__).resolve().parents[1]
FIT_JSON = ROOT / "docs" / "data" / "fit.json"
_original_upsert = pipeline.storage.upsert


def _upsert_with_fit(conn, jobs, today=None):
    count, size_mb = fit_requirements.export_fit_index(jobs, FIT_JSON)
    print(f"  índice de aderência: {count} vagas · {size_mb:.2f} MB · {FIT_JSON.relative_to(ROOT)}")
    return _original_upsert(conn, jobs, today=today)


def main():
    pipeline.storage.upsert = _upsert_with_fit
    pipeline.main()


if __name__ == "__main__":
    main()
