# -*- coding: utf-8 -*-
"""SQLite history plus a compact, public-safe JSON snapshot."""
import calendar
import json
import os
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_uid          TEXT PRIMARY KEY,
    source           TEXT,
    title            TEXT,
    company          TEXT,
    area             TEXT,
    seniority        TEXT,
    work_model       TEXT,
    city             TEXT,
    state            TEXT,
    country          TEXT,
    market           TEXT,
    salary_min       REAL,
    salary_max       REAL,
    salary_currency  TEXT,
    published_date   TEXT,
    expires_date     TEXT,
    first_seen_date  TEXT,
    last_seen_date   TEXT,
    url              TEXT,
    skills           TEXT,
    contract_types   TEXT,
    pcd              INTEGER DEFAULT 0,
    blind_selection  INTEGER DEFAULT 0,
    description      TEXT DEFAULT '',
    dedupe_key       TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON jobs(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_jobs_seen ON jobs(last_seen_date);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
"""

MIGRATION_COLUMNS = {
    "expires_date": "TEXT",
    "contract_types": "TEXT",
    "pcd": "INTEGER DEFAULT 0",
    "blind_selection": "INTEGER DEFAULT 0",
    "description": "TEXT DEFAULT ''",
}

_STOP = re.compile(
    r"\b(pleno|senior|junior|especialista|analista|estagi\w*|trainee|aprendiz|"
    r"remoto|remote|hibrido|presencial|home\s*office|jr|sr|pl|i{1,3}|\d+)\b",
    re.I,
)


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode().lower()
    text = _STOP.sub(" ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def dedupe_key(title, company):
    return f"{_norm(title)}|{_norm(company)}"


def months_ago(value, months):
    """Return the same day ``months`` earlier, clamped to the target month."""
    year = value.year
    month = value.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def publication_cutoff(today=None, max_age_months=3):
    today_value = date.fromisoformat(today) if isinstance(today, str) else (today or date.today())
    return months_ago(today_value, max(0, max_age_months)).isoformat()


def connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    for name, definition in MIGRATION_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
    conn.commit()
    return conn


def upsert(conn, jobs, today=None):
    today = today or date.today().isoformat()
    for item in jobs:
        uid = f"{item['source']}:{item['native_id'] or item['url']}"
        skills = " · ".join(dict.fromkeys(item.get("skills") or []))[:500]
        contracts = " · ".join(dict.fromkeys(item.get("contract_types") or []))[:240]
        row = (
            uid, item["source"], item["title"], item["company"], item.get("area", ""),
            item.get("seniority", ""), item.get("work_model", ""), item.get("city", ""),
            item.get("state", ""), item.get("country", ""), item.get("market", ""),
            item.get("salary_min"), item.get("salary_max"), item.get("salary_currency"),
            item.get("published_date", ""), item.get("expires_date", ""), today, today,
            item.get("url", ""), skills, contracts, int(bool(item.get("pcd"))),
            int(bool(item.get("blind_selection"))), "", dedupe_key(item["title"], item["company"]),
        )
        conn.execute("""
            INSERT INTO jobs (
                job_uid, source, title, company, area, seniority, work_model, city,
                state, country, market, salary_min, salary_max, salary_currency,
                published_date, expires_date, first_seen_date, last_seen_date, url,
                skills, contract_types, pcd, blind_selection, description, dedupe_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_uid) DO UPDATE SET
                last_seen_date=excluded.last_seen_date,
                title=excluded.title, company=excluded.company, area=excluded.area,
                seniority=excluded.seniority, work_model=excluded.work_model,
                city=excluded.city, state=excluded.state, country=excluded.country,
                market=excluded.market, salary_min=excluded.salary_min,
                salary_max=excluded.salary_max, salary_currency=excluded.salary_currency,
                published_date=excluded.published_date, expires_date=excluded.expires_date,
                url=excluded.url, skills=excluded.skills,
                contract_types=excluded.contract_types, pcd=excluded.pcd,
                blind_selection=excluded.blind_selection, description='',
                dedupe_key=excluded.dedupe_key
        """, row)
    conn.commit()


def prune(conn, keep_days=120, today=None, max_age_months=3):
    today = today or date.today().isoformat()
    seen_cutoff = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    age_cutoff = publication_cutoff(today, max_age_months)
    cursor = conn.execute("""
        DELETE FROM jobs
        WHERE last_seen_date < ?
           OR COALESCE(NULLIF(published_date, ''), first_seen_date) < ?
    """, (seen_cutoff, age_cutoff))
    conn.commit()
    return cursor.rowcount


def export_snapshot(conn, out_path, fresh_days=3, today=None, max_jobs=50000,
                    max_age_months=3,
                    max_raw_mb=18, source_counts=None, failed_sources=None):
    """Export jobs seen in a recent successful collection window.

    A three-day tolerance prevents a temporary portal outage from instantly
    removing all of that portal's vacancies from the public page.
    """
    today = today or date.today().isoformat()
    cutoff = (date.fromisoformat(today) - timedelta(days=max(0, fresh_days - 1))).isoformat()
    age_cutoff = publication_cutoff(today, max_age_months)
    rows = conn.execute("""
        SELECT source, title, company, area, seniority, work_model, city, state,
               country, market, salary_min, salary_max, salary_currency,
               published_date, first_seen_date, last_seen_date, expires_date,
               url, skills, dedupe_key, pcd, blind_selection, contract_types
        FROM jobs
        WHERE last_seen_date >= ?
          AND (expires_date IS NULL OR expires_date = '' OR expires_date >= ?)
          AND COALESCE(NULLIF(published_date, ''), first_seen_date) >= ?
        ORDER BY MAX(COALESCE(published_date,''), first_seen_date) DESC,
                 last_seen_date DESC
        LIMIT ?
    """, (cutoff, today, age_cutoff, max_jobs)).fetchall()

    portal_sets = {}
    snapshot_source_counts = {}
    for row in rows:
        portal_sets.setdefault(row[19], set()).add(row[0])
        snapshot_source_counts[row[0]] = snapshot_source_counts.get(row[0], 0) + 1

    dictionaries = {name: [] for name in (
        "source", "company", "area", "seniority", "work_model", "market",
        "country", "currency"
    )}
    indexes = {name: {} for name in dictionaries}

    def code(name, value):
        value = value or ""
        if value not in indexes[name]:
            indexes[name][value] = len(dictionaries[name])
            dictionaries[name].append(value)
        return indexes[name][value]

    columns = {name: [] for name in (
        "title", "src", "cmp", "area", "sen", "wm", "mk", "co", "city",
        "pub", "seen", "exp", "url", "np", "sk", "smin", "smax", "cur",
        "pcd", "blind", "ct"
    )}
    for row in rows:
        (source, title, company, area, seniority, work_model, city, state, country,
         market, salary_min, salary_max, currency, published, first_seen, last_seen,
         expires, url, skills, duplicate, pcd, blind, contracts) = row
        columns["title"].append(title or "")
        columns["src"].append(code("source", source))
        columns["cmp"].append(code("company", company))
        columns["area"].append(code("area", area))
        columns["sen"].append(code("seniority", seniority))
        columns["wm"].append(code("work_model", work_model))
        columns["mk"].append(code("market", market))
        columns["co"].append(code("country", country))
        columns["city"].append(city or state or "")
        columns["pub"].append((published or first_seen or "")[:10])
        columns["seen"].append((last_seen or first_seen or "")[:10])
        columns["exp"].append((expires or "")[:10])
        columns["url"].append(url or "")
        columns["np"].append(len(portal_sets.get(duplicate, {source})))
        columns["sk"].append(skills or "")
        columns["smin"].append(round(salary_min, 2) if salary_min else None)
        columns["smax"].append(round(salary_max, 2) if salary_max else None)
        columns["cur"].append(code("currency", currency))
        columns["pcd"].append(1 if pcd else 0)
        columns["blind"].append(1 if blind else 0)
        columns["ct"].append(contracts or "")

    source_counts = source_counts or {}
    payload = {
        "schema_version": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_date": today,
        "fresh_days": fresh_days,
        "max_age_months": max_age_months,
        "publication_cutoff": age_cutoff,
        "count": len(rows),
        "total_base": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
        "source_counts": dict(sorted(snapshot_source_counts.items())),
        "collected_source_counts": source_counts,
        "failed_sources": failed_sources or [],
        "companies": len({row[2] for row in rows if row[2]}),
        "pcd_count": sum(1 for row in rows if row[20]),
        "dict": dictionaries,
        "jobs": columns,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    size_mb = len(text.encode("utf-8")) / 1_048_576
    if size_mb > max_raw_mb:
        raise RuntimeError(
            f"public snapshot is {size_mb:.1f} MB, above the {max_raw_mb} MB safety cap"
        )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    temporary = f"{out_path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, out_path)
    return len(rows), size_mb
