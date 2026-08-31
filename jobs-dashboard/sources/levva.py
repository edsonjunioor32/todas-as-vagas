# -*- coding: utf-8 -*-
"""Public Levva vacancies through the IziRH JSON API.

The visible Levva board is a JavaScript application.  Its public catalogue is
served by the same key-free endpoint used by the page, which is more reliable
for the scheduled runner than depending on browser rendering.
"""
import re

from ._common import iso_date, job, work_model_label
from ._http import get_json, post_json


LIST_URL = "https://levva.izirh.io/explorar-vagas"
SUBDOMAIN = "levva.izirh.io"
COMPANY = "Levva"
CONFIG_URL = "https://izi-api-v2.izirh.io/api/subdomains/levva.izirh.io"
VACANCIES_URL = "https://izi-api.izirh.io/api/sertec-ms-candidates"
PAGE_SIZE = 100
_GENERIC_LOCATIONS = {"", "não informado", "nao informado", "brasil", "brazil"}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _value_name(value):
    if isinstance(value, dict):
        return _clean(value.get("name") or value.get("label") or value.get("value"))
    return _clean(value)


def _model(value):
    raw = _value_name(value)
    normalized = raw.casefold()
    if normalized in {"presencial ou remoto", "remoto ou presencial"}:
        return "hybrid"
    if normalized in {"híbrido", "hibrido", "hybrid"}:
        return "hybrid"
    if normalized in {"presencial", "on-site", "onsite"}:
        return "on-site"
    if normalized in {"remoto", "remote", "home office", "home-office"}:
        return "remote"
    return work_model_label(raw=raw)


def _location(item):
    city = _clean(item.get("city"))
    state = _clean(item.get("state"))
    if city.casefold() in _GENERIC_LOCATIONS:
        city = "Brasil"
    return city, state


def _row(item):
    if not isinstance(item, dict):
        return None
    title = _clean(item.get("name") or item.get("title"))
    native_id = _clean(item.get("id") or item.get("_id") or item.get("vacancyId"))
    if not title or not native_id:
        return None

    city, state = _location(item)
    model = _model(item.get("workModel") or item.get("work_model"))
    if not model and city.casefold() not in {"brasil", "brazil"}:
        model = "on-site"

    contract = _value_name(item.get("typeContraction") or item.get("contractType"))
    url = f"{LIST_URL.rsplit('/', 1)[0]}/visualizar-vaga/{native_id}"
    published = (
        item.get("createdAt")
        or item.get("publishedAt")
        or item.get("published_date")
    )
    return job(
        "levva",
        native_id,
        title,
        COMPANY,
        url,
        work_model=model,
        city=city,
        state=state,
        country="BR",
        market="BR",
        published_date=iso_date(published),
        contract_types=[contract] if contract else [],
        pcd=bool(item.get("pcd")),
    )


def _rows_from_items(items):
    rows = []
    seen = set()
    for item in items or []:
        row = _row(item)
        if not row or row["native_id"] in seen:
            continue
        seen.add(row["native_id"])
        rows.append(row)
    return rows


def _result_payload(payload):
    if not isinstance(payload, dict):
        return {}
    result = payload.get("result")
    return result if isinstance(result, dict) else payload


def _rows_from_api(payload):
    result = _result_payload(payload)
    data = result.get("data") or result.get("vacancies") or []
    return _rows_from_items(data)


def _rows_from_cards(cards):
    """Keep the small card-normalization seam used by regression tests."""
    rows = []
    for item in cards or []:
        if not isinstance(item, dict):
            continue
        normalized = {
            "id": item.get("native_id") or item.get("id"),
            "name": item.get("title") or item.get("name"),
            "city": item.get("city"),
            "state": item.get("state"),
            "workModel": {"name": item.get("model")},
        }
        row = _row(normalized)
        if row:
            if item.get("url"):
                row["url"] = _clean(item["url"])
            rows.append(row)
    return rows


def _configuration():
    payload = get_json(CONFIG_URL, timeout=30, retries=3)
    tenant_id = _clean(payload.get("tenantId")) if isinstance(payload, dict) else ""
    if not tenant_id:
        raise RuntimeError("Levva public configuration did not expose a tenant id")
    return tenant_id


def _fetch_page(tenant_id, offset, limit=PAGE_SIZE):
    payload = {
        "command": "get_available_vacancies",
        "payload": {
            "companyId": tenant_id,
            "offset": offset,
            "limit": limit,
            "orderBy": {"name": "createdAt", "order": "desc"},
            "options": {"filters": True},
            "subdomain": SUBDOMAIN,
        },
    }
    response = post_json(VACANCIES_URL, payload, timeout=45, retries=3)
    result = _result_payload(response)
    if not isinstance(result.get("data"), list):
        raise RuntimeError("Levva public vacancy response has no data list")
    return result


def fetch():
    tenant_id = _configuration()
    offset = 0
    items = []
    expected = None

    while True:
        result = _fetch_page(tenant_id, offset)
        page = result.get("data") or []
        if expected is None:
            try:
                expected = int(result.get("vacanciesNumber"))
            except (TypeError, ValueError):
                expected = None
        items.extend(page)
        offset += len(page)

        if not page or (expected is not None and offset >= expected):
            break
        if expected is None and len(page) < PAGE_SIZE:
            break
        if offset > 10000:
            raise RuntimeError("Levva pagination exceeded the safety limit")

    unique_items = {
        _clean(item.get("id") or item.get("_id") or item.get("vacancyId")): item
        for item in items
        if isinstance(item, dict)
        and _clean(item.get("id") or item.get("_id") or item.get("vacancyId"))
    }
    if expected is not None and len(unique_items) < expected:
        raise RuntimeError(
            f"Levva pagination incomplete: {len(unique_items)}/{expected} vacancies"
        )

    rows = _rows_from_items(unique_items.values())
    if expected is not None and len(rows) < expected:
        raise RuntimeError(
            f"Levva returned {len(rows)}/{expected} recognizable vacancies"
        )
    if not rows:
        raise RuntimeError("Levva returned no recognizable public vacancy cards")
    return rows
