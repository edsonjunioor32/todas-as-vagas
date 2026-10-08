"""Review-only JobSpy MCP suggestions for vacancies with missing descriptions.

An alternative listing is not proof that it is the same vacancy. This tool
never writes to the SQLite store and never auto-publishes a description.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3

from description_recovery import _tokens


def match_score(original: dict, candidate: dict) -> float:
    title = _tokens(original.get("title", ""))
    other_title = _tokens(candidate.get("title", ""))
    company = _tokens(original.get("company", ""))
    other_company = _tokens(candidate.get("company", ""))
    if not title or not other_title or not company or not other_company:
        return 0.0
    title_overlap = len(title & other_title) / len(title | other_title)
    company_overlap = len(company & other_company) / len(company | other_company)
    return round(0.7 * title_overlap + 0.3 * company_overlap, 3)


async def suggestions(job: dict, *, sites: list[str], location: str) -> list[dict]:
    from jobspy_mcp.server import search_jobs

    result = await search_jobs(
        site_name=sites,
        search_term=job["title"],
        location=location,
        country_indeed="brazil",
        results_wanted=5,
        linkedin_fetch_description=False,
    )
    if not isinstance(result, dict) or result.get("error"):
        return []
    output = []
    for candidate in result.get("jobs") or []:
        if not isinstance(candidate, dict):
            continue
        score = match_score(job, candidate)
        if score < 0.8:
            continue
        output.append({
            "title": candidate.get("title"),
            "company": candidate.get("company"),
            "url": candidate.get("job_url") or candidate.get("job_url_direct"),
            "description_chars": len(str(candidate.get("description") or "")),
            "similarity": score,
            "review_required": True,
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--source", default="")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--location", default="Brazil")
    parser.add_argument("--sites", nargs="+", default=["indeed", "google"],
                        choices=["indeed", "google", "linkedin", "glassdoor"])
    args = parser.parse_args()
    if not 1 <= args.limit <= 10:
        parser.error("--limit deve ficar entre 1 e 10")
    connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT job_uid, source, title, company, url FROM job_descriptions
               WHERE description = '' AND status IN ('no_description', 'http_404', 'http_403')
                 AND (? = '' OR source = ?)
               ORDER BY checked_at DESC LIMIT ?""",
            (args.source, args.source, args.limit),
        ).fetchall()
    finally:
        connection.close()
    for row in rows:
        job = dict(row)
        try:
            found = asyncio.run(suggestions(job, sites=args.sites, location=args.location))
        except ImportError as error:
            raise SystemExit("jobspy-mcp não está instalado no Python isolado") from error
        print(json.dumps({
            "job_uid": job["job_uid"], "title": job["title"],
            "company": job["company"], "original_url": job["url"],
            "suggestions": found,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
