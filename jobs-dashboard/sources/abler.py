# -*- coding: utf-8 -*-
"""Public vacancies from Agência Team's Abler career page."""
import urllib.parse

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json


SOURCE = "abler"
SUBDOMAIN = "agênciateam-6047"
API_ROOT = "https://hulk-smash.abler.com.br/api/company/v1/careers_pages"
PUBLIC_ROOT = (
    "https://ats.abler.com.br/jobs/"
    + urllib.parse.quote(SUBDOMAIN, safe="")
)
PAGE_SIZE = 100
MAX_PAGES = 20
INCLUDE = "area_of_interests,level_of_interest"


def _api_url(page):
    query = urllib.parse.urlencode(
        {
            "page": page,
            "per_page": PAGE_SIZE,
            "include": INCLUDE,
        }
    )
    subdomain = urllib.parse.quote(SUBDOMAIN, safe="")
    return f"{API_ROOT}/{subdomain}/vacancies?{query}"


def _number(value):
    if value in (None, "", False):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _names(values):
    output = []
    for value in values or []:
        if isinstance(value, dict):
            value = value.get("name") or value.get("title")
        text = str(value or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def _included_index(payload):
    return {
        (str(item.get("type") or ""), str(item.get("id") or "")): item
        for item in (payload.get("included") or [])
        if isinstance(item, dict)
    }


def _related_names(item, included, relationship):
    relation = ((item.get("relationships") or {}).get(relationship) or {}).get("data")
    references = relation if isinstance(relation, list) else [relation] if relation else []
    values = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        related = included.get(
            (str(reference.get("type") or ""), str(reference.get("id") or "")),
            {},
        )
        attributes = related.get("attributes") or {}
        value = attributes.get("name") or attributes.get("title")
        if value:
            values.append(value)
    return _names(values)


def _public_url(vacancy_id, slug):
    if slug:
        return f"{PUBLIC_ROOT}?{urllib.parse.urlencode({'slug': slug})}"
    identifier = urllib.parse.quote(f"abler-{vacancy_id}", safe="")
    return f"https://candidatos.abler.com.br/vagas?slug={identifier}"


def _normalize(item, included):
    attributes = item.get("attributes") or {}
    vacancy_id = item.get("id")
    title = attributes.get("title_formatted") or attributes.get("title") or ""
    if not vacancy_id or not str(title).strip():
        return None

    country = str(attributes.get("country") or "").strip()
    if country.upper() not in {"BR", "BRA", "BRASIL", "BRAZIL"}:
        return None

    work_types = _names(attributes.get("work_type") or attributes.get("work_type_formatted"))
    raw_model = " ".join(work_types)
    salary_min = _number(
        attributes.get("initial_salary_range")
        or attributes.get("salary_value")
        or attributes.get("salary")
    )
    salary_max = _number(attributes.get("final_salary_range"))
    contract = str(attributes.get("contracting_regime") or "").strip()
    description = attributes.get("description") or " ".join(
        str(attributes.get(field) or "")
        for field in (
            "role_description",
            "mandatory_requirements",
            "desirable_requirements",
            "results_and_deliveries",
            "working_journey",
        )
    )
    skills = _names(attributes.get("tech_skills")) + _names(attributes.get("soft_skills"))
    levels = _related_names(item, included, "level_of_interest")
    if not levels and attributes.get("seniority_level_formatted"):
        levels = [str(attributes["seniority_level_formatted"]).strip()]

    return job(
        SOURCE,
        vacancy_id,
        title=str(title),
        company=str(attributes.get("company_name") or "Agência Team"),
        url=_public_url(vacancy_id, str(attributes.get("slug") or "").strip()),
        work_model=work_model_label(
            remote_flag=attributes.get("available_for_homeoffice") is True,
            raw=raw_model,
        ),
        city=str(attributes.get("city") or "").strip(),
        state=str(attributes.get("state") or "").strip(),
        country="BR",
        market="BR",
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency="BRL" if salary_min is not None or salary_max is not None else None,
        published_date=iso_date(
            attributes.get("republished_at")
            or attributes.get("published_at")
            or attributes.get("created_at")
        ),
        expires_date=iso_date(attributes.get("close_on")),
        skills=skills[:10],
        description=strip_html(description),
        levels=levels,
        categories=_related_names(item, included, "area_of_interests"),
        contract_types=[contract] if contract else [],
        pcd=bool(attributes.get("exclusive_pcd")),
        blind_selection=attributes.get("promote_company") is False,
    )


def fetch():
    rows, seen = [], set()
    headers = {
        "Origin": "https://ats.abler.com.br",
        "Referer": PUBLIC_ROOT,
    }
    for page in range(1, MAX_PAGES + 1):
        payload = get_json(_api_url(page), headers=headers, timeout=60, retries=3)
        data = payload.get("data") or []
        if not isinstance(data, list):
            raise RuntimeError(f"Abler returned invalid data on page {page}")
        included = _included_index(payload)
        for item in data:
            row = _normalize(item, included)
            if row and row["native_id"] not in seen:
                seen.add(row["native_id"])
                rows.append(row)

        meta = payload.get("meta") or {}
        last_page = max(1, int(meta.get("last") or 1))
        if page >= last_page or not data:
            break

    if not rows:
        raise RuntimeError("Abler returned no public Agência Team vacancies")
    return rows


# ---------------------------------------------------------------------------
# Quadros Abler por empresa (formato genérico), migrados de
# requested_portals_27082026 em 15/11/2026 sem mudança de comportamento.
# Para incluir uma empresa, acrescente (fonte, subdomínio, empresa) em BOARDS.
# ---------------------------------------------------------------------------

BOARDS = (
    ("talentodovalesc", "talentodovalesc", "Talento do Vale SC"),
    ("precisionrh", "precision", "Precision RH"),
)


def fetch_board(source, subdomain, company):
    """Read a generic Abler public JSON:API career page."""
    encoded_subdomain = urllib.parse.quote(subdomain, safe="")
    api_root = (
        "https://hulk-smash.abler.com.br/api/company/v1/careers_pages/"
        f"{encoded_subdomain}/vacancies"
    )
    public_root = f"https://ats.abler.com.br/jobs/{encoded_subdomain}"
    rows, seen = [], set()
    for page in range(1, 21):
        query = urllib.parse.urlencode({
            "page": page,
            "per_page": 100,
            "include": "area_of_interests,level_of_interest",
        })
        payload = get_json(
            f"{api_root}?{query}",
            headers={"Origin": "https://ats.abler.com.br", "Referer": public_root},
            timeout=60,
            retries=3,
        )
        values = payload.get("data") or []
        if not isinstance(values, list):
            raise RuntimeError(f"Abler/{subdomain} returned invalid data")
        included = {
            (str(item.get("type") or ""), str(item.get("id") or "")): item
            for item in (payload.get("included") or [])
            if isinstance(item, dict)
        }
        for item in values:
            attrs = item.get("attributes") or {}
            native_id = str(item.get("id") or "").strip()
            title = str(attrs.get("title_formatted") or attrs.get("title") or "").strip()
            country = str(attrs.get("country") or "").strip().casefold()
            if not native_id or not title or native_id in seen:
                continue
            if country and country not in {"br", "bra", "brasil", "brazil"}:
                continue
            seen.add(native_id)
            slug = str(attrs.get("slug") or "").strip()
            url = f"{public_root}?slug={slug}" if slug else f"{public_root}?id={native_id}"
            raw_model = " ".join(
                str(value or "").strip()
                for value in (attrs.get("work_type"), attrs.get("work_type_formatted"))
            )
            contract = str(attrs.get("contracting_regime") or "").strip()
            description = " ".join(
                str(attrs.get(field) or "")
                for field in (
                    "description", "role_description", "mandatory_requirements",
                    "desirable_requirements", "results_and_deliveries",
                )
            )
            rows.append(job(
                source, native_id, title=title, company=company, url=url,
                work_model=work_model_label(
                    remote_flag=attrs.get("available_for_homeoffice") is True,
                    raw=raw_model,
                ),
                city=str(attrs.get("city") or "Brasil").strip(),
                state=str(attrs.get("state") or "").strip(),
                country="BR", market="BR",
                published_date=iso_date(
                    attrs.get("republished_at") or attrs.get("published_at") or attrs.get("created_at")
                ),
                expires_date=iso_date(attrs.get("close_on")),
                description=strip_html(description),
                contract_types=[contract] if contract else [],
            ))
        meta = payload.get("meta") or {}
        last_page = int(meta.get("last") or page)
        if page >= last_page or not values:
            break
    if not rows:
        raise RuntimeError(f"Abler/{subdomain} returned no public vacancies")
    return rows


def _board_fetcher(source, subdomain, company):
    def fetch_board_source():
        return fetch_board(source, subdomain, company)

    fetch_board_source.__name__ = fetch_board_source.__qualname__ = f"fetch_{source}"
    fetch_board_source.__doc__ = f"Collect the open Brazilian vacancies on {company}'s Abler board."
    return fetch_board_source


BOARD_FETCHERS = {source: _board_fetcher(source, sub, company) for source, sub, company in BOARDS}
BOARD_TARGETS = tuple(BOARD_FETCHERS.items())
