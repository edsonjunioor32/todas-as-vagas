# -*- coding: utf-8 -*-
"""Multi-portal ETL: collect, normalize, classify, store and export."""
# General collection can be triggered manually through the GitHub workflow.
# Rendered career pages are verified by their adapters before publication.
# Telegram alerts run only after the public snapshot passes validation.
import argparse
import concurrent.futures
import gzip
import json
import math
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import classify
import storage
from sources import (
    REGISTRY,
    recrutei as recrutei_source,
    solides as solides_source,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = HERE / "data" / "jobs.db"
JSON_PATH = ROOT / "docs" / "data" / "vagas.json"

# Every registered source is expected to expose public vacancies unless it is
# explicitly documented as a feed that can legitimately be empty. Keep this
# allowlist small: empty required feeds are integration failures and must not
# replace the last valid snapshot.
# Journy is refreshed by its dedicated 02:17 Brasília workflow, not by the
# four daytime refreshes that serve the other portals.
NIGHTLY_ONLY_SOURCES = {"journy"}
PAUSED_SOURCES = frozenset({"azify", "assefaz", "cprocco", "atitude"})

ALLOW_EMPTY_SOURCES = frozenset({"fiotec", "saleco"})
NONEMPTY_SOURCES = frozenset(
    {name for name, _fetch in REGISTRY if name not in ALLOW_EMPTY_SOURCES}
    | PAUSED_SOURCES
)

CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_ENV = "JOBS_COLLECTION_CHECKPOINT_DIR"

def sources_to_preserve(failed_sources):
    """Return unavailable sources whose last valid rows must remain eligible."""
    failed = {
        str(source).strip()
        for source in (failed_sources or [])
        if str(source).strip()
    }
    return sorted(failed | PAUSED_SOURCES)


def selected_registry(names):
    if not names:
        return [
            (name, fetch)
            for name, fetch in REGISTRY
            if name not in NIGHTLY_ONLY_SOURCES and name not in PAUSED_SOURCES
        ]
    wanted = {part.strip().lower() for part in names.split(",") if part.strip()}
    selected = [
        (name, fetch)
        for name, fetch in REGISTRY
        if name in wanted and name not in PAUSED_SOURCES
    ]
    missing = wanted - {name for name, _ in selected}
    if missing:
        paused = missing & PAUSED_SOURCES
        if paused:
            raise SystemExit(f"Paused source(s): {', '.join(sorted(paused))}")
        raise SystemExit(f"Unknown source(s): {', '.join(sorted(missing))}")
    return selected


def _env_int(name, default, minimum=1, maximum=16):
    try:
        value = int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


_ROW_TEXT_FIELDS = (
    "company", "area", "seniority", "work_model", "city", "state", "country",
    "market", "salary_currency", "published_date", "expires_date", "description",
)
_ROW_LIST_FIELDS = ("skills", "contract_types", "levels", "categories")


def _validate_source_rows(name, rows):
    """Keep valid rows while quarantining malformed records individually."""
    valid = []
    dropped = 0
    try:
        iterator = iter(rows)
    except TypeError:
        return [], 1

    for row in iterator:
        if not isinstance(row, dict):
            dropped += 1
            continue
        item = dict(row)
        title, url = item.get("title"), item.get("url")
        if not isinstance(title, str) or not title.strip():
            dropped += 1
            continue
        if not isinstance(url, str) or not url.strip():
            dropped += 1
            continue

        source = item.get("source")
        if source is None or (isinstance(source, str) and not source.strip()):
            source = name
        elif not isinstance(source, str) or source.strip().casefold() != name.casefold():
            dropped += 1
            continue
        item["source"] = name
        item["title"] = title.strip()
        item["url"] = url.strip()
        item["native_id"] = item.get("native_id") or ""
        item["company"] = item.get("company") or ""

        malformed = False
        for field in _ROW_TEXT_FIELDS:
            value = item.get(field)
            if value is not None and not isinstance(value, str):
                malformed = True
                break
        native_id = item.get("native_id")
        if native_id is not None and (
            isinstance(native_id, bool) or not isinstance(native_id, (str, int))
        ):
            malformed = True
        for field in ("salary_min", "salary_max"):
            value = item.get(field)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                malformed = True
        for field in _ROW_LIST_FIELDS:
            value = item.get(field)
            if value is None:
                item[field] = []
            elif isinstance(value, str):
                item[field] = [value] if value.strip() else []
            elif isinstance(value, (list, tuple, set)) and all(
                isinstance(part, str) for part in value
            ):
                item[field] = sorted(value) if isinstance(value, set) else list(value)
            else:
                malformed = True
        for field in ("pcd", "blind_selection"):
            value = item.get(field)
            if value is not None and not isinstance(value, (bool, int)):
                malformed = True
        if malformed:
            dropped += 1
            continue
        try:
            json.dumps(item, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            dropped += 1
            continue
        valid.append(item)
    return valid, dropped


def _collect_source(index, name, fetch):
    started = time.perf_counter()
    try:
        fetched = fetch()
        if fetched is None:
            fetched = []
        if isinstance(fetched, dict):
            raise TypeError("the adapter returned an object instead of a job list")
        fetched = list(fetched)
        valid, dropped = _validate_source_rows(name, fetched)
        error = (
            f"discarded {dropped} malformed vacancy row(s)"
            if dropped else ""
        )
        if name in NONEMPTY_SOURCES and not valid:
            empty_error = "returned zero vacancies; preserving the last valid snapshot"
            error = f"{error}; {empty_error}" if error else empty_error
        return {
            "index": index,
            "name": name,
            "rows": valid,
            "dropped": dropped,
            "seconds": time.perf_counter() - started,
            "error": error,
        }
    except Exception as error:
        # Some adapters can return a useful partial result while reporting
        # board-level failures (notably Greenhouse). Preserve those rows and
        # mark the source unhealthy so storage keeps the last valid snapshot
        # for boards that were temporarily blocked.
        partial = getattr(error, "rows", None) or []
        valid_partial, dropped = _validate_source_rows(name, partial)
        detail = str(error)[:180]
        if dropped:
            detail = f"{detail}; discarded {dropped} malformed partial row(s)"[:180]
        return {
            "index": index,
            "name": name,
            "rows": valid_partial,
            "dropped": dropped,
            "seconds": time.perf_counter() - started,
            "error": detail,
        }


def _checkpoint_path(checkpoint_dir, name):
    """Return a safe per-source checkpoint path."""
    safe_name = "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in str(name)
    )
    return Path(checkpoint_dir) / f"{safe_name}.json.gz"


def _read_checkpoint(checkpoint_dir, name):
    """Load one successful source result, ignoring corrupt or stale files."""
    if not checkpoint_dir:
        return None
    path = _checkpoint_path(checkpoint_dir, name)
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, EOFError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or payload.get("source") != name
        or payload.get("status") != "ok"
        or not isinstance(payload.get("rows"), list)
    ):
        return None
    rows, dropped = _validate_source_rows(name, payload["rows"])
    if dropped:
        return None
    if name in NONEMPTY_SOURCES and not rows:
        return None
    return {
        "rows": rows,
        "dropped": int(payload.get("dropped") or 0),
        "seconds": float(payload.get("seconds") or 0.0),
    }


def _write_checkpoint(checkpoint_dir, name, result):
    """Atomically persist a successful source result for a later retry."""
    if not checkpoint_dir or result.get("error"):
        return
    path = _checkpoint_path(checkpoint_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "status": "ok",
        "source": name,
        "rows": result.get("rows") or [],
        "dropped": result.get("dropped") or 0,
        "seconds": result.get("seconds") or 0.0,
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as target:
            temporary = Path(target.name)
            with gzip.GzipFile(fileobj=target, mode="wb", mtime=0) as compressed:
                compressed.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as error:
        # A checkpoint is an optimization. Never turn a successful collection
        # into a failed one because a cache volume is unavailable.
        print(f"  aviso: checkpoint de {name} não foi salvo: {error}")
        if temporary:
            temporary.unlink(missing_ok=True)


def collect(registry, checkpoint_dir=None):
    """Collect sources concurrently and resume completed sources from checkpoints."""
    if not registry:
        return [], [], []
    checkpoint_dir = checkpoint_dir or os.environ.get(CHECKPOINT_ENV, "").strip()
    checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
    results = [None] * len(registry)
    pending = []
    for index, (name, fetch) in enumerate(registry):
        cached = _read_checkpoint(checkpoint_dir, name)
        if cached is None:
            pending.append((index, name, fetch))
            continue
        results[index] = {
            "index": index,
            "name": name,
            "rows": cached["rows"],
            "dropped": cached["dropped"],
            "seconds": cached["seconds"],
            "error": "",
            "resumed": True,
        }
        print(
            f"  [{name:14}] retomada do checkpoint: {len(cached['rows']):>6} vagas"
        )

    if not pending:
        rows = [row for result in results for row in result["rows"]]
        failed = []
        metrics = [
            {
                "name": result["name"],
                "status": "ok",
                "jobs": len(result["rows"]),
                "dropped": result["dropped"],
                "seconds": result["seconds"],
                "resumed": True,
            }
            for result in results
        ]
        return rows, failed, metrics

    workers = min(len(pending), _env_int("JOBS_SOURCE_WORKERS", 5, maximum=8))
    print(f"  concorrência entre fontes: {workers}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_collect_source, index, name, fetch): index
            for index, name, fetch in pending
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result["index"]] = result
            _write_checkpoint(checkpoint_dir, result["name"], result)
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
            "dropped": result["dropped"],
            "seconds": result["seconds"],
            "resumed": bool(result.get("resumed")),
        }
        for result in results
    ]
    return rows, failed, metrics



def normalize_market(rows):
    """Normalize source-specific geography before publication."""
    for row in rows:
        source = str(row.get("source") or "").strip().casefold()
        market = str(row.get("market") or "").strip().casefold()
        if source == "yellowipe":
            row["market"] = "Global - Portugal"
            continue
        if source == "senior" and market == "global":
            row["market"] = "BR"
            continue
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

def sanitize_future_publication_dates(rows, today=None):
    """Clear impossible portal dates without discarding the vacancy.

    A portal can expose a clock-skewed or malformed publication date in the
    future. Keeping that value would make the integrity validator reject the
    entire snapshot. Clearing only the invalid field preserves the row and
    lets storage use its first-seen date as the safe fallback.
    """
    today = today or storage.local_today().isoformat()
    corrected = Counter()
    for row in rows:
        published = str(row.get("published_date") or "").strip()
        date_prefix = published[:10]
        if (
            len(date_prefix) == 10
            and date_prefix[4] == "-"
            and date_prefix[7] == "-"
            and date_prefix > today
        ):
            source = str(row.get("source") or "desconhecida").strip() or "desconhecida"
            corrected[source] += 1
            row["published_date"] = ""
    return dict(sorted(corrected.items()))



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


def main(before_persist=None):
    """Run the public ETL, optionally extending rows before descriptions are dropped."""
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
    rows, failed, source_metrics = collect(
        registry,
        checkpoint_dir=os.environ.get(CHECKPOINT_ENV, "").strip(),
    )
    preserved_sources = sources_to_preserve(failed)
    phases["Coleta das fontes"] = time.perf_counter() - stage_started
    stage_started = time.perf_counter()
    rows = normalize_market(rows)
    rows = dedupe_native(rows)
    future_publications = sanitize_future_publication_dates(
        rows, today=storage.local_today().isoformat()
    )
    if future_publications:
        print(
            "  datas de publicação futuras corrigidas: "
            + ", ".join(
                f"{source} ({count})"
                for source, count in future_publications.items()
            )
        )
    collection_today = storage.local_today().isoformat()
    max_age_days = storage.publication_max_age_days(collection_today)
    publication_cutoff = storage.publication_cutoff(
        today=collection_today,
        max_age_months=max(0, args.max_age_months),
        max_age_days=max_age_days,
    )
    rows, old_dropped = discard_old_publications(
        rows, publication_cutoff, today=collection_today
    )
    counts = Counter(row["source"] for row in rows)
    print("-" * 72)
    print(f"  coletadas: {len(rows)} vagas · fontes: {len(registry)-len(failed)}/{len(registry)}")
    window = (
        f"{max_age_days} dias (sexta a segunda)"
        if max_age_days is not None
        else f"{max(0, args.max_age_months)} meses"
    )
    print(
        f"  corte: publicadas desde {publication_cutoff} · janela: {window} · "
        f"Gupy com prazo vigente · {old_dropped} antigas descartadas"
    )
    print(f"  por portal: {dict(sorted(counts.items()))}")
    if failed:
        print(f"  fontes indisponíveis: {', '.join(failed)}")

    if PAUSED_SOURCES:
        print(
            "  fontes pausadas (vagas armazenadas preservadas até a janela normal): "
            + ", ".join(sorted(PAUSED_SOURCES))
        )

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
    if before_persist:
        before_persist(rows)
    conn = storage.connect(str(DB_PATH))
    before = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    storage.upsert(conn, rows)
    recrutei_repaired = 0
    if "recrutei" in selected_sources and "recrutei" not in failed:
        candidates = conn.execute(
            """
            SELECT job_uid, url, city, work_model
            FROM jobs
            WHERE source = 'recrutei'
              AND (
                  LOWER(TRIM(COALESCE(city, ''))) IN (
                      'brasil', 'brazil', 'não informado', 'nao informado'
                  )
                  OR LOWER(TRIM(COALESCE(city, ''))) LIKE 'publicada %'
              )
            """
        ).fetchall()
        repairs = recrutei_source.repair_historical_rows([
            {
                "job_uid": job_uid,
                "url": url,
                "city": city,
                "work_model": work_model,
            }
            for job_uid, url, city, work_model in candidates
        ])
        recrutei_repaired = storage.apply_source_repairs(conn, repairs)
    senior_markets_repaired = storage.rewrite_source_market(
        conn,
        "senior",
        "global",
        "BR",
    )
    yellowipe_markets_repaired = storage.rewrite_source_market_all(
        conn,
        "yellowipe",
        "Global - Portugal",
    )
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
        today=collection_today,
        max_age_months=max(0, args.max_age_months),
        active_feed_sources=active_feed_sources,
        max_age_days=max_age_days,
    )
    after = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    count, size_mb = storage.export_snapshot(
        conn,
        str(JSON_PATH),
        fresh_days=max(1, args.fresh_days),
        today=collection_today,
        max_age_months=max(0, args.max_age_months),
        max_age_days=max_age_days,
        source_counts=dict(sorted(counts.items())),
        failed_sources=preserved_sources,
    )
    conn.close()
    phases["Banco e fotografia pública"] = time.perf_counter() - stage_started
    phases["total"] = time.perf_counter() - pipeline_started
    print(f"  base histórica: {after} vagas ({after-before+pruned:+d} nesta execução; {pruned} removidas; {greenhouse_removed} Greenhouse fora do Brasil; {totvs_removed} TOTVS obsoletas/inválidas; {solides_urls_repaired} links Sólides corrigidos; {senior_markets_repaired} mercados Senior corrigidos; {yellowipe_markets_repaired} mercados YellowIpe corrigidos; {recrutei_repaired} localizações Recrutei reparadas; {modality_inferred} modalidades inferidas)")
    print(f"  base pública: {count} vagas · {size_mb:.2f} MB · {JSON_PATH.relative_to(ROOT)}")
    print(
        "  tempos: "
        + " · ".join(f"{name}: {seconds:.1f}s" for name, seconds in phases.items())
    )
    write_actions_summary(source_metrics, phases, count, failed)
    print("=" * 72)


if __name__ == "__main__":
    main()

