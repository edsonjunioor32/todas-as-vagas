# -*- coding: utf-8 -*-
"""Executa o pipeline público e gera o índice de aderência antes de descartar descrições."""
import json
import os
from pathlib import Path

import fit_requirements
import pipeline
from validate_fit import validate_entry

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
    max_raw_mb = fit_requirements.DEFAULT_MAX_RAW_MB
    if size_mb > max_raw_mb:
        raise RuntimeError(
            f"fit index com metadados excedeu limite de segurança: {size_mb:.1f} MB "
            f"(máximo {max_raw_mb:.1f} MB)"
        )
    FIT_JSON.write_text(text, encoding="utf-8")
    return size_mb


def _quarantine_limits():
    try:
        max_rows = max(0, int(os.environ.get("FIT_MAX_QUARANTINED_ROWS", "50")))
    except (TypeError, ValueError):
        max_rows = 50
    try:
        max_ratio = min(1.0, max(0.0, float(os.environ.get("FIT_MAX_QUARANTINE_RATIO", "0.02"))))
    except (TypeError, ValueError):
        max_ratio = 0.02
    return max_rows, max_ratio


def _record_quarantine(rejected):
    print(f"  fit quarantine: {len(rejected)} entradas inválidas removidas")
    for item in rejected:
        print(f"  fit quarantine: {item['url']} — {item['reason']}")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "",
        "### Entradas do índice de aderência em quarentena",
        "",
        f"Foram removidas **{len(rejected)}** entradas inválidas; o catálogo principal não foi alterado.",
        "",
        "| URL | Motivo |",
        "|---|---|",
    ]
    lines.extend(
        f"| {item['url'].replace('|', '%7C')} | {item['reason'].replace('|', '%7C')} |"
        for item in rejected
    )
    try:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("\n".join(lines) + "\n")
    except OSError as error:
        print(f"  aviso: não foi possível registrar a quarentena no resumo: {error}")


def quarantine_invalid_entries(payload):
    """Remove isolated invalid fit entries while preserving the main catalog."""
    entries = payload.get("jobs") or {}
    terms = payload.get("terms") or []
    if not isinstance(entries, dict) or not isinstance(terms, list):
        raise RuntimeError("fit index inválido antes da quarentena")
    valid, rejected = {}, []
    for url, entry in entries.items():
        reason = validate_entry(url, entry, len(terms))
        if reason:
            rejected.append({"url": str(url), "reason": reason})
        else:
            valid[url] = entry
    if not rejected:
        return payload, []
    max_rows, max_ratio = _quarantine_limits()
    ratio = len(rejected) / len(entries) if entries else 1.0
    if not valid:
        raise RuntimeError("todas as entradas do fit.json foram rejeitadas; publicação bloqueada")
    if len(rejected) > max_rows:
        raise RuntimeError(
            f"quarentena do fit excedeu o limite: {len(rejected)} entradas (máximo {max_rows})"
        )
    if ratio > max_ratio:
        raise RuntimeError(
            f"proporção de quarentena do fit excedeu o limite: {ratio:.2%} (máximo {max_ratio:.2%})"
        )
    updated = dict(payload)
    updated["jobs"] = valid
    updated["count"] = len(valid)
    _record_quarantine(rejected)
    return updated, rejected


def export_fit_index(jobs):
    count, _ = fit_requirements.export_fit_index(jobs, FIT_JSON)
    size_mb = _attach_public_metadata(jobs)
    payload = json.loads(FIT_JSON.read_text(encoding="utf-8"))
    payload, rejected = quarantine_invalid_entries(payload)
    if rejected:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        size_mb = len(text.encode("utf-8")) / 1_048_576
        FIT_JSON.write_text(text, encoding="utf-8")
        count = payload["count"]
    print(f"  índice de aderência: {count} vagas · {size_mb:.2f} MB · {FIT_JSON.relative_to(ROOT)}")


def main():
    pipeline.main(before_persist=export_fit_index)


if __name__ == "__main__":
    main()

