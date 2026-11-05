# -*- coding: utf-8 -*-
"""Public Skeelo careers catalogue backed by its key-free ATS endpoint."""
import re
from urllib.parse import urlsplit

from ._common import job, work_model_label
from ._http import get_json


API_URL = "https://skeelo.com/api/ats/jobs"
SOURCE = "skeelo"
RIPPLING_HOST = "ats.rippling.com"
MAX_PAGES = 50
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)


def _page(page_number):
    """Read one public Skeelo page and reject malformed API responses."""
    payload = get_json(
        f"{API_URL}?page={int(page_number)}",
        headers={"Accept": "application/json"},
        timeout=30,
        retries=3,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise RuntimeError("Skeelo retornou um payload de vagas inválido")
    return payload


def _detail_url(item):
    """Return a Rippling URL only when it belongs to Skeelo's job route."""
    native_id = str(item.get("id") or "").strip()
    if not UUID_RE.fullmatch(native_id):
        raise RuntimeError("Skeelo retornou uma vaga sem UUID válido")

    raw_url = str(item.get("url") or "").strip()
    parsed = urlsplit(raw_url)
    expected_path = f"/skeelo/jobs/{native_id}"
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != RIPPLING_HOST
        or parsed.path.rstrip("/") != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(f"URL de vaga Skeelo inválida para {native_id}")
    return raw_url


def _first_location(item):
    locations = item.get("locations")
    if not isinstance(locations, list):
        return {}
    return next((location for location in locations if isinstance(location, dict)), {})


def _normalize(item):
    if not isinstance(item, dict):
        raise RuntimeError("Skeelo retornou um item de vaga inválido")

    native_id = str(item.get("id") or "").strip()
    title = str(item.get("name") or "").strip()
    if not UUID_RE.fullmatch(native_id) or not title:
        raise RuntimeError("Skeelo retornou uma vaga sem UUID ou título")

    location = _first_location(item)
    location_name = str(location.get("name") or "").strip()
    workplace_type = str(location.get("workplaceType") or "").strip().upper()
    workplace_label = workplace_type.replace("_", "-")
    work_model = work_model_label(
        remote_flag=True if workplace_type == "REMOTE" else None,
        raw=f"{workplace_label} {location_name}",
    )

    country = str(location.get("countryCode") or "").strip().upper()
    city = str(location.get("city") or "").strip()
    state = str(location.get("state") or location.get("stateCode") or "").strip()
    if workplace_type == "REMOTE" and country == "BR" and not city:
        city = "Brasil"

    department = item.get("department")
    if isinstance(department, dict):
        department_name = str(department.get("name") or "").strip()
    else:
        department_name = str(department or "").strip()
    categories = [name for name in (department_name, "Skeelo") if name]

    return job(
        SOURCE,
        native_id,
        title,
        "Skeelo",
        _detail_url(item),
        work_model=work_model,
        city=city,
        state=state,
        country=country,
        market=country,
        categories=categories,
    )


def fetch():
    """Fetch every public Skeelo page, preserving only unique UUIDs."""
    first = _page(0)
    try:
        total_pages = int(first.get("totalPages") or 1)
    except (TypeError, ValueError) as error:
        raise RuntimeError("Skeelo retornou totalPages inválido") from error
    if total_pages < 1 or total_pages > MAX_PAGES:
        raise RuntimeError(f"Skeelo retornou quantidade de páginas insegura: {total_pages}")

    payloads = [first]
    payloads.extend(_page(page_number) for page_number in range(1, total_pages))
    unique = {}
    for payload in payloads:
        for item in payload["items"]:
            row = _normalize(item)
            unique.setdefault(row["native_id"], row)

    if not unique:
        raise RuntimeError("Skeelo não retornou vagas públicas")
    return list(unique.values())
