# -*- coding: utf-8 -*-
"""ATS job boards — Greenhouse, Lever and Ashby all expose a public, key-free
JSON board per company. We pull from a curated list of companies (each slug
verified to respond), capped per company so no single board floods the dataset.

Adds named-company variety and depth on top of the aggregators. Extend the lists
below with any company slug that returns jobs on its ATS.
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from ._http import get_json
from ._common import strip_html, iso_date, work_model_label, is_brazil_location, job

PER_COMPANY = 120   # cap for global Lever/Ashby boards

LEVER = ["spotify", "veeva"]
ASHBY = ["openai", "ramp", "notion", "replit", "watershed", "linear"]

HERE = Path(__file__).resolve().parent
GREENHOUSE_BR_CATALOG = HERE.parent / "data" / "greenhouse_br_companies.json"
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=false"
REQUIRED_GREENHOUSE_BOARDS = {"c6bank": "C6 Bank"}
PCD_PATTERN = re.compile(r"\bpcd\b|pessoa(?:s)?\s+com\s+defici", re.I)
def _market(loc):
    t = (loc or "").lower()
    if any(k in t for k in ("bras", "brazil", "são paulo", "sao paulo", "rio de janeiro",
                            "belo horizonte", "curitiba", "porto alegre")):
        return "BR", "BR"
    if any(k in t for k in ("remote", "anywhere", "distributed")):
        return loc, "Global remote"
    return loc, "Global"


def fetch_greenhouse():
    with open(GREENHOUSE_BR_CATALOG, encoding="utf-8") as handle:
        configs = json.load(handle).get("companies") or []
    configured = {str(config.get("board") or "").strip() for config in configs}
    configs.extend(
        {"board": board, "company": company}
        for board, company in REQUIRED_GREENHOUSE_BOARDS.items()
        if board not in configured
    )

    def fetch_board(config):
        board = config["board"]
        payload = get_json(GREENHOUSE_API.format(board=board), timeout=35, retries=2)
        rows = []
        for item in payload.get("jobs") or []:
            loc = str((item.get("location") or {}).get("name") or "").strip()
            if not is_brazil_location(loc):
                continue
            depts = [d.get("name", "") for d in (item.get("departments") or [])]
            metadata = item.get("metadata") or []
            contracts = []
            for field in metadata:
                name = str(field.get("name") or "").strip().rstrip(":").casefold()
                if name not in {"tipo de contrato", "employment type", "contract type"}:
                    continue
                value = field.get("value")
                contracts.extend(value if isinstance(value, list) else [value])
            title = item.get("title", "")
            rows.append(job(
                "greenhouse", item.get("id") or item.get("internal_job_id"),
                title=title,
                company=item.get("company_name") or config.get("company") or board,
                url=item.get("absolute_url", ""),
                work_model=work_model_label(raw=f"{title} {loc}"),
                city=loc,
                country="BR",
                market="BR",
                published_date=iso_date(item.get("first_published") or item.get("updated_at")),
                expires_date=iso_date(item.get("application_deadline")),
                categories=[d for d in depts if d],
                contract_types=[str(value).strip() for value in contracts if str(value or "").strip()],
                pcd=bool(PCD_PATTERN.search(title)),
            ))
        return rows

    out = []
    workers = min(20, max(1, int(os.environ.get("GREENHOUSE_WORKERS", "12"))))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_board, config): config for config in configs}
        for future in as_completed(futures):
            config = futures[future]
            try:
                out.extend(future.result())
            except Exception as error:
                print(f"    [gh:{config.get('board')}] {str(error)[:60]}")
    return out


def fetch_lever():
    out = []
    for c in LEVER:
        try:
            jobs = get_json(f"https://api.lever.co/v0/postings/{c}?mode=json")
        except Exception as e:
            print(f"    [lever:{c}] {str(e)[:40]}"); continue
        for j in (jobs if isinstance(jobs, list) else [])[:PER_COMPANY]:
            cats = j.get("categories", {}) or {}
            loc = cats.get("location", "")
            country, market = _market(loc)
            out.append(job("lever", j.get("id"),
                title=j.get("text", ""), company=c.title(),
                url=j.get("hostedUrl", ""), work_model=work_model_label(raw=cats.get("commitment", "") + " " + loc),
                city=loc, country=country, market=market,
                published_date=iso_date(j.get("createdAt")),
                categories=[cats.get("department") or cats.get("team") or ""]))
        time.sleep(0.2)
    return out


def fetch_ashby():
    out = []
    for c in ASHBY:
        try:
            jobs = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{c}").get("jobs", [])
        except Exception as e:
            print(f"    [ashby:{c}] {str(e)[:40]}"); continue
        for j in jobs[:PER_COMPANY]:
            loc = j.get("location", "") or j.get("locationName", "")
            country, market = _market(loc)
            remote = bool(j.get("isRemote"))
            out.append(job("ashby", j.get("id") or j.get("jobId"),
                title=j.get("title", ""), company=c.title(),
                url=j.get("jobUrl") or j.get("applyUrl", ""),
                work_model="remote" if remote else work_model_label(raw=loc),
                city=loc, country=country, market="Global remote" if remote else market,
                published_date=iso_date(j.get("publishedAt")),
                categories=[j.get("department", "") or j.get("teamName", "")]))
        time.sleep(0.2)
    return out
