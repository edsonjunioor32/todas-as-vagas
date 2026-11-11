# -*- coding: utf-8 -*-
"""Read-only quality report for the private description store."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from description_quality import assess_row


def _sorted_counts(values: Counter[str]) -> dict[str, int]:
    return {key: int(values[key]) for key in sorted(values)}


def _sample(row: sqlite3.Row, assessment: Any) -> dict[str, Any]:
    return {
        "job_uid": str(row["job_uid"]),
        "source": str(row["source"]),
        "title": str(row["title"]),
        "company": str(row["company"]),
        "url": str(row["url"]),
        "status": str(row["status"]),
        "reason": assessment.reason,
        "character_count": assessment.character_count,
        "content_kind": str(row["content_kind"]),
    }


def build_report(
    connection: sqlite3.Connection,
    *,
    seen_at: str = "",
    refresh_after_days: int = 30,
    sample_limit: int = 5,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a report using SELECTs only; the caller owns the connection."""

    where = " WHERE last_seen_at = ?" if seen_at else ""
    parameters: tuple[Any, ...] = (seen_at,) if seen_at else ()
    rows = connection.execute(
        f"""
        SELECT job_uid, source, native_id, title, company, url, description,
               content_kind, status, http_status, error, checked_at,
               attempts, next_attempt_at, fetched_at
        FROM job_descriptions
        {where}
        ORDER BY source, job_uid
        """,
        parameters,
    ).fetchall()

    limit = max(0, min(int(sample_limit), 50))
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    generated_at = generated_at.astimezone(timezone.utc)

    quality = Counter()
    statuses = Counter()
    content_kinds = Counter()
    sources: dict[str, dict[str, Any]] = {}
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    bytes_total = 0
    character_total = 0
    with_description = 0

    for row in rows:
        assessment = assess_row(
            row,
            now=generated_at,
            stale_after_days=refresh_after_days,
        )
        quality[assessment.level] += 1
        statuses[str(row["status"])] += 1
        content_kinds[str(row["content_kind"])] += 1
        description = str(row["description"] or "")
        bytes_total += len(description.encode("utf-8"))
        character_total += len(description)
        if description:
            with_description += 1

        source = str(row["source"] or "unknown")
        source_report = sources.setdefault(
            source,
            {
                "total": 0,
                "with_description": 0,
                "description_bytes": 0,
                "description_chars": 0,
                "quality": Counter(),
                "statuses": Counter(),
                "content_kinds": Counter(),
            },
        )
        source_report["total"] += 1
        source_report["with_description"] += bool(description)
        source_report["description_bytes"] += len(description.encode("utf-8"))
        source_report["description_chars"] += len(description)
        source_report["quality"][assessment.level] += 1
        source_report["statuses"][str(row["status"])] += 1
        source_report["content_kinds"][str(row["content_kind"])] += 1

        if len(samples[assessment.level]) < limit:
            samples[assessment.level].append(_sample(row, assessment))

    normalized_sources = {}
    for source, value in sorted(sources.items()):
        normalized_sources[source] = {
            "total": int(value["total"]),
            "with_description": int(value["with_description"]),
            "description_bytes": int(value["description_bytes"]),
            "description_chars": int(value["description_chars"]),
            "quality": _sorted_counts(value["quality"]),
            "statuses": _sorted_counts(value["statuses"]),
            "content_kinds": _sorted_counts(value["content_kinds"]),
        }

    return {
        "generated_at": generated_at.isoformat(),
        "seen_at": seen_at,
        "refresh_after_days": int(refresh_after_days),
        "total": len(rows),
        "with_description": with_description,
        "description_bytes": bytes_total,
        "description_chars": character_total,
        "quality": _sorted_counts(quality),
        "statuses": _sorted_counts(statuses),
        "content_kinds": _sorted_counts(content_kinds),
        "sources": normalized_sources,
        "samples": {key: samples[key] for key in sorted(samples)},
    }


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Relatório de qualidade das descrições",
        "",
        f"- Gerado em: {report['generated_at']}",
        f"- Total analisado: {report['total']}",
        f"- Com texto: {report['with_description']}",
        f"- Bytes UTF-8 das descrições: {report['description_bytes']}",
        f"- Caracteres das descrições: {report['description_chars']}",
        "",
        "## Qualidade",
        "",
        "| Categoria | Quantidade |",
        "| --- | ---: |",
    ]
    for key, amount in report["quality"].items():
        lines.append(f"| {key} | {amount} |")

    lines.extend(
        [
            "",
            "## Portais",
            "",
            "| Portal | Total | Com texto | Candidatas completas | Bloqueadas | Vazias |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for source, value in report["sources"].items():
        lines.append(
            f"| {source} | {value['total']} | {value['with_description']} | "
            f"{value['quality'].get('complete_candidate', 0)} | "
            f"{value['quality'].get('blocked', 0)} | "
            f"{value['quality'].get('empty', 0)} |"
        )

    lines.extend(["", "## Amostras", ""])
    for level, rows in report["samples"].items():
        lines.extend([f"### {level}", ""])
        for row in rows:
            lines.append(
                f"- {row['title'] or '(sem título)'} — {row['company'] or '(sem empresa)'} "
                f"({row['source']}); motivo: {row['reason']}; {row['url']}"
            )
        if not rows:
            lines.append("- Nenhuma amostra.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _read_only_connection(path: str | Path) -> sqlite3.Connection:
    target = Path(path).expanduser().resolve()
    connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.row_factory = sqlite3.Row
    return connection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gera relatório somente leitura do SQLite privado."
    )
    parser.add_argument("--db", required=True, help="caminho do descriptions.sqlite3")
    parser.add_argument("--seen-at", default="")
    parser.add_argument("--refresh-after-days", type=int, default=30)
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args(argv)

    try:
        connection = _read_only_connection(args.db)
    except sqlite3.Error as error:
        parser.error(f"não foi possível abrir o banco em modo somente leitura: {error}")
        return 2
    try:
        report = build_report(
            connection,
            seen_at=args.seen_at,
            refresh_after_days=args.refresh_after_days,
            sample_limit=args.sample_limit,
        )
    finally:
        connection.close()

    sys.stdout.write(render_json(report) if args.format == "json" else render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
