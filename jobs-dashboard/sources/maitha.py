# -*- coding: utf-8 -*-
"""Public Maitha Tech vacancies through the company's public opportunities API."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import unicodedata
from urllib.parse import quote

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json


ORIGIN_URL = "https://maitha.com.br/vagas"
API_BASE_URL = "https://vagas-api.maitha-tech.com"
OPPORTUNITIES_URL = f"{API_BASE_URL}/opportunities"
DETAIL_URL = f"{API_BASE_URL}/opportunities"
MAX_POSITIONS = 5000
DETAIL_WORKERS = 8
STATE_RE = re.compile(r"^[A-Za-z]{2}$")


def _text(value):
    if isinstance(value, dict):
        for key in ("address", "name", "label", "value", "text"):
            if value.get(key) not in (None, ""):
                return _text(value[key])
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value if item not in (None, ""))
    return str(value or "").strip()


def _fold(value):
    return "".join(
        char for char in unicodedata.normalize("NFD", _text(value))
        if unicodedata.category(char) != "Mn"
    ).casefold()


def _location_fields(value):
    raw = _text(value)
    model = work_model_label(raw=raw)
    folded = _fold(raw)
    if not model:
        if any(token in folded for token in ("remoto", "remote", "home office", "teletrabalho")):
            model = "remote"
        elif any(token in folded for token in ("hibrido", "hybrid")):
            model = "hybrid"

    if model == "remote" or folded in {"remoto", "remote", "anywhere"}:
        return {
            "work_model": "remote",
            "city": "Brasil",
            "state": "",
            "country": "BR",
            "market": "BR",
        }

    parts = [part.strip() for part in re.split(r"[,|]", raw) if part.strip()]
    state = ""
    if len(parts) >= 2 and STATE_RE.fullmatch(parts[-1]):
        state = parts[-1].upper()
        city = parts[-2]
    else:
        city = parts[0] if parts else "Brasil"

    if _fold(city) in {"remoto", "remote", "home office"}:
        city = "Brasil"
        model = "remote"

    return {
        "work_model": model,
        "city": city or "Brasil",
        "state": state,
        "country": "BR",
        "market": "BR",
    }


def _skills(value):
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(
        _text(item) for item in values if _text(item)
    ))[:40]


def _contract_types(value):
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(
        _text(item) for item in values if _text(item)
    ))


def _extract_opportunities(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise RuntimeError("Maitha retornou uma resposta inválida")
    data = payload["data"]
    rows = data.get("opportunitiesList")
    if not isinstance(rows, list):
        raise RuntimeError("Maitha não retornou a lista de oportunidades")
    pagination = data.get("pagination") or {}
    try:
        total_pages = max(1, int(pagination.get("totalPages") or 1))
    except (TypeError, ValueError):
        total_pages = 1
    return rows, total_pages


def _list_opportunities():
    first_payload = get_json(
        OPPORTUNITIES_URL,
        headers={"Accept": "application/json", "Referer": ORIGIN_URL},
        timeout=25,
        retries=3,
        backoff=1,
    )
    rows, total_pages = _extract_opportunities(first_payload)
    if total_pages > 1:
        for page in range(2, total_pages + 1):
            payload = get_json(
                f"{OPPORTUNITIES_URL}?page={page}&limit=1000",
                headers={"Accept": "application/json", "Referer": ORIGIN_URL},
                timeout=25,
                retries=2,
                backoff=1,
            )
            page_rows, _ = _extract_opportunities(payload)
            rows.extend(page_rows)
            if len(rows) > MAX_POSITIONS:
                raise RuntimeError(
                    f"Maitha excedeu o limite de segurança de {MAX_POSITIONS} vagas"
                )
    if len(rows) > MAX_POSITIONS:
        raise RuntimeError(
            f"Maitha excedeu o limite de segurança de {MAX_POSITIONS} vagas"
        )
    return rows


def _detail(opportunity_id):
    try:
        payload = get_json(
            f"{DETAIL_URL}/{quote(str(opportunity_id), safe='')}",
            headers={"Accept": "application/json", "Referer": ORIGIN_URL},
            timeout=20,
            retries=2,
            backoff=1,
        )
    except Exception as error:
        print(f"[maitha] detalhe {opportunity_id} indisponível: {error}")
        return {}
    data = payload.get("data") if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


def _normalize(opportunity, detail=None):
    if not isinstance(opportunity, dict):
        return None
    detail = detail if isinstance(detail, dict) else {}
    opportunity_id = _text(
        detail.get("_id") or opportunity.get("id")
    )
    title = _text(detail.get("name") or opportunity.get("name"))
    if not opportunity_id or not title:
        return None

    location = detail.get("opportunityLocation") or opportunity.get("location")
    if isinstance(location, dict):
        location = location.get("address") or location.get("name") or ""
    location_data = _location_fields(location)

    skills = _skills(
        detail.get("specialities")
        or opportunity.get("skills")
        or []
    )
    profile = _text(detail.get("profile") or opportunity.get("profile"))
    description = strip_html(
        detail.get("description") or "",
        limit=60000,
    )

    return job(
        "maitha",
        opportunity_id,
        title=title,
        company="Maitha Tech",
        url=f"https://maitha.com.br/vaga.html?id={quote(opportunity_id, safe='')}",
        work_model=location_data["work_model"],
        city=location_data["city"],
        state=location_data["state"],
        country=location_data["country"],
        market=location_data["market"],
        published_date=iso_date(opportunity.get("openingTime")),
        description=description,
        skills=skills,
        levels=[profile] if profile else [],
        categories=skills[:12],
        contract_types=_contract_types(
            detail.get("hiringType") or opportunity.get("hiringType") or []
        ),
    )


def fetch():
    """Collect all currently listed Maitha Tech opportunities."""
    opportunities = _list_opportunities()
    details = {}
    with ThreadPoolExecutor(max_workers=min(DETAIL_WORKERS, len(opportunities) or 1)) as pool:
        futures = {
            pool.submit(_detail, _text(item.get("id"))): item
            for item in opportunities
            if isinstance(item, dict) and _text(item.get("id"))
        }
        for future in as_completed(futures):
            item = futures[future]
            details[_text(item.get("id"))] = future.result()

    rows = {}
    for opportunity in opportunities:
        opportunity_id = _text(opportunity.get("id")) if isinstance(opportunity, dict) else ""
        row = _normalize(opportunity, details.get(opportunity_id, {}))
        if row:
            rows[row["native_id"]] = row
    if not rows:
        raise RuntimeError("Maitha não retornou vagas públicas válidas")
    return list(rows.values())
