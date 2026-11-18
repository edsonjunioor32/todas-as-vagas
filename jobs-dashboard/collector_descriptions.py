"""Store descriptions already returned by the public collectors in the private DB.

The public pipeline receives full descriptions from several portal APIs and
drops them before publishing the catalogue. The private crawler then downloads
each job page again, which fails for portals that block page requests (HTTP
403/429, robots.txt) or remove the page (HTTP 404) while the API still serves
the text. This job reuses the same source collectors from ``pipeline.py`` on
the VPS and records those descriptions directly in the private SQLite store.

Rules:
- it only updates rows that already exist in the private store (the crawler's
  manifest sync owns row creation and pruning);
- it never overwrites a usable fetched description, only missing, failed or
  short ones;
- rows are matched by ``source:native_id`` and, as a fallback, by the
  normalized job URL (the public catalogue often keys jobs by URL);
- it logs counts only, never description content;
- each source fails in isolation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from collections import Counter

import description_store

DEFAULT_DB = os.environ.get(
    "PRIVATE_DESCRIPTIONS_DB",
    "/home/ubuntu/todas-as-vagas-private/descriptions.sqlite3",
)
# Portals whose APIs return descriptions that the page crawler cannot fetch.
DEFAULT_SOURCES = os.environ.get(
    "COLLECTOR_DESCRIPTION_SOURCES",
    "solides,arbeitnow,himalayas,vagascom,themuse",
)
DEFAULT_MIN_CHARS = 120
# Fetched descriptions shorter than this may be replaced by a longer API text.
SHORT_DESCRIPTION_CHARS = 300
CONTENT_KIND = "collector_api"
# Unmatched API descriptions wait here until the crawler's manifest sync
# creates their row (APIs such as Himalayas return jobs minutes after
# publication, before they reach the public catalogue).
CACHE_TTL_DAYS = 14
CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS collector_description_cache (
    source TEXT NOT NULL,
    native_id TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (source, native_id, url)
)
"""


def normalize_url(value: str) -> str:
    """Return scheme-less host+path without query, fragment or trailing slash."""
    text = str(value or "").strip()
    if not text:
        return ""
    parts = urllib.parse.urlsplit(text)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return f"{host}{path}" if host else ""


def url_path(value: str) -> str:
    parts = urllib.parse.urlsplit(str(value or "").strip())
    return parts.path.rstrip("/")


def _as_dict(row) -> dict:
    if isinstance(row, dict):
        return row
    if hasattr(row, "_asdict"):
        return row._asdict()
    return dict(vars(row))


def load_index(connection, sources: set[str]) -> dict[str, dict]:
    """Index existing private rows of the selected sources by lookup keys."""
    index: dict[str, dict] = {}
    placeholders = ",".join("?" for _ in sources)
    rows = connection.execute(
        f"""
        SELECT job_uid, source, native_id, url, status, length(description) AS size
        FROM job_descriptions
        WHERE source IN ({placeholders})
        """,
        tuple(sorted(sources)),
    ).fetchall()
    for row in rows:
        record = dict(row)
        index.setdefault(f"uid:{row['job_uid']}", record)
        normalized = normalize_url(row["url"])
        if normalized:
            index.setdefault(f"url:{normalized}", record)
        path = url_path(row["url"])
        if path:
            index.setdefault(f"path:{row['source']}:{path}", record)
    return index


def match(index: dict[str, dict], item: dict) -> dict | None:
    source = str(item.get("source") or "").strip()
    native_id = str(item.get("native_id") or "").strip()
    url = str(item.get("url") or "").strip()
    keys = []
    if native_id:
        keys.append(f"uid:{source}:{native_id}")
    if url:
        keys.append(f"uid:{source}:{url}")
        keys.append(f"url:{normalize_url(url)}")
        keys.append(f"path:{source}:{url_path(url)}")
    for native in (native_id,):
        if native.startswith("http"):
            keys.append(f"url:{normalize_url(native)}")
    for key in keys:
        found = index.get(key)
        if found and found["source"] == source:
            return found
    return None


def should_replace(record: dict, description: str) -> bool:
    if record["status"] != "fetched":
        return True
    size = int(record["size"] or 0)
    return size < SHORT_DESCRIPTION_CHARS and len(description) > size


def _store(connection, record, description, refresh_after_days, dry_run):
    if not dry_run:
        description_store.record_success(
            connection,
            {"job_uid": record["job_uid"]},
            description,
            content_kind=CONTENT_KIND,
            http_status=200,
            refresh_after_days=refresh_after_days,
        )
    record["status"] = "fetched"
    record["size"] = len(description)


def apply_cache(connection, index, *, refresh_after_days: int, dry_run: bool) -> dict:
    """Apply cached descriptions whose rows now exist, then prune old entries."""
    applied = 0
    pending = connection.execute(
        "SELECT rowid, source, native_id, url, description FROM collector_description_cache"
    ).fetchall()
    done = []
    for row in pending:
        record = match(index, dict(row))
        if record is None:
            continue
        if should_replace(record, row["description"]):
            _store(connection, record, row["description"], refresh_after_days, dry_run)
            applied += 1
        done.append((row["rowid"],))
    pruned = 0
    if not dry_run:
        connection.executemany("DELETE FROM collector_description_cache WHERE rowid = ?", done)
        pruned = connection.execute(
            "DELETE FROM collector_description_cache WHERE seen_at < ?",
            (description_store._after(-CACHE_TTL_DAYS * 86400),),
        ).rowcount
        connection.commit()
    return {"cache_applied": applied, "cache_pruned": pruned, "cache_waiting": len(pending) - len(done)}


def ingest(connection, registry, *, min_chars: int, refresh_after_days: int, dry_run: bool):
    sources = {name for name, _ in registry}
    if not dry_run:
        connection.execute(CACHE_SCHEMA)
        connection.commit()
    index = load_index(connection, sources)
    has_cache = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='collector_description_cache'"
    ).fetchone()
    cache_metrics = (
        apply_cache(connection, index, refresh_after_days=refresh_after_days, dry_run=dry_run)
        if has_cache
        else {"cache_applied": 0, "cache_pruned": 0, "cache_waiting": 0}
    )
    cache_rows = []
    metrics = {
        "sources": {},
        "stored": 0,
        "matched": 0,
        "collected_with_description": 0,
        "unmatched": 0,
        "kept_existing": 0,
        "failed_sources": [],
        "dry_run": dry_run,
    }
    for name, fetch in registry:
        started = time.monotonic()
        counts = Counter()
        try:
            rows = [_as_dict(row) for row in (fetch() or [])]
        except Exception as error:  # noqa: BLE001 - fronteira: cada portal falha isolado
            metrics["failed_sources"].append({"source": name, "error": type(error).__name__})
            continue
        for item in rows:
            counts["collected"] += 1
            description = str(item.get("description") or "").strip()
            if len(description) < min_chars:
                continue
            counts["with_description"] += 1
            record = match(index, item)
            if record is None:
                counts["unmatched"] += 1
                cache_rows.append((
                    name,
                    str(item.get("native_id") or "").strip(),
                    str(item.get("url") or "").strip(),
                    description,
                    description_store.utc_now(),
                ))
                continue
            counts["matched"] += 1
            if not should_replace(record, description):
                counts["kept_existing"] += 1
                continue
            counts["stored"] += 1
            _store(connection, record, description, refresh_after_days, dry_run)
        counts["seconds"] = round(time.monotonic() - started, 1)
        metrics["sources"][name] = dict(counts)
        for key, target in (
            ("stored", "stored"),
            ("matched", "matched"),
            ("with_description", "collected_with_description"),
            ("unmatched", "unmatched"),
            ("kept_existing", "kept_existing"),
        ):
            metrics[target] += counts[key]
    if cache_rows and not dry_run:
        connection.executemany(
            """
            INSERT INTO collector_description_cache (source, native_id, url, description, seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (source, native_id, url)
            DO UPDATE SET description = excluded.description, seen_at = excluded.seen_at
            """,
            cache_rows,
        )
        connection.commit()
    metrics.update(cache_metrics)
    metrics["cached_unmatched"] = len(cache_rows)
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--sources", default=DEFAULT_SOURCES,
                        help="fontes separadas por vírgula (padrão: portais com API)")
    parser.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS)
    parser.add_argument("--refresh-after-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true",
                        help="mede o casamento sem gravar no banco")
    args = parser.parse_args(argv)

    import pipeline  # imported late: heavy module, only needed to run

    registry = pipeline.selected_registry(args.sources)
    if not registry:
        print("COLLECTOR_DESCRIPTIONS_METRICS " + json.dumps({"error": "no_sources"}))
        return 1
    connection = description_store.connect(args.db)
    try:
        metrics = ingest(
            connection,
            registry,
            min_chars=max(1, args.min_chars),
            refresh_after_days=max(1, args.refresh_after_days),
            dry_run=args.dry_run,
        )
    finally:
        connection.close()
    print("COLLECTOR_DESCRIPTIONS_METRICS " + json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
