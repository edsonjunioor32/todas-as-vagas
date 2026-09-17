# -*- coding: utf-8 -*-
"""Private, resumable storage for vacancy descriptions.

This module deliberately lives outside the public snapshot flow. The SQLite
file is expected to be placed on the VPS (or another private disk), never in
docs/data or on the public-data branch.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA_VERSION = 1
PARSER_VERSION = "description-crawler-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _after(seconds: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=max(0, int(seconds)))
    ).replace(microsecond=0).isoformat()


def _description_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def connect(path: str | Path) -> sqlite3.Connection:
    """Open and initialize the private store with safe defaults."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS job_descriptions (
            job_uid TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            native_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            company TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            description_sha256 TEXT NOT NULL DEFAULT '',
            content_kind TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            http_status INTEGER,
            error TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            checked_at TEXT NOT NULL DEFAULT '',
            fetched_at TEXT NOT NULL DEFAULT '',
            next_attempt_at TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_job_descriptions_pending
            ON job_descriptions(status, next_attempt_at, last_seen_at);

        CREATE INDEX IF NOT EXISTS idx_job_descriptions_source
            ON job_descriptions(source, status);

        CREATE INDEX IF NOT EXISTS idx_job_descriptions_hash
            ON job_descriptions(description_sha256);
        """
    )
    # FTS5 is part of the standard Python SQLite build on the VPS. Keep a
    # graceful fallback so collection still works if a minimal build omits it.
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS job_descriptions_fts
            USING fts5(
                job_uid UNINDEXED,
                source,
                title,
                company,
                description,
                url UNINDEXED
            )
            """
        )
    except sqlite3.OperationalError:
        pass
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    return connection


def _job_uid(job: dict) -> str:
    source = str(job.get("source") or "unknown").strip()
    native_id = str(job.get("native_id") or "").strip()
    url = str(job.get("url") or "").strip()
    return f"{source}:{native_id or url}"


def sync_manifest(
    connection: sqlite3.Connection,
    jobs: list[dict],
    *,
    seen_at: str | None = None,
) -> tuple[str, int]:
    """Insert/update the current public manifest without fetching descriptions."""
    seen_at = seen_at or utc_now()
    rows = []
    for job in jobs:
        url = str(job.get("url") or "").strip()
        if not url:
            continue
        rows.append(
            (
                _job_uid(job),
                str(job.get("source") or "unknown").strip(),
                str(job.get("native_id") or "").strip(),
                str(job.get("title") or "").strip()[:500],
                str(job.get("company") or "").strip()[:500],
                url,
                seen_at,
            )
        )
    connection.executemany(
        """
        INSERT INTO job_descriptions (
            job_uid, source, native_id, title, company, url,
            first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_uid) DO UPDATE SET
            source=excluded.source,
            native_id=excluded.native_id,
            title=excluded.title,
            company=excluded.company,
            url=excluded.url,
            last_seen_at=excluded.last_seen_at
        """,
        [
            (*row[:6], row[6], row[6])
            for row in rows
        ],
    )
    connection.commit()
    return seen_at, len(rows)


def pending_jobs(
    connection: sqlite3.Connection,
    *,
    seen_at: str,
    refresh_after_days: int = 30,
    force: bool = False,
    source: str = "",
) -> list[sqlite3.Row]:
    """Return current jobs that are new or due for a refresh."""
    source_clause = ""
    parameters: list[object] = [seen_at]
    if source:
        source_clause = " AND source = ?"
        parameters.append(source)
    now = utc_now()
    refresh_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max(0, refresh_after_days))
    ).replace(microsecond=0).isoformat()
    if force:
        due_clause = "1 = 1"
    else:
        due_clause = """
            (
                (
                    description = ''
                    AND status <> 'robots_denied'
                    AND (next_attempt_at = '' OR next_attempt_at <= ?)
                )
                OR (
                    description <> ''
                    AND checked_at <> ''
                    AND checked_at <= ?
                )
            )
        """
        parameters.extend([now, refresh_cutoff])
    parameters.append(seen_at)
    return connection.execute(
        f"""
        SELECT job_uid, source, native_id, title, company, url, description,
               status, attempts, checked_at
        FROM job_descriptions
        WHERE last_seen_at = ? {source_clause}
          AND {due_clause}
        ORDER BY CASE WHEN description = '' THEN 0 ELSE 1 END,
                 source, job_uid
        """,
        parameters,
    ).fetchall()


def _fts_upsert(connection: sqlite3.Connection, job: sqlite3.Row) -> None:
    try:
        connection.execute(
            "DELETE FROM job_descriptions_fts WHERE job_uid = ?",
            (job["job_uid"],),
        )
        if job["description"]:
            connection.execute(
                """
                INSERT INTO job_descriptions_fts
                    (job_uid, source, title, company, description, url)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job["job_uid"],
                    job["source"],
                    job["title"],
                    job["company"],
                    job["description"],
                    job["url"],
                ),
            )
    except sqlite3.OperationalError:
        # FTS is an optimization for the future matching feature, never a
        # reason to discard a successfully collected description.
        return


def record_success(
    connection: sqlite3.Connection,
    job: sqlite3.Row,
    description: str,
    *,
    content_kind: str,
    http_status: int = 200,
    refresh_after_days: int = 30,
) -> None:
    now = utc_now()
    description = str(description or "").strip()
    connection.execute(
        """
        UPDATE job_descriptions
        SET description = ?,
            description_sha256 = ?,
            content_kind = ?,
            status = 'fetched',
            http_status = ?,
            error = '',
            attempts = 0,
            checked_at = ?,
            fetched_at = ?,
            next_attempt_at = ?,
            parser_version = ?
        WHERE job_uid = ?
        """,
        (
            description,
            _description_hash(description),
            str(content_kind or "unknown")[:40],
            int(http_status),
            now,
            now,
            _after(max(1, refresh_after_days) * 86400),
            PARSER_VERSION,
            job["job_uid"],
        ),
    )
    stored = connection.execute(
        "SELECT * FROM job_descriptions WHERE job_uid = ?",
        (job["job_uid"],),
    ).fetchone()
    if stored:
        _fts_upsert(connection, stored)
    connection.commit()


def record_failure(
    connection: sqlite3.Connection,
    job: sqlite3.Row,
    *,
    status: str,
    error: str = "",
    http_status: int | None = None,
    retry_after_seconds: int = 3600,
    permanent: bool = False,
) -> None:
    """Checkpoint a failed attempt while preserving any older description."""
    previous = connection.execute(
        "SELECT description, attempts FROM job_descriptions WHERE job_uid = ?",
        (job["job_uid"],),
    ).fetchone()
    attempts = int(previous["attempts"] or 0) + 1 if previous else 1
    current_description = str(previous["description"] or "") if previous else ""
    if permanent:
        delay = 30 * 86400
    else:
        delay = min(
            max(60, int(retry_after_seconds)) * (2 ** min(attempts - 1, 5)),
            7 * 86400,
        )
    stored_status = "stale" if current_description else str(status or "error")[:40]
    now = utc_now()
    connection.execute(
        """
        UPDATE job_descriptions
        SET status = ?,
            http_status = ?,
            error = ?,
            attempts = ?,
            checked_at = ?,
            next_attempt_at = ?,
            parser_version = ?
        WHERE job_uid = ?
        """,
        (
            stored_status,
            http_status,
            str(error or "")[:300],
            attempts,
            now,
            _after(delay),
            PARSER_VERSION,
            job["job_uid"],
        ),
    )
    connection.commit()


def stats(connection: sqlite3.Connection) -> dict:
    total, with_description, bytes_total = connection.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN LENGTH(description) > 0 THEN 1 ELSE 0 END),
               COALESCE(SUM(LENGTH(description)), 0)
        FROM job_descriptions
        """
    ).fetchone()
    status_rows = connection.execute(
        """
        SELECT status, COUNT(*) AS amount
        FROM job_descriptions
        GROUP BY status
        ORDER BY status
        """
    ).fetchall()
    return {
        "total": int(total or 0),
        "with_description": int(with_description or 0),
        "bytes": int(bytes_total or 0),
        "statuses": {row["status"]: int(row["amount"]) for row in status_rows},
    }


def search(
    connection: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """Search collected descriptions when the private matching UI is added."""
    query = str(query or "").strip()
    if not query:
        return []
    try:
        return connection.execute(
            """
            SELECT d.job_uid, d.source, d.title, d.company, d.url,
                   d.description, d.content_kind, d.fetched_at
            FROM job_descriptions_fts f
            JOIN job_descriptions d ON d.job_uid = f.job_uid
            WHERE job_descriptions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, max(1, min(int(limit), 100))),
        ).fetchall()
    except sqlite3.OperationalError:
        # Fallback for systems without FTS5. This is intentionally bounded.
        pattern = f"%{query}%"
        return connection.execute(
            """
            SELECT job_uid, source, title, company, url, description,
                   content_kind, fetched_at
            FROM job_descriptions
            WHERE description LIKE ? OR title LIKE ? OR company LIKE ?
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, max(1, min(int(limit), 100))),
        ).fetchall()
