# -*- coding: utf-8 -*-
"""ATS job boards — Greenhouse, Lever and Ashby all expose a public, key-free
JSON board per company. We pull from a curated list of companies (each slug
verified to respond), capped per company so no single board floods the dataset.

Adds named-company variety and depth on top of the aggregators. Extend the lists
below with any company slug that returns jobs on its ATS.
"""
import time
from ._http import get_json
from ._common import strip_html, iso_date, work_model_label, job

PER_COMPANY = 120   # cap so one big board can't dominate

# Verified slugs (return >0 jobs). BR-relevant: ebanx, wildlifestudios, thoughtworks.
GREENHOUSE = ["stripe", "databricks", "datadog", "cloudflare", "airbnb", "coinbase",
              "brex", "pinterest", "reddit", "elastic", "gitlab", "asana", "samsara",
              "thoughtworks", "discord", "dropbox", "ebanx", "wildlifestudios"]
LEVER = ["spotify", "veeva"]
ASHBY = ["openai", "ramp", "notion", "replit", "watershed", "linear"]


def _market(loc):
    t = (loc or "").lower()
    if any(k in t for k in ("bras", "brazil", "são paulo", "sao paulo", "rio de janeiro",
                            "belo horizonte", "curitiba", "porto alegre")):
        return "BR", "BR"
    if any(k in t for k in ("remote", "anywhere", "distributed")):
        return loc, "Global remote"
    return loc, "Global"


def fetch_greenhouse():
    out = []
    for c in GREENHOUSE:
        try:
            jobs = get_json(f"https://boards-api.greenhouse.io/v1/boards/{c}/jobs?content=false").get("jobs", [])
        except Exception as e:
            print(f"    [gh:{c}] {str(e)[:40]}"); continue
        for j in jobs[:PER_COMPANY]:
            loc = (j.get("location", {}) or {}).get("name", "")
            country, market = _market(loc)
            depts = [d.get("name", "") for d in (j.get("departments") or [])]
            out.append(job("greenhouse", j.get("id"),
                title=j.get("title", ""), company=c.replace("wildlifestudios", "Wildlife Studios").title(),
                url=j.get("absolute_url", ""), work_model=work_model_label(raw=loc),
                city=loc, country=country, market=market,
                published_date=iso_date(j.get("updated_at") or j.get("first_published")),
                categories=[d for d in depts if d]))
        time.sleep(0.2)
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
