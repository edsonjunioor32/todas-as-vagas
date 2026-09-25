# -*- coding: utf-8 -*-
"""Public NG.CASH vacancies through the unauthenticated Revolut People API."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlencode

from ._common import iso_date, job, strip_html
from ._http import get_json


CAREERS_URL = "https://revolutpeople.com/ngcash/public/careers/"
POSTINGS_API = "https://revolutpeople.com/api/ngcash/external/v3/postings"
DETAILS_API = "https://revolutpeople.com/api/ngcash/external/v2/postings"
MAX_PAGES = 20
MAX_POSITIONS = 2000


def _text(value):
    return str(value or "").strip()


def _request_headers():
    return {
        "Accept": "application/json",
        "Referer": CAREERS_URL,
    }


def _list_page(page):
    payload = get_json(
        f"{POSTINGS_API}?{urlencode({'page': page})}",
        headers=_request_headers(),
        timeout=20,
        retries=2,
        backoff=1,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("NG.CASH retornou uma listagem inválida")

    results = payload.get("results")
    pages = payload.get("pages")
    if not isinstance(results, list) or not isinstance(pages, dict):
        raise RuntimeError("NG.CASH retornou paginação inválida")

    try:
        total_pages = int(pages.get("total") or 0)
    except (TypeError, ValueError) as error:
        raise RuntimeError("NG.CASH retornou total de páginas inválido") from error

    if total_pages < 1 and results:
        total_pages = 1
    if total_pages > MAX_PAGES:
        raise RuntimeError(
            f"NG.CASH excedeu o limite de segurança de {MAX_PAGES} páginas"
        )
    return results, total_pages


def _brazil_locations(posting):
    locations = posting.get("locations") or []
    if isinstance(locations, dict):
        locations = [locations]
    if not isinstance(locations, list):
        return []

    brazil_locations = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        country = location.get("country") or {}
        country_name = _text(country.get("name")) if isinstance(country, dict) else ""
        name = _text(location.get("name"))
        is_brazil = country_name.casefold() in {"brasil", "brazil"} or name.casefold() in {
            "brasil",
            "brazil",
        }
        if is_brazil:
            brazil_locations.append(location)
    return brazil_locations


def _location_fields(posting):
    locations = _brazil_locations(posting)
    if not locations:
        return None

    names = [_text(location.get("name")) for location in locations]
    city = next(
        (name for name in names if name and name.casefold() not in {"brasil", "brazil"}),
        "Brasil",
    )
    state = "SP" if city.casefold() in {"são paulo", "sao paulo"} else ""

    models = {_text(location.get("type")).casefold() for location in locations}
    if "remote" in models:
        work_model = "remote"
    elif "hybrid" in models:
        work_model = "hybrid"
    elif models.intersection({"office", "on-site", "onsite"}):
        work_model = "on-site"
    else:
        work_model = ""

    return {
        "city": city,
        "state": state,
        "country": "BR",
        "market": "BR",
        "work_model": work_model,
    }


def _slug(title):
    ascii_title = (
        unicodedata.normalize("NFKD", title)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_title.casefold()).strip("-")


def _canonical_url(title, posting_id):
    slug = _slug(title) or "vaga"
    return f"{CAREERS_URL}position/{slug}-{posting_id}"


def _normalize_position(posting, detail=None):
    """Normalize public list/detail API payloads into the catalog contract."""
    if not isinstance(posting, dict):
        return None

    posting_id = _text(posting.get("id"))
    title = _text(posting.get("title"))
    if not posting_id or not title:
        return None

    location = _location_fields(posting)
    if location is None:
        return None

    detail = detail if isinstance(detail, dict) else {}
    if _text(detail.get("id")) not in {"", posting_id}:
        detail = {}

    detail_title = _text(detail.get("title"))
    function = detail.get("function") or posting.get("function") or {}
    function_name = _text(function.get("name")) if isinstance(function, dict) else ""
    description = strip_html(_text(detail.get("description")), limit=60000)

    return job(
        "ngcash",
        posting_id,
        title=detail_title or title,
        company="NG.CASH",
        url=_canonical_url(title, posting_id),
        work_model=location["work_model"],
        city=location["city"],
        state=location["state"],
        country=location["country"],
        market=location["market"],
        published_date=iso_date(detail.get("creation_date_time")),
        description=description,
        categories=[function_name] if function_name else [],
    )


def fetch():
    """Collect currently published NG.CASH Brazil vacancies via public JSON."""
    first_page, total_pages = _list_page(1)
    postings = list(first_page)

    for page in range(2, total_pages + 1):
        page_results, _ = _list_page(page)
        postings.extend(page_results)
        if len(postings) > MAX_POSITIONS:
            raise RuntimeError("NG.CASH excedeu o limite de segurança de vagas coletadas")

    if len(postings) > MAX_POSITIONS:
        raise RuntimeError("NG.CASH excedeu o limite de segurança de vagas coletadas")

    rows = {}
    for posting in postings:
        if not isinstance(posting, dict):
            continue
        posting_id = _text(posting.get("id"))
        if not posting_id:
            continue

        detail = {}
        try:
            detail = get_json(
                f"{DETAILS_API}/{posting_id}",
                headers=_request_headers(),
                timeout=12,
                retries=1,
                backoff=0,
            )
        except Exception as error:
            # The public list is authoritative for active postings. Preserve a
            # valid listing if an individual detail endpoint is temporarily down.
            print(f"[ngcash] detalhe {posting_id} indisponível: {error}")

        row = _normalize_position(posting, detail)
        if row:
            rows.setdefault(row["native_id"], row)

    if not rows:
        raise RuntimeError("NG.CASH não retornou vagas brasileiras publicadas")
    return list(rows.values())
