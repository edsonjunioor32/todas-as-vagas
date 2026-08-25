# -*- coding: utf-8 -*-
"""Discover Greenhouse boards that currently advertise jobs in Brazil.

Greenhouse has no public endpoint that enumerates every board token. This
script therefore validates an external discovery catalog against the official
public Job Board API and writes only the much smaller Brazil-relevant catalog
used by the normal collection workflow.
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from sources._common import is_brazil_location


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "data" / "greenhouse_br_companies.json"
DEFAULT_CATALOG = (
    "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/"
    "main/data/greenhouse_companies.json"
)
API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=false"
EXCLUDED = {"stone", "ifoodcarreiras"}  # already collected as named sources

def get_json(url, timeout=20):
    request = Request(url, headers={"User-Agent": "Todas-as-Vagas/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def is_brazilian(job):
    location = str((job.get("location") or {}).get("name") or "")
    # Bare two-letter codes collide with US states (MA, PR, RI, etc.).
    # Discovery must use the same strict location rule as normal collection.
    return is_brazil_location(location)


def validate_board(board, timeout):
    try:
        jobs = get_json(API.format(board=board), timeout=timeout).get("jobs") or []
    except Exception:
        return None
    brazil_jobs = [item for item in jobs if is_brazilian(item)]
    if not brazil_jobs:
        return None
    names = [str(item.get("company_name") or "").strip() for item in brazil_jobs]
    company = next((name for name in names if name), board)
    return {
        "board": board,
        "company": company,
        "brazil_jobs": len(brazil_jobs),
    }


def load_catalog(value):
    if value.startswith(("http://", "https://")):
        payload = get_json(value, timeout=60)
    else:
        with open(value, encoding="utf-8") as handle:
            payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("the discovery catalog must be a JSON list of board tokens")
    return sorted({str(item).strip().lower() for item in payload if str(item).strip()} - EXCLUDED)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    boards = load_catalog(args.catalog)
    print(f"Validando {len(boards)} páginas Greenhouse; mantendo somente vagas brasileiras...")
    found = []
    workers = min(200, max(1, args.workers))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(validate_board, board, max(3, args.timeout)): board
            for board in boards
        }
        for position, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                found.append(result)
                print(f"  + {result['company']} ({result['board']}): {result['brazil_jobs']}")
            if position % 500 == 0:
                print(f"  {position}/{len(boards)} verificadas · {len(found)} brasileiras")

    found.sort(key=lambda item: (item["company"].casefold(), item["board"]))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(boards),
        "company_count": len(found),
        "companies": found,
    }
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"Catálogo brasileiro: {len(found)} empresas · {output}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
