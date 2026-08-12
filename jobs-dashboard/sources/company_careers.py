# -*- coding: utf-8 -*-
"""Company career pages backed by Greenhouse's public Job Board API.

Stone and iFood are kept as named sources in the dashboard instead of being
folded into the generic Greenhouse source. This lets visitors filter each
company directly while applications still open on the official job page.
"""
import html
import re

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

BOARDS = {
    "stone": {
        "board": "stone",
        "company": "Stone",
    },
    "ifood": {
        "board": "ifoodcarreiras",
        "company": "iFood",
    },
}

PCD_PATTERN = re.compile(r"\bpcd\b|pessoa(?:s)?\s+com\s+defici", re.I)
WORKPLACE_PREFIX = re.compile(
    r"^\s*(?:remote|remoto|hybrid|h[ií]brido|on[- ]?site|presencial)\s*[,;/|–—-]+\s*",
    re.I,
)


def _location(value, title=""):
    """Keep useful cities while removing a leading workplace label."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = WORKPLACE_PREFIX.sub("", text)
    parts = [part.strip() for part in re.split(r"\s*[;|]\s*", text) if part.strip()]
    if parts:
        return " · ".join(dict.fromkeys(parts))
    title_match = re.search(
        r"\|\s*([A-Za-zÀ-ÿ .'-]+?)\s*/\s*([A-Z]{2})\b",
        str(title or ""),
    )
    if title_match and title_match.group(1).strip().casefold() not in {
        "híbrido", "hibrido", "presencial", "remoto",
    }:
        return f"{title_match.group(1).strip()}, {title_match.group(2)}"
    return ""


def _metadata_values(metadata, *wanted_names):
    wanted = {name.casefold() for name in wanted_names}
    values = []
    for item in metadata or []:
        name = str(item.get("name") or "").strip().rstrip(":").casefold()
        value = item.get("value")
        if name not in wanted or value in (None, ""):
            continue
        if isinstance(value, list):
            values.extend(str(entry).strip() for entry in value if str(entry).strip())
        elif str(value).strip():
            values.append(str(value).strip())
    return list(dict.fromkeys(values))


def _work_model(title, location, description):
    workplace = work_model_label(raw=f"{title} {location}")
    if workplace:
        return workplace
    match = re.search(
        r"(?:modelo|modalidade|formato)\s+(?:de\s+)?trabalho.{0,100}",
        description,
        re.I,
    )
    return work_model_label(raw=match.group(0) if match else "")


def _normalize(source, config, item):
    raw_location = (item.get("location") or {}).get("name", "")
    title = item.get("title", "")
    location = _location(raw_location, title)
    description = strip_html(html.unescape(item.get("content", "")))
    workplace = _work_model(title, raw_location, description)
    departments = [
        str(department.get("name") or "").strip()
        for department in item.get("departments") or []
        if str(department.get("name") or "").strip()
    ]
    contracts = _metadata_values(
        item.get("metadata"),
        "tipo de contrato",
        "employment type",
        "contract type",
    )
    keywords = _metadata_values(item.get("metadata"), "keywords", "palavras-chave")
    affirmative_text = f"{title} {description[:700]}"

    return job(
        source,
        item.get("id") or item.get("internal_job_id") or item.get("absolute_url"),
        title=title,
        company=config["company"],
        url=item.get("absolute_url", ""),
        work_model=workplace,
        city=location,
        country="BR",
        market="BR",
        published_date=iso_date(item.get("first_published") or item.get("updated_at")),
        expires_date=iso_date(item.get("application_deadline")),
        skills=keywords[:12],
        description=description,
        categories=departments,
        contract_types=contracts,
        pcd=bool(PCD_PATTERN.search(affirmative_text)),
    )


def _fetch(source):
    config = BOARDS[source]
    payload = get_json(API.format(board=config["board"]), timeout=45, retries=3)
    rows = payload.get("jobs") or []
    return [_normalize(source, config, item) for item in rows]


def fetch_stone():
    return _fetch("stone")


def fetch_ifood():
    return _fetch("ifood")
