# -*- coding: utf-8 -*-
"""SQLite history plus a compact, public-safe JSON snapshot."""
import calendar
import json
import os
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TIMEZONE = ZoneInfo("America/Fortaleza")

# SmartRecruiters keeps DBC's public postings active while exposing their
# original release date. This source-specific exception is shared by the
# collector and the snapshot validator so the same active-feed rule is used
# end to end.
ACTIVE_PUBLIC_FEED_SOURCES = {"dbccompany"}

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


def local_today():
    return datetime.now(LOCAL_TIMEZONE).date()


def publication_cutoff(today=None, max_age_months=2):
    today_value = date.fromisoformat(today) if isinstance(today, str) else (today or local_today())
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
    today = today or local_today().isoformat()

    def values():
        for item in jobs:
            uid = f"{item['source']}:{item['native_id'] or item['url']}"
            skills = " · ".join(dict.fromkeys(item.get("skills") or []))[:500]
            contracts = " · ".join(dict.fromkeys(item.get("contract_types") or []))[:240]
            yield (
                uid, item["source"], item["title"], item["company"], item.get("area", ""),
                item.get("seniority", ""), item.get("work_model", ""), item.get("city", ""),
                item.get("state", ""), item.get("country", ""), item.get("market", ""),
                item.get("salary_min"), item.get("salary_max"), item.get("salary_currency"),
                item.get("published_date", ""), item.get("expires_date", ""), today, today,
                item.get("url", ""), skills, contracts, int(bool(item.get("pcd"))),
                int(bool(item.get("blind_selection"))), "",
                dedupe_key(item["title"], item["company"]),
            )

    conn.executemany("""
        INSERT INTO jobs (
            job_uid, source, title, company, area, seniority, work_model, city,
            state, country, market, salary_min, salary_max, salary_currency,
            published_date, expires_date, first_seen_date, last_seen_date, url,
            skills, contract_types, pcd, blind_selection, description, dedupe_key
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(job_uid) DO UPDATE SET
            last_seen_date=excluded.last_seen_date,
            title=excluded.title, company=excluded.company, area=excluded.area,
            seniority=excluded.seniority,
            work_model=COALESCE(NULLIF(excluded.work_model, ''), jobs.work_model),
            city=excluded.city, state=excluded.state, country=excluded.country,
            market=excluded.market, salary_min=excluded.salary_min,
            salary_max=excluded.salary_max, salary_currency=excluded.salary_currency,
            published_date=excluded.published_date, expires_date=excluded.expires_date,
            url=excluded.url, skills=excluded.skills,
            contract_types=excluded.contract_types, pcd=excluded.pcd,
            blind_selection=excluded.blind_selection, description='',
            dedupe_key=excluded.dedupe_key
    """, values())
    conn.commit()



def rewrite_source_urls(conn, source, url_builder):
    """Rewrite stored links for a source after its public URL contract changes."""
    candidates = conn.execute(
        "SELECT job_uid, title, url FROM jobs WHERE source = ?",
        (source,),
    ).fetchall()
    updates = []
    for job_uid, title, current_url in candidates:
        prefix, separator, native_id = str(job_uid or "").partition(":")
        if not separator or prefix != source or not native_id:
            continue
        new_url = str(url_builder(native_id, title) or "").strip()
        if new_url and new_url != str(current_url or "").strip():
            updates.append((new_url, job_uid))
    if updates:
        conn.executemany("UPDATE jobs SET url = ? WHERE job_uid = ?", updates)
        conn.commit()
    return len(updates)


def infer_missing_work_models(conn):
    """Infer the modality only when the portal did not provide it.

    A vacancy whose only location is Brazil is nationwide remote. A Brazilian
    city/location is treated as on-site unless the source explicitly said
    remote or hybrid.
    """
    remote = conn.execute("""
        UPDATE jobs
        SET work_model = 'remote'
        WHERE TRIM(COALESCE(work_model, '')) = ''
          AND (
              LOWER(TRIM(COALESCE(country, ''))) IN ('br', 'brasil', 'brazil')
              OR LOWER(TRIM(COALESCE(market, ''))) = 'br'
          )
          AND (
              LOWER(TRIM(COALESCE(city, ''))) IN (
                  'br', 'brasil', 'brazil', 'remoto', 'remote', 'home office'
              )
              OR (
                  TRIM(COALESCE(city, '')) = ''
                  AND LOWER(TRIM(COALESCE(country, ''))) IN ('brasil', 'brazil')
              )
          )
    """).rowcount
    on_site = conn.execute("""
        UPDATE jobs
        SET work_model = 'on-site'
        WHERE TRIM(COALESCE(work_model, '')) = ''
          AND TRIM(COALESCE(city, '')) <> ''
          AND (
              LOWER(TRIM(COALESCE(country, ''))) IN ('br', 'brasil', 'brazil')
              OR LOWER(TRIM(COALESCE(market, ''))) = 'br'
          )
    """).rowcount
    changed = max(0, remote) + max(0, on_site)
    if changed:
        conn.commit()
    return changed


_BRAZIL_LOCATION_RE = re.compile(
    r"\b(?:brasil|brazil|s[aã]o paulo|rio de janeiro|belo horizonte|bras[ií]lia|"
    r"curitiba|porto alegre|recife|fortaleza|salvador|florian[oó]polis|campinas|"
    r"goi[aâ]nia|vit[oó]ria|jo[aã]o pessoa|manaus|bel[eé]m|natal|macei[oó]|"
    r"aracaju|cuiab[aá]|campo grande|joinville|uberl[aâ]ndia)\b",
    re.I,
)


def purge_greenhouse_non_brazil(conn, current_uids=None):
    """Remove invalid legacy rows without discarding freshly validated jobs.

    The current Greenhouse collector already applies the board-aware Brazil
    filter. Its accepted UIDs are authoritative even when the location is a
    valid value that the generic legacy regex cannot recognize, such as
    ``Barueri/SP`` or ``Remoto``.
    """
    current = {
        str(uid or "").strip()
        for uid in (current_uids or [])
        if str(uid or "").strip()
    }
    candidates = conn.execute(
        "SELECT job_uid, city FROM jobs WHERE source = 'greenhouse'"
    ).fetchall()
    invalid = [
        uid for uid, city in candidates
        if uid not in current and not _BRAZIL_LOCATION_RE.search(str(city or ""))
    ]
    if invalid:
        conn.executemany("DELETE FROM jobs WHERE job_uid = ?", [(uid,) for uid in invalid])
        conn.commit()
    return len(invalid)


def purge_source_rows_not_in_uids(conn, source, current_uids):
    """Remove stale, invalid or legacy-identified rows after a complete catalog succeeds."""
    allowed = {str(uid or "").strip() for uid in current_uids if str(uid or "").strip()}
    if not allowed:
        return 0
    candidates = conn.execute(
        "SELECT job_uid FROM jobs WHERE source = ?", (source,)
    ).fetchall()
    invalid = [uid for (uid,) in candidates if str(uid or "").strip() not in allowed]
    if invalid:
        conn.executemany("DELETE FROM jobs WHERE job_uid = ?", [(uid,) for uid in invalid])
        conn.commit()
    return len(invalid)

def prune(conn, keep_days=120, today=None, max_age_months=2,
          active_feed_sources=None):
    today = today or local_today().isoformat()
    seen_cutoff = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    age_cutoff = publication_cutoff(today, max_age_months)
    active = sorted({str(source).strip() for source in (active_feed_sources or [])
                     if str(source).strip() in ACTIVE_PUBLIC_FEED_SOURCES})
    exemptions = [
        "source = 'gupy' AND COALESCE(NULLIF(expires_date, ''), '') >= ?",
    ]
    active_params = []
    if active:
        placeholders = ", ".join("?" for _ in active)
        exemptions.insert(0, f"source IN ({placeholders})")
        active_params.extend(active)
    publication_exemption = " OR ".join(f"({item})" for item in exemptions)
    cursor = conn.execute(f"""
        DELETE FROM jobs
        WHERE last_seen_date < ?
           OR (
               COALESCE(NULLIF(published_date, ''), first_seen_date) < ?
               AND NOT ({publication_exemption})
           )
           OR (source = 'greenhouse' AND COALESCE(market, '') <> 'BR')
    """, (seen_cutoff, age_cutoff, *active_params, today))
    conn.commit()
    return cursor.rowcount


def export_snapshot(conn, out_path, fresh_days=3, today=None, max_jobs=50000,
                    max_age_months=2,
                    max_raw_mb=18, source_counts=None, failed_sources=None):
    """Export jobs seen in a recent successful collection window.

    A three-day tolerance prevents a temporary portal outage from instantly
    removing all of that portal's vacancies from the public page. When a
    source explicitly failed, its last valid rows remain eligible until the
    normal publication-age cutoff instead of disappearing after three days.
    """
    today = today or local_today().isoformat()
    cutoff = (date.fromisoformat(today) - timedelta(days=max(0, fresh_days - 1))).isoformat()
    age_cutoff = publication_cutoff(today, max_age_months)
    failed = sorted({str(source).strip() for source in (failed_sources or []) if str(source).strip()})
    failed_clause = ""
    failed_params = []
    if failed:
        placeholders = ", ".join("?" for _ in failed)
        failed_clause = f" OR source IN ({placeholders})"
        failed_params = failed
    source_counts = source_counts or {}
    # SmartRecruiters exposes DBC postings as active public records while
    # retaining their original 2021 release date. Include that source only
    # when the current collection actually returned rows; a failed/absent
    # source never receives this exception.
    active_feed_sources = [
        source for source in ("dbccompany",)
        if source_counts.get(source, 0) and source not in failed
    ]
    active_feed_clause = ""
    active_feed_params = []
    if active_feed_sources:
        placeholders = ", ".join("?" for _ in active_feed_sources)
        active_feed_clause = f" OR source IN ({placeholders})"
        active_feed_params = active_feed_sources
    rows = conn.execute(f"""
        SELECT source, title, company, area, seniority, work_model, city, state,
               country, market, salary_min, salary_max, salary_currency,
               published_date, first_seen_date, last_seen_date, expires_date,
               url, skills, dedupe_key, pcd, blind_selection, contract_types
        FROM jobs
        WHERE (last_seen_date >= ?{failed_clause})
          AND (expires_date IS NULL OR expires_date = '' OR expires_date >= ?)
          AND COALESCE(NULLIF(market, ''), 'Não informado') <> 'Não informado'
          AND (source <> 'greenhouse' OR market = 'BR')
          AND (
              COALESCE(NULLIF(published_date, ''), first_seen_date) >= ?
              OR (
                  source = 'gupy'
                  AND COALESCE(NULLIF(expires_date, ''), '') >= ?
              )
              {active_feed_clause}
          )
        ORDER BY MAX(COALESCE(published_date,''), first_seen_date) DESC,
                 last_seen_date DESC
        LIMIT ?
    """, (cutoff, *failed_params, today, age_cutoff, today, *active_feed_params, max_jobs)).fetchall()

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
        columns["pub"].append(published or first_seen or "")
        columns["seen"].append((last_seen or first_seen or "")[:10])
        columns["exp"].append((expires or "")[:10])
        columns["url"].append((url or "").replace("http://", "https://", 1))
        columns["np"].append(len(portal_sets.get(duplicate, {source})))
        columns["sk"].append(skills or "")
        columns["smin"].append(round(salary_min, 2) if salary_min else None)
        columns["smax"].append(round(salary_max, 2) if salary_max else None)
        columns["cur"].append(code("currency", currency))
        columns["pcd"].append(1 if pcd else 0)
        columns["blind"].append(1 if blind else 0)
        columns["ct"].append(contracts or "")

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
