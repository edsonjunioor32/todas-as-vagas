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
