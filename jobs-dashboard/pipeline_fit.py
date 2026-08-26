# -*- coding: utf-8 -*-
"""Executa o pipeline público e gera o índice de aderência antes de descartar descrições."""
import json
from pathlib import Path

import fit_requirements
import pipeline

ROOT = Path(__file__).resolve().parents[1]
FIT_JSON = ROOT / "docs" / "data" / "fit.json"


def _public_metadata(job):
    location = str(job.get("city") or job.get("state") or job.get("country") or "").strip()
    return {
        "t": str(job.get("title") or "")[:180],
        "e": str(job.get("company") or "")[:140],
        "l": location[:120],
        "w": str(job.get("work_model") or "")[:40],
        "d": str(job.get("published_date") or "")[:40],
    }


def _attach_public_metadata(jobs):
    payload = json.loads(FIT_JSON.read_text(encoding="utf-8"))
    entries = payload.get("jobs") or {}
    for job in jobs:
        url = str(job.get("url") or "").strip().replace("http://", "https://", 1)
        if url in entries:
            entries[url].update(_public_metadata(job))
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    size_mb = len(text.encode("utf-8")) / 1_048_576
    if size_mb > 8.0:
        raise RuntimeError(f"fit index com metadados excedeu limite de segurança: {size_mb:.1f} MB")
    FIT_JSON.write_text(text, encoding="utf-8")
    return size_mb


def export_fit_index(jobs):
    count, _ = fit_requirements.export_fit_index(jobs, FIT_JSON)
    size_mb = _attach_public_metadata(jobs)
    print(f"  índice de aderência: {count} vagas · {size_mb:.2f} MB · {FIT_JSON.relative_to(ROOT)}")


def main():
    pipeline.main(before_persist=export_fit_index)


if __name__ == "__main__":
    main()
