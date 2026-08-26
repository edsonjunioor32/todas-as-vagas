# -*- coding: utf-8 -*-
"""Multi-portal ETL: collect, normalize, classify, store and export."""
# General collection can be triggered manually through the GitHub workflow.
# Rendered career pages are verified by their adapters before publication.
# Telegram alerts run only after the public snapshot passes validation.
import argparse
import concurrent.futures
import os
import sys
import time
from collections import Counter
from pathlib import Path

import classify
import storage
from sources import REGISTRY, solides as solides_source

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = HERE / "data" / "jobs.db"
JSON_PATH = ROOT / "docs" / "data" / "vagas.json"

# These portals are expected to expose public vacancies. An empty response is
# an integration regression, never a successful refresh.
NONEMPTY_SOURCES = {
    "digisystem", "recrutei", "docusign", "dbccompany", "sankhya", "senior", "mercadolivre",
    "greenhouse",
}

def selected_registry(names):
    if not names:
        return REGISTRY
    wanted = {part.strip().lower() for part in names.split(",") if part.strip()}
    selected = [(name, fetch) for name, fetch in REGISTRY if name in wanted]
    missing = wanted - {name for name, _ in selected}
    if missing:
        raise SystemExit(f"Unknown source(s): {', '.join(sorted(missing))}")
    return selected


def _env_int(name, default, minimum=1, maximum=16):
    try:
        value = int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _collect_source(index, name, fetch):
    started = time.perf_counter()
    try:
        fetched = fetch()
        if fetched is None:
            fetched = []
        if isinstance(fetched, dict):
            raise TypeError("the adapter returned an object instead of a job list")
        fetched = list(fetched)
        valid = [
            row for row in fetched
            if isinstance(row, dict) and row.get("title") and row.get("url")
        ]
        if name in NONEMPTY_SOURCES and not valid:
            raise RuntimeError("returned zero vacancies; preserving the last valid snapshot")
        return {
            "index": index,
            "name": name,
            "rows": valid,
            "dropped": len(fetched) - len(valid),
            "seconds": time.perf_counter() - started,
            "error": "",
        }
    except Exception as error:
        # Some adapters can return a useful partial result while reporting
        # board-level failures (notably Greenhouse). Preserve those rows and
        # mark the source unhealthy so storage keeps the last valid snapshot
        # for boards that were temporarily blocked.
        partial = getattr(error, "rows", None) or []
        valid_partial = [
            row for row in partial
            if isinstance(row, dict) and row.get("title") and row.get("url")
        ]
        return {
            "index": index,
            "name": name,
            "rows": valid_partial,
            "dropped": 0,
            "seconds": time.perf_counter() - started,
            "error": str(error)[:180],
        }


def collect(registry):
    """Collect independent sources concurrently while preserving registry order."""
    if not registry:
        return [], [], []
    workers = min(len(registry), _env_int("JOBS_SOURCE_WORKERS", 5, maximum=8))
    print(f"  concorrência entre fontes: {workers}")
    results = [None] * len(registry)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_collect_source, index, name, fetch): index
            for index, (name, fetch) in enumerate(registry)
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result["index"]] = result
            if result["error"]:
                print(f"  [{result['name']:14}] FALHA {result['error']} ({result['seconds']:.1f}s)")
                continue
            suffix = f" · {result['dropped']} inválidas descartadas" if result["dropped"] else ""
            status = "ok" if result["rows"] else "vazio"
            print(
                f"  [{result['name']:14}] {status:5} {len(result['rows']):>6} vagas "
                f"({result['seconds']:.1f}s){suffix}"
            )

    rows = [row for result in results for row in result["rows"]]
    failed = [result["name"] for result in results if result["error"]]
    metrics = [
        {
            "name": result["name"],
            "status": "falha" if result["error"] else ("ok" if result["rows"] else "vazio"),
            "jobs": len(result["rows"]),
            "seconds": result["seconds"],
        }
        for result in results
    ]
    return rows, failed, metrics



def normalize_market(rows):
    """Classify a vacancy located only in Brazil as part of the Brazilian market."""
    for row in rows:
        location = str(row.get("city") or "").strip().casefold()
        if location in {"brazil", "brasil"}:
            row["market"] = "BR"
    return rows


def infer_work_models(rows):
    """Infer a missing Brazilian modality once, before writing the database."""
    inferred = 0
    remote_locations = {"br", "brasil", "brazil", "remoto", "remote", "home office"}
    for row in rows:
        if str(row.get("work_model") or "").strip():
            continue
        location = str(row.get("city") or "").strip().casefold()
        country = str(row.get("country") or "").strip().casefold()
        market = str(row.get("market") or "").strip().casefold()
        is_brazil = country in {"br", "brasil", "brazil"} or market == "br"
        if not is_brazil:
            continue
        if location in remote_locations or (
            not location and country in {"brasil", "brazil"}
        ):
            row["work_model"] = "remote"
        elif location:
            row["work_model"] = "on-site"
        else:
            continue
        inferred += 1
    return inferred

def dedupe_native(rows):
    unique = {}
    for row in rows:
        key = f"{row['source']}:{row.get('native_id') or row.get('url')}"
        unique[key] = row
    return list(unique.values())



def discard_unknown_market(rows):
    """Exclude vacancies whose market could not be identified."""
    kept = [
        row for row in rows
        if str(row.get("market") or "").strip() not in {"", "Não informado"}
    ]
    return kept, len(rows) - len(kept)

def discard_old_publications(rows, cutoff, today=None):
    """Drop rows whose normalized publication date is older than the cutoff.

    Rows without a portal-supplied date are retained here. The database uses
    their first-seen date as the fallback and expires them after two months.
    A Gupy vacancy with a current application deadline remains eligible even
    when the portal keeps its original publication date after reopening it.
    """
    today = today or storage.local_today().isoformat()
    kept, dropped = [], 0
    for row in rows:
        published = str(row.get("published_date") or "")[:10]
        expires = str(row.get("expires_date") or "")[:10]
        active_gupy = row.get("source") == "gupy" and expires and expires >= today
        if (
            published
            and published < cutoff
            and not active_gupy
            and row.get("source") not in storage.ACTIVE_PUBLIC_FEED_SOURCES
        ):
            dropped += 1
        else:
            kept.append(row)
    return kept, dropped


def write_actions_summary(source_metrics, phases, total_jobs, failed):
    """Expose timing and source health in the GitHub Actions run summary."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    ordered = sorted(source_metrics, key=lambda item: item["seconds"], reverse=True)
    lines = [
        "## Atualização do Portal Todas as Vagas",
        "",
        f"- **Vagas consolidadas:** {total_jobs:,}".replace(",", "."),
        f"- **Fontes com falha:** {', '.join(failed) if failed else 'nenhuma'}",
        f"- **Tempo total do pipeline Python:** {phases.get('total', 0):.1f}s",
        "",
        "### Tempos por etapa",
        "",
        "| Etapa | Tempo |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {seconds:.1f}s |" for name, seconds in phases.items())
    lines.extend([
        "",
        "### Fontes mais demoradas",
        "",
        "| Fonte | Situação | Vagas | Tempo |",
        "|---|---|---:|---:|",
    ])
    lines.extend(
        f"| {item['name']} | {item['status']} | {item['jobs']} | {item['seconds']:.1f}s |"
        for item in ordered
    )
    try:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("\n".join(lines) + "\n")
    except OSError as error:
        print(f"  aviso: não foi possível gravar o resumo da execução: {error}")


def main():
    pipeline_started = time.perf_counter()
    phases = {}
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="collect without writing files")
    parser.add_argument("--sources", default=os.environ.get("JOBS_SOURCES", ""),
                        help="comma-separated source names for a partial run")
    parser.add_argument("--fresh-days", type=int, default=3,
                        help="keep jobs seen in this many recent collection dates")
    parser.add_argument("--max-age-months", type=int, default=2,
                        help="discard jobs published more than this many months ago")
    args = parser.parse_args()

    os.environ["JOBS_MAX_AGE_MONTHS"] = str(max(0, args.max_age_months))
    registry = selected_registry(args.sources)
    selected_sources = {name for name, _ in registry}
    print("=" * 72)
    print(f"  Radar de Vagas — coleta de {len(registry)} fontes públicas")
    print("=" * 72)
    stage_started = time.perf_counter()
    rows, failed, source_metrics = collect(registry)
    phases["Coleta das fontes"] = time.perf_counter() - stage_started
    stage_started = time.perf_counter()
    rows = normalize_market(rows)
    rows = dedupe_native(rows)
    publication_cutoff = storage.publication_cutoff(max_age_months=max(0, args.max_age_months))
    rows, old_dropped = discard_old_publications(rows, publication_cutoff)
    counts = Counter(row["source"] for row in rows)
    print("-" * 72)
    print(f"  coletadas: {len(rows)} vagas · fontes: {len(registry)-len(failed)}/{len(registry)}")
    print(f"  corte: publicadas desde {publication_cutoff} ou Gupy com prazo vigente · {old_dropped} antigas descartadas")
    print(f"  por portal: {dict(sorted(counts.items()))}")
    if failed:
        print(f"  fontes indisponíveis: {', '.join(failed)}")

    if not rows:
        raise SystemExit("No jobs were collected; refusing to overwrite the public snapshot")

    work_models_inferred = infer_work_models(rows)
    for row in rows:
        classify.classify(row)
    rows, unknown_market_dropped = discard_unknown_market(rows)
    phases["Normalização e classificação"] = time.perf_counter() - stage_started
    print(
        f"  mercado não informado: {unknown_market_dropped} vagas descartadas · "
        f"{work_models_inferred} modalidades inferidas antes da gravação"
    )

    if args.dry_run:
        sample = dict(rows[0])
        sample.pop("description", None)
        print(f"  amostra pública: {sample}")
        print("  dry-run: nenhum arquivo foi alterado")
        phases["total"] = time.perf_counter() - pipeline_started
        write_actions_summary(source_metrics, phases, len(rows), failed)
        return

    stage_started = time.perf_counter()
    conn = storage.connect(str(DB_PATH))
    before = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    storage.upsert(conn, rows)
    solides_urls_repaired = storage.rewrite_source_urls(
        conn,
        "solides",
        solides_source.canonical_url,
    )
    totvs_removed = 0
    if "totvs" in selected_sources and "totvs" not in failed:
        totvs_removed = storage.purge_source_rows_not_in_uids(
            conn,
            "totvs",
            [
                f"totvs:{row.get('native_id') or row['url']}"
                for row in rows
                if row["source"] == "totvs"
            ],
        )
    modality_inferred = storage.infer_missing_work_models(conn)
    greenhouse_removed = 0
    if "greenhouse" in selected_sources and "greenhouse" not in failed:
        greenhouse_removed = storage.purge_greenhouse_non_brazil(
            conn,
            [
                f"greenhouse:{row.get('native_id') or row['url']}"
                for row in rows
                if row["source"] == "greenhouse"
            ],
        )
    active_feed_sources = {
        source for source in storage.ACTIVE_PUBLIC_FEED_SOURCES
        if counts.get(source, 0) and source not in failed
    }
    pruned = storage.prune(
        conn,
        keep_days=120,
        max_age_months=max(0, args.max_age_months),
        active_feed_sources=active_feed_sources,
    )
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
    phases["Banco e fotografia pública"] = time.perf_counter() - stage_started
    phases["total"] = time.perf_counter() - pipeline_started
    print(f"  base histórica: {after} vagas ({after-before+pruned:+d} nesta execução; {pruned} removidas; {greenhouse_removed} Greenhouse fora do Brasil; {totvs_removed} TOTVS obsoletas/inválidas; {solides_urls_repaired} links Sólides corrigidos; {modality_inferred} modalidades inferidas)")
    print(f"  base pública: {count} vagas · {size_mb:.2f} MB · {JSON_PATH.relative_to(ROOT)}")
    print(
        "  tempos: "
        + " · ".join(f"{name}: {seconds:.1f}s" for name, seconds in phases.items())
    )
    write_actions_summary(source_metrics, phases, count, failed)
    print("=" * 72)


if __name__ == "__main__":
    main()
