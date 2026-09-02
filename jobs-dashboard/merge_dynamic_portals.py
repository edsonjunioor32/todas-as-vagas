# -*- coding: utf-8 -*-
"""Merge only the validated requested career feeds into the existing catalog.

This is deliberately different from the general ETL. It collects the repaired
feeds, refuses to write anything if one of them fails, updates only their rows
in a copied SQLite database, and atomically replaces the public snapshot. All
other portals and their history remain untouched.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify  # noqa: E402
import fit_requirements  # noqa: E402
import pipeline  # noqa: E402
import storage  # noqa: E402
from sources import (  # noqa: E402
    bradesco,
    digisystem,
    experian,
    geekhunter,
    quickin,
    levva,
    requested_careers,
    requested_portals_27082026,
    requested_portals_28082026,
    requested_portals_29082026,
    sankhya_senior,
    spassu,
)


DB_PATH = ROOT / "jobs-dashboard" / "data" / "jobs.db"
JSON_PATH = ROOT / "docs" / "data" / "vagas.json"
FIT_PATH = ROOT / "docs" / "data" / "fit.json"
TARGETS = (
    ("experian", experian.fetch),
    ("spassu", spassu.fetch),
    ("levva", levva.fetch),
    ("infovagas", quickin.fetch),
    ("digisystem", digisystem.fetch),
    ("docusign", requested_careers.fetch_docusign),
    ("dbccompany", requested_careers.fetch_dbccompany),
    ("sankhya", sankhya_senior.fetch_sankhya),
    ("senior", sankhya_senior.fetch_senior),
    ("bradesco", bradesco.fetch),
    ("nttdata", geekhunter.fetch_ntt_data),
) + requested_portals_27082026.TARGETS + requested_portals_28082026.TARGETS + requested_portals_29082026.TARGETS
TARGET_NAMES = {name for name, _ in TARGETS}
# Empty current feeds are kept in the general registry, but do not block a
# partial merge for unrelated portals and are never purged by this job.
OPTIONAL_EMPTY_SOURCES = {"fiotec", "saleco"}

# A partial run must never replace a complete public catalog with only its batch.
MIN_GUARDED_SNAPSHOT_COUNT = 10000
MIN_ALLOWED_SNAPSHOT_RATIO = 0.5


def ensure_snapshot_not_shrunk(previous_count, new_count):
    """Reject catastrophic partial-publication regressions before replacement."""
    try:
        previous = int(previous_count or 0)
        current = int(new_count or 0)
    except (TypeError, ValueError):
        return
    if previous >= MIN_GUARDED_SNAPSHOT_COUNT and current < previous * MIN_ALLOWED_SNAPSHOT_RATIO:
        raise RuntimeError(
            "redução insegura do snapshot parcial: "
            f"{previous} para {current} vagas; publicação abortada"
        )


def collect_rows():
    """Collect and normalize every target before opening the database."""
    active_targets = [
        target for target in TARGETS
        if target[0] not in OPTIONAL_EMPTY_SOURCES
    ]
    rows, failed, metrics = pipeline.collect(active_targets)
    if failed:
        details = ", ".join(
            f"{item['name']}: {item['status']}" for item in metrics if item["name"] in failed
        )
        raise RuntimeError(f"coleta parcial abortada; fontes com falha: {details}")

    rows = pipeline.normalize_market(rows)
    rows = pipeline.dedupe_native(rows)
    today = storage.local_today().isoformat()
    max_age_days = storage.publication_max_age_days(today)
    cutoff = storage.publication_cutoff(
        today=today, max_age_months=2, max_age_days=max_age_days
    )
    rows, dropped_old = pipeline.discard_old_publications(
        rows, cutoff, today=today
    )
    pipeline.infer_work_models(rows)
    for row in rows:
        classify.classify(row)
    rows, dropped_unknown = pipeline.discard_unknown_market(rows)
    counts = Counter(row["source"] for row in rows)
    missing = sorted((TARGET_NAMES - OPTIONAL_EMPTY_SOURCES) - set(counts))
    if missing:
        raise RuntimeError(
            "coleta parcial abortada; fontes ficaram sem vagas após os filtros: "
            + ", ".join(missing)
        )
    print(
        f"  lote isolado: {len(rows)} vagas · {dropped_old} antigas descartadas · "
        f"{dropped_unknown} sem mercado descartadas"
    )
    print(f"  por portal: {dict(sorted(counts.items()))}")
    return rows, dict(counts)


def _source_uids(rows, source):
    return [
        f"{source}:{row.get('native_id') or row['url']}"
        for row in rows
        if row.get("source") == source
    ]


def merge_fit_index(rows, existing_path=FIT_PATH, output_path=None):
    """Add requirements from the isolated rows without replacing old entries."""
    existing_path = Path(existing_path)
    output_path = Path(output_path or existing_path)
    payload = json.loads(existing_path.read_text(encoding="utf-8")) if existing_path.exists() else {}
    terms = list(payload.get("terms") or [])
    jobs = dict(payload.get("jobs") or {})
    term_index = {fit_requirements.normalize(term): index for index, term in enumerate(terms)}
    taxonomy = fit_requirements.load_taxonomy()

    def code(label):
        key = fit_requirements.normalize(label)
        if key not in term_index:
            term_index[key] = len(terms)
            terms.append(label)
        return term_index[key]

    changed = 0
    for row in rows:
        url = str(row.get("url") or "").strip().replace("http://", "https://", 1)
        description = str(row.get("description") or "")
        if not url or len(fit_requirements.normalize(description)) < fit_requirements.MIN_DESCRIPTION_CHARS:
            continue
        result = fit_requirements.extract_requirements(row, taxonomy)
        if not any(result[name] for name in ("mandatory", "preferred", "context", "manual")):
            continue
        jobs[url] = {
            "m": [code(value) for value in result["mandatory"]],
            "p": [code(value) for value in result["preferred"]],
            "c": [code(value) for value in result["context"]],
            "x": [code(value) for value in result["manual"]],
            "q": result["confidence"],
        }
        changed += 1

    merged = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(jobs),
        "terms": terms,
        "jobs": jobs,
    }
    text = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > 8 * 1_048_576:
        raise RuntimeError("índice de aderência excedeu o limite de 8 MB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return changed, len(jobs)


def merge_catalog(rows, collected_counts, db_path=DB_PATH, json_path=JSON_PATH,
                  fit_path=FIT_PATH, dry_run=False):
    """Replace only target rows, preserving all other database and snapshot data."""
    db_path = Path(db_path)
    json_path = Path(json_path)
    fit_path = Path(fit_path)
    if not db_path.exists() or not json_path.exists():
        raise RuntimeError("catálogo atual não encontrado para a mesclagem parcial")
    current = json.loads(json_path.read_text(encoding="utf-8"))
    previous_failed = {
        str(source).strip() for source in current.get("failed_sources") or [] if str(source).strip()
    }
    failed_after = sorted(previous_failed - TARGET_NAMES)
    previous_collected = dict(current.get("collected_source_counts") or {})
    previous_collected.update(collected_counts)

    with tempfile.TemporaryDirectory(prefix="partial-vagas-") as temporary:
        temp_dir = Path(temporary)
        temp_db = temp_dir / "jobs.db"
        temp_json = temp_dir / "vagas.json"
        temp_fit = temp_dir / "fit.json"
        shutil.copy2(db_path, temp_db)
        conn = storage.connect(str(temp_db))
        storage.upsert(conn, rows)
        removed = {}
        for source in sorted(TARGET_NAMES):
            removed[source] = storage.purge_source_rows_not_in_uids(
                conn, source, _source_uids(rows, source)
            )
        try:
            public_count, size_mb = storage.export_snapshot(
                conn,
                str(temp_json),
                fresh_days=3,
                max_age_months=2,
                max_age_days=storage.publication_max_age_days(),
                source_counts=dict(sorted(previous_collected.items())),
                failed_sources=failed_after,
            )
        finally:
            conn.close()
        ensure_snapshot_not_shrunk(current.get("count"), public_count)
        fit_changed, fit_count = merge_fit_index(rows, fit_path, temp_fit)

        if dry_run:
            print(f"  dry-run: {public_count} vagas públicas · {size_mb:.2f} MB")
            print(f"  removidas apenas dos portais do lote: {removed}")
            print(f"  índice de aderência: {fit_changed} entradas atualizadas · {fit_count} total")
            return {
                "public_count": public_count, "removed": removed,
                "fit_changed": fit_changed, "fit_count": fit_count,
            }

        os.replace(temp_db, db_path)
        os.replace(temp_json, json_path)
        os.replace(temp_fit, fit_path)
        print(f"  snapshot parcial publicado: {public_count} vagas · {size_mb:.2f} MB")
        print(f"  removidas apenas dos portais do lote: {removed}")
        print(f"  índice de aderência: {fit_changed} entradas atualizadas · {fit_count} total")
        return {
            "public_count": public_count, "removed": removed,
            "fit_changed": fit_changed, "fit_count": fit_count,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    rows, counts = collect_rows()
    result = merge_catalog(rows, counts, dry_run=args.dry_run)
    print(f"  duração total: {time.monotonic() - started:.1f}s")
    return result


if __name__ == "__main__":
    main()
