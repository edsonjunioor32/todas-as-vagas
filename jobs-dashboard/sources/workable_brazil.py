# -*- coding: utf-8 -*-
"""Public Workable vacancies filtered to Brazil.

The public Jobs By Workable search exposes a key-free JSON endpoint.  It
returns normalized job metadata and the full public description in each page,
so this adapter does not need a browser or detail-page fan-out.
"""
import os
import time
from urllib.parse import urlencode

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json


SEARCH_URL = "https://jobs.workable.com/search?location=Brazil"
API_URL = "https://jobs.workable.com/api/v1/jobs"
LOCATION = "Brazil"
DEFAULT_MAX_PAGES = 100
DEFAULT_PAGE_DELAY = 0.15

_WORKPLACE_MODELS = {
    "remote": "remote",
    "hybrid": "hybrid",
    "on_site": "on-site",
    "onsite": "on-site",
    "on-site": "on-site",
}


def _text(value):
    return str(value or "").strip()


def _page_limit():
    try:
        value = int(os.environ.get("WORKABLE_BRAZIL_MAX_PAGES") or DEFAULT_MAX_PAGES)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_PAGES
    return min(200, max(1, value))


def _page_delay():
    try:
        value = float(os.environ.get("WORKABLE_BRAZIL_PAGE_DELAY") or DEFAULT_PAGE_DELAY)
    except (TypeError, ValueError):
        value = DEFAULT_PAGE_DELAY
    return min(5.0, max(0.0, value))


def _location_fields(item):
    location = item.get("location") or {}
    locations = item.get("locations") or []
    if not isinstance(locations, list):
        locations = [locations]

    visible_locations = [
        _text(value) for value in locations
        if _text(value) and _text(value).upper() != "TELECOMMUTE"
    ]
    fallback = visible_locations[0] if visible_locations else ""

    city = _text(location.get("city"))
    state = _text(location.get("subregion"))
    country_name = _text(location.get("countryName"))

    if not city and fallback:
        parts = [part.strip() for part in fallback.split(",") if part.strip()]
        is_bare_country = bool(parts) and parts[0].casefold() in {"brazil", "brasil"}
        if parts and not is_bare_country:
            city = parts[0]
        if len(parts) >= 2 and not state:
            state = parts[-2] if len(parts) >= 3 else ""
        if not country_name and len(parts) >= 2:
            country_name = parts[-1]
        elif not country_name and is_bare_country:
            country_name = parts[0]

    is_brazil = country_name.casefold() in {"brazil", "brasil"} or any(
        "brazil" in value.casefold() or "brasil" in value.casefold()
        for value in visible_locations
    )
    if not is_brazil:
        # The request itself is scoped to Brazil; this fallback handles the
        # remote records whose API location object has only TELECOMMUTE/Brazil.
        is_brazil = LOCATION.casefold() in " ".join(visible_locations).casefold()

    return {
        "city": city or ("Brasil" if is_brazil else ""),
        "state": state,
        "country": "BR" if is_brazil else country_name,
        "market": "BR" if is_brazil else "",
        "location_text": " ".join(visible_locations),
    }


def _work_model(item, location):
    raw_workplace = _text(item.get("workplace")).casefold()
    if raw_workplace in _WORKPLACE_MODELS:
        return _WORKPLACE_MODELS[raw_workplace]

    raw = " ".join(
        part for part in (
            raw_workplace,
            location.get("location_text", ""),
            " ".join(_text(value) for value in (item.get("locations") or [])),
        ) if part
    )
    return work_model_label(raw=raw) or ""


def _description(item):
    parts = [
        item.get("description"),
        item.get("requirementsSection"),
        item.get("benefitsSection"),
    ]
    if not any(_text(part) for part in parts):
        parts.append(item.get("socialSharingDescription"))
    return strip_html(" ".join(_text(part) for part in parts if _text(part)))


def _contract_types(item):
    value = item.get("employmentType")
    if isinstance(value, list):
        return [_text(part) for part in value if _text(part)]
    return [_text(value)] if _text(value) else []


def _normalize(item):
    if not isinstance(item, dict):
        return None
    native_id = _text(item.get("id")) or _text(item.get("url"))
    title = _text(item.get("title"))
    url = _text(item.get("url"))
    if not native_id or not title or not url:
        return None
    if _text(item.get("state")).casefold() not in {"", "published"}:
        return None

    location = _location_fields(item)
    company = item.get("company") or {}
    company_name = _text(company.get("title")) if isinstance(company, dict) else ""
    department = _text(item.get("department"))

    return job(
        "workable_brazil",
        native_id,
        title=title,
        company=company_name or "Workable",
        url=url,
        work_model=_work_model(item, location),
        city=location["city"],
        state=location["state"],
        country=location["country"],
        market=location["market"],
        published_date=iso_date(item.get("created")),
        description=_description(item),
        categories=[department] if department else [],
        contract_types=_contract_types(item),
    )


def fetch():
    rows = {}
    page_token = ""
    seen_tokens = set()

    for page_number in range(_page_limit()):
        params = {"location": LOCATION}
        if page_token:
            params["pageToken"] = page_token
        url = f"{API_URL}?{urlencode(params)}"
        payload = get_json(
            url,
            headers={"Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8"},
            timeout=45,
            retries=3,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Workable retornou um payload que não é objeto")

        page_jobs = payload.get("jobs") or []
        if not isinstance(page_jobs, list):
            raise RuntimeError("Workable retornou uma lista de vagas inválida")

        for item in page_jobs:
            row = _normalize(item)
            if row:
                rows.setdefault(row["native_id"], row)

        next_token = _text(payload.get("nextPageToken"))
        if not page_jobs or not next_token:
            break
        if next_token in seen_tokens:
            raise RuntimeError("Workable repetiu o cursor de paginação")
        seen_tokens.add(next_token)
        page_token = next_token
        if page_number + 1 < _page_limit():
            time.sleep(_page_delay())

    if not rows:
        raise RuntimeError(f"Workable não retornou vagas publicadas para o Brasil: {SEARCH_URL}")
    return list(rows.values())
