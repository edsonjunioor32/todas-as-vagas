# -*- coding: utf-8 -*-
"""Accenture Brazil jobs from the public API used by its official catalog."""
import json
import re

from ._common import iso_date, job, strip_html, work_model_label
from ._http import post_form_json


API_URL = "https://www.accenture.com/api/accenture/elastic/findjobs"
DETAIL_BASE = "https://www.accenture.com/br-pt/careers/jobdetails"
PAGE_SIZE = 200
MAX_PAGES = 10
MIN_EXPECTED_JOBS = 20

PCD_PATTERN = re.compile(r"\bpcd\b|pessoa(?:s)?\s+com\s+defici", re.I)
LEVEL_MAP = {
    "early career": "Júnior/Assistente",
    "mid-level": "Pleno",
    "senior level": "Sênior/Especialista",
}


def _request_page(start_index):
    return post_form_json(
        API_URL,
        {
            "startIndex": start_index,
            "maxResultSize": PAGE_SIZE,
            "jobKeyword": "",
            "jobCountry": "Brasil",
            "jobLanguage": "pt-br",
            "countrySite": "br-pt",
            "sortBy": 2,
            "searchType": "vectorSearch",
            "enableQueryBoost": "true",
            "minScore": "0.6",
            "getFeedbackJudgmentEnabled": "true",
            "useCleanEmbedding": "true",
            "score": "true",
            "totalHits": "true",
            "debugQuery": "false",
            "jobFilters": json.dumps([], separators=(",", ":")),
        },
        headers={"Referer": "https://www.accenture.com/br-pt/careers/jobsearch"},
        timeout=45,
        retries=3,
    )


def _values(value):
    if isinstance(value, list):
        entries = value
    elif value in (None, ""):
        entries = []
    else:
        entries = [value]
    return list(dict.fromkeys(str(entry).strip() for entry in entries if str(entry).strip()))


def _work_model(item, locations, description):
    model = work_model_label(raw=item.get("remoteType"))
    if model:
        return model
    model = work_model_label(raw=f"{item.get('title', '')} {description}")
    if model:
        return model
    # Global dashboard rule: Brazil without a city is remote; a named city is
    # on-site when the source supplies no explicit workplace arrangement.
    meaningful = [
        value for value in locations
        if value.casefold() not in {"br", "brasil", "brazil"}
    ]
    return "on-site" if meaningful else "remote"


def _display_location(locations, work_model):
    if not locations or all(
        value.casefold() in {"br", "brasil", "brazil"} for value in locations
    ):
        return "Brasil"
    if work_model == "remote" and len(locations) > 1:
        return "Brasil"
    if len(locations) == 1:
        return locations[0]
    visible = " · ".join(locations[:3])
    return f"{visible} · +{len(locations) - 3} localidades" if len(locations) > 3 else visible


def _normalize(item):
    guid = str(item.get("guid") or "").strip()
    if str(item.get("country") or "").strip().casefold() != "brasil":
        return None
    if not guid.endswith("_pt-br"):
        return None

    title = str(item.get("title") or "").strip()
    locations = _values(item.get("location"))
    description = strip_html(
        " ".join(
            str(item.get(field) or "")
            for field in (
                "jobDescriptionClean",
                "qualificationClean",
                "additionalInformation",
            )
        )
    )
    work_model = _work_model(item, locations, description)
    raw_url = str(item.get("jobDetailUrl") or "")
    url = raw_url.replace("{0}", "br-pt")
    if not url.startswith(DETAIL_BASE):
        return None

    categories = _values(item.get("jobFamilyGroup"))
    categories += _values(item.get("businessArea"))
    categories += _values(item.get("function"))
    categories = list(dict.fromkeys(categories))
    skills = _values(item.get("skill"))
    skills += _values(item.get("mustHaveSkills"))
    skills += _values(item.get("goodToHaveSkills"))
    skills = list(dict.fromkeys(skills))[:12]
    raw_level = str(item.get("jobTypeDescription") or "").strip()
    level = LEVEL_MAP.get(raw_level.casefold(), raw_level)

    return job(
        "accenture",
        item.get("requisitionId") or guid.removesuffix("_pt-br"),
        title=title,
        company="Accenture",
        url=url,
        work_model=work_model,
        city=_display_location(locations, work_model),
        country="BR",
        market="BR",
        published_date=iso_date(item.get("updateDate")),
        skills=skills,
        description=description,
        levels=[level] if level else [],
        categories=categories,
        pcd=bool(PCD_PATTERN.search(f"{title} {description[:1000]}")),
    )


def fetch():
    first = _request_page(0)
    total_hits = first.get("totalHits") or {}
    total = int(total_hits.get("total") or 0)
    raw_rows = list(first.get("data") or [])

    page = 1
    while len(raw_rows) < total and page < MAX_PAGES:
        payload = _request_page(page * PAGE_SIZE)
        batch = payload.get("data") or []
        if not batch:
            break
        raw_rows.extend(batch)
        page += 1

    unique = {}
    for item in raw_rows:
        guid = str(item.get("guid") or "").strip()
        if guid:
            unique[guid] = item
    if total and len(unique) < total:
        raise RuntimeError(
            f"Accenture returned {len(unique)} of {total} jobs; refusing a partial catalog"
        )

    rows = []
    for item in unique.values():
        normalized = _normalize(item)
        if normalized:
            rows.append(normalized)
    if len(rows) < MIN_EXPECTED_JOBS:
        raise RuntimeError(
            f"Accenture returned only {len(rows)} verified Brazil jobs; refusing a partial catalog"
        )
    return rows
