# -*- coding: utf-8 -*-
"""Sólides Vagas — recent public catalogue from the portal's key-free API.

The public endpoint fixes pages at ten records. The live catalogue contains
tens of thousands of vacancies, so the default refresh intentionally covers
the 3,000 most recent records. SOLIDES_MAX_PAGES can tune that window without
changing the adapter; bounded concurrency keeps the scheduled run practical.
"""
import os
import re
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json

API = "https://apigw.solides.com.br/jobs/v3/portal-vacancies-new"
PAGE_SIZE = 10
DEFAULT_MAX_PAGES = 300
PORTAL = "https://vagas.solides.com.br/vaga"


def _job_slug(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:120].rstrip("-") or "vaga")


def canonical_url(vacancy_id, title):
    encoded_id = urllib.parse.quote(str(vacancy_id or "").strip(), safe="")
    return f"{PORTAL}/{encoded_id}/{_job_slug(title)}"


def _url(page):
    query = urllib.parse.urlencode({"page": page, "take": PAGE_SIZE})
    return f"{API}?{query}"


def _page(page):
    payload = get_json(_url(page), timeout=45, retries=3)
    if not payload.get("success"):
        raise RuntimeError(f"Sólides returned success=false on page {page}")
    model = payload.get("data") or {}
    return model, model.get("data") or []


def _names(values):
    output = []
    for value in values or []:
        name = value.get("name") if isinstance(value, dict) else value
        if name and str(name).strip():
            output.append(str(name).strip())
    return output


def _salary(value):
    value = value or {}
    if not value.get("showRangeToApplicant"):
        return None, None, None
    initial = value.get("initialRange")
    final = value.get("finalRange")
    salary_min = float(initial) if initial not in (None, "", 0) else None
    salary_max = float(final) if final not in (None, "", 0) else None
    if value.get("type") == "simple" and salary_min is None and salary_max is not None:
        salary_min, salary_max = salary_max, None
    return salary_min, salary_max, "BRL" if salary_min or salary_max else None


def _normalize(item):
    address = item.get("address") or {}
    city_data = item.get("city") or address.get("city") or {}
    state_data = item.get("state") or address.get("state") or {}
    country_data = address.get("country") or {}
    city = str(city_data.get("name") or "").strip()
    state = str(state_data.get("code") or state_data.get("name") or "").strip()
    country = str(country_data.get("code") or country_data.get("name") or "BR").strip()
    market = "BR" if country.upper() in {"BR", "BRASIL", "BRAZIL"} else "Global"

    salary_min, salary_max, currency = _salary(item.get("salary"))
    skills = _names(item.get("hardSkills"))
    levels = _names(item.get("seniority"))
    categories = _names(item.get("occupationAreas"))
    contracts = _names(item.get("recruitmentContractType"))
    vacancy_id = item.get("id")
    # The API still returns legacy *.solides.jobs links whose DNS was retired.
    # The current portal requires a third path segment after the vacancy id.
    url = canonical_url(vacancy_id, item.get("title"))
    raw_model = item.get("jobType") or ("remoto" if item.get("homeOffice") else "")

    return job(
        "solides",
        vacancy_id,
        title=item.get("title", ""),
        company=item.get("companyName", ""),
        url=url,
        work_model=work_model_label(remote_flag=item.get("homeOffice") is True, raw=raw_model),
        city=", ".join(part for part in (city, state) if part),
        state=state,
        country="BR" if market == "BR" else country,
        market=market,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        published_date=iso_date(item.get("createdAt")),
        skills=skills[:10],
        description=strip_html(item.get("description", "")),
        levels=levels,
        categories=categories,
        contract_types=contracts,
        pcd=bool(item.get("pcdOnly") or item.get("peopleWithDisabilities") or item.get("hasSpecialNeeds")),
        blind_selection=bool(item.get("isHiddenJob")),
    )


def fetch():
    first_model, first_rows = _page(1)
    available_pages = max(1, int(first_model.get("totalPages") or 1))
    configured_cap = int(os.environ.get("SOLIDES_MAX_PAGES") or DEFAULT_MAX_PAGES)
    total_pages = min(available_pages, max(1, configured_cap))
    workers = min(max(1, int(os.environ.get("SOLIDES_WORKERS") or 6)), 8)

    pages = {1: first_rows}
    failed_pages = []
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_page, page): page for page in range(2, total_pages + 1)}
            for future in as_completed(futures):
                page = futures[future]
                try:
                    _, rows = future.result()
                    pages[page] = rows
                except Exception:
                    failed_pages.append(page)

    if failed_pages and len(pages) < max(2, total_pages // 2):
        raise RuntimeError(
            f"Sólides returned too few usable pages: {len(pages)}/{total_pages}"
        )

    unique = {}
    for page in range(1, total_pages + 1):
        for item in pages.get(page, []):
            vacancy_id = item.get("id")
            if vacancy_id is not None:
                unique[str(vacancy_id)] = _normalize(item)
    return list(unique.values())
