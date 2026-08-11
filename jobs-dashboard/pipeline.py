# -*- coding: utf-8 -*-
"""Multi-portal ETL: collect, normalize, classify, store and export."""
import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

import classify
import storage
from sources import REGISTRY

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = HERE / "data" / "jobs.db"
JSON_PATH = ROOT / "docs" / "data" / "vagas.json"


def selected_registry(names):
    if not names:
        return REGISTRY
    wanted = {part.strip().lower() for part in names.split(",") if part.strip()}
    selected = [(name, fetch) for name, fetch in REGISTRY if name in wanted]
    missing = wanted - {name for name, _ in selected}
    if missing:
        raise SystemExit(f"Unknown source(s): {', '.join(sorted(missing))}")
    return selected


def collect(registry):
    rows, failed = [], []
    for name, fetch in registry:
        started = time.time()
        try:
            fetched = fetch()
            valid = [row for row in fetched if row.get("title") and row.get("url")]
            rows.extend(valid)
            dropped = len(fetched) - len(valid)
            suffix = f" · {dropped} invalid dropped" if dropped else ""
            print(f"  [{name:14}] ok    {len(valid):>6} vagas ({time.time()-started:.1f}s){suffix}")
        except Exception as error:
            failed.append(name)
            print(f"  [{name:14}] FALHA {str(error)[:120]}")
    return rows, failed


def dedupe_native(rows):
    unique = {}
    for row in rows:
        key = f"{row['source']}:{row.get('native_id') or row.get('url')}"
        unique[key] = row
    return list(unique.values())


def discard_old_publications(rows, cutoff):
    """Drop rows whose normalized publication date is older than the cutoff.

    Rows without a portal-supplied date are retained here. The database uses
    their first-seen date as the fallback and expires them after three months.
    """
    kept, dropped = [], 0
    for row in rows:
        published = str(row.get("published_date") or "")[:10]
        if published and published < cutoff:
            dropped += 1
        else:
            kept.append(row)
    return kept, dropped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="collect without writing files")
    parser.add_argument("--sources", default=os.environ.get("JOBS_SOURCES", ""),
                        help="comma-separated source names for a partial run")
    parser.add_argument("--fresh-days", type=int, default=3,
                        help="keep jobs seen in this many recent collection dates")
    parser.add_argument("--max-age-months", type=int, default=3,
                        help="discard jobs published more than this many months ago")
    args = parser.parse_args()

    registry = selected_registry(args.sources)
    print("=" * 72)
    print(f"  Radar de Vagas — coleta de {len(registry)} fontes públicas")
    print("=" * 72)
    rows, failed = collect(registry)
    rows = dedupe_native(rows)
    publication_cutoff = storage.publication_cutoff(max_age_months=max(0, args.max_age_months))
    rows, old_dropped = discard_old_publications(rows, publication_cutoff)
    counts = Counter(row["source"] for row in rows)
    print("-" * 72)
    print(f"  coletadas: {len(rows)} vagas · fontes: {len(registry)-len(failed)}/{len(registry)}")
    print(f"  corte: publicadas desde {publication_cutoff} · {old_dropped} antigas descartadas")
    print(f"  por portal: {dict(sorted(counts.items()))}")
    if failed:
        print(f"  fontes indisponíveis: {', '.join(failed)}")

    if not rows:
        raise SystemExit("No jobs were collected; refusing to overwrite the public snapshot")

    for row in rows:
        classify.classify(row)

    if args.dry_run:
        sample = dict(rows[0])
        sample.pop("description", None)
        print(f"  amostra pública: {sample}")
        print("  dry-run: nenhum arquivo foi alterado")
        return

    conn = storage.connect(str(DB_PATH))
    before = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    storage.upsert(conn, rows)
    pruned = storage.prune(conn, keep_days=120, max_age_months=max(0, args.max_age_months))
    after = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    count, size_mb = storage.export_snapshot(
        conn,
        str(JSON_PATH),
        fresh_days=max(1, args.fresh_days),
        max_age_months=max(0, args.max_age_months),
        source_counts=dict(sorted(counts.items())),
        failed_sources=failed,
    )
    conn.close()
    print(f"  base histórica: {after} vagas ({after-before+pruned:+d} nesta execução; {pruned} removidas)")
    print(f"  base pública: {count} vagas · {size_mb:.2f} MB · {JSON_PATH.relative_to(ROOT)}")
    print("=" * 72)


if __name__ == "__main__":
    main()
