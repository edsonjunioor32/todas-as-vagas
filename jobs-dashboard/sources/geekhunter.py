# -*- coding: utf-8 -*-
"""GeekHunter — all jobs exposed in the public server-rendered catalogue.

The portal embeds a structured PublicJob payload in its Next.js response. We
read that payload instead of copying the visual card text or full job pages.
Descriptions are used only in memory for classification and are never exported.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from ._common import job, strip_html, work_model_label
from ._http import get_text

BASE = "https://www.geekhunter.com/pt/vagas"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; todas-as-vagas/1.0)"}


def _flight_stream(html):
    marker = "self.__next_f.push("
    chunks = []
    cursor = 0
    while True:
        start = html.find(marker, cursor)
        if start < 0:
            break
        start += len(marker)
        end = html.find(")</script>", start)
        if end < 0:
            break
        try:
            payload = json.loads(html[start:end])
            if len(payload) > 1 and isinstance(payload[1], str):
                chunks.append(payload[1])
        except (json.JSONDecodeError, TypeError):
            pass
        cursor = end + 1
    return "".join(chunks)


def _parse_page(html):
    stream = _flight_stream(html)
    public_job_pos = stream.find('"__typename":"PublicJob"')
    if public_job_pos < 0:
        raise RuntimeError("GeekHunter PublicJob payload was not found")

    data_marker = '"data":'
    data_start = stream.rfind(data_marker, 0, public_job_pos)
    if data_start < 0:
        raise RuntimeError("GeekHunter job array was not found")
    decoder = json.JSONDecoder()
    rows, data_end = decoder.raw_decode(stream, data_start + len(data_marker))

    meta_marker = '"meta":'
    meta_start = stream.find(meta_marker, data_end, data_end + 2500)
    if meta_start < 0:
        raise RuntimeError("GeekHunter pagination metadata was not found")
    meta, _ = decoder.raw_decode(stream, meta_start + len(meta_marker))
    return rows, meta


def _page(page):
    html = get_text(f"{BASE}?page={page}", headers=HEADERS, timeout=45, retries=3)
    return _parse_page(html)


def _epoch_ms_date(value):
    try:
        number = int(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _company_name(slug):
    slug = str(slug or "").strip().lower()
    if slug in {"confidential", "empresa-confidencial"}:
        return "Empresa confidencial"
    slug = re.sub(r"-\d+$", "", slug)
    return " ".join(part.capitalize() for part in slug.split("-") if part) or "Empresa não informada"


def _location(detail, work_model):
    locations = []
    countries = []
    for entry in detail.get("atsJobCities") or []:
        city_data = entry.get("city") or {}
        name = str(entry.get("name") or city_data.get("name") or "").strip()
        if name:
            locations.append(name)
        code = str(city_data.get("countryCode") or "").strip().upper()
        if code:
            countries.append(code)
    location = " · ".join(dict.fromkeys(locations[:3]))
    state = ""
    if locations:
        parts = [part.strip() for part in locations[0].split(",") if part.strip()]
        if len(parts) >= 2 and len(parts[-1]) <= 3:
            state = parts[-1].upper()
    country = countries[0] if countries else ("BR" if state else "")
    if not location and work_model == "remote":
        location = "Remoto"
    return location, state, country


def _salary_and_contracts(detail):
    salaries = detail.get("atsJobSalaries") or []
    minimums, maximums, contracts = [], [], []
    currency = None
    for salary in salaries:
        if salary.get("minSalary") not in (None, ""):
            minimums.append(float(salary["minSalary"]))
        if salary.get("maxSalary") not in (None, ""):
            maximums.append(float(salary["maxSalary"]))
        if salary.get("contractType"):
            contracts.append(str(salary["contractType"]).strip())
        currency = currency or salary.get("currency")
    return (
        min(minimums) if minimums else None,
        max(maximums) if maximums else None,
        currency if minimums or maximums else None,
        list(dict.fromkeys(contracts)),
    )


def _skills(detail):
    output = []
    for entry in detail.get("atsJobSkills") or []:
        skill = entry.get("atsSkill") or entry.get("poolSkill") or {}
        name = str(skill.get("name") or "").strip()
        if name:
            output.append(name)
    return list(dict.fromkeys(output))


def _normalize(item):
    ats = item.get("atsJob") or {}
    detail = ats.get("atsJobDetail") or {}
    company_slug = str((ats.get("company") or {}).get("slug") or "").strip()
    job_slug = str(ats.get("jobSlug") or "").strip()
    work_model = work_model_label(raw=detail.get("workModality"))
    location, state, country = _location(detail, work_model)
    salary_min, salary_max, currency, contracts = _salary_and_contracts(detail)
    description = strip_html(detail.get("description", ""))
    pcd_text = f"{detail.get('title', '')} {description}".lower()

    return job(
        "geekhunter",
        item.get("id") or ats.get("id"),
        title=detail.get("title", ""),
        company=_company_name(company_slug),
        url=f"https://www.geekhunter.com/pt/{company_slug}/jobs/{job_slug}",
        work_model=work_model,
        city=location,
        state=state,
        country=country,
        # GeekHunter publica vagas voltadas ao mercado brasileiro. Alguns
        # anúncios omitem o país na carga estruturada, mas continuam nacionais.
        market="BR",
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        published_date=_epoch_ms_date(ats.get("publishedAt") or ats.get("firstCreatedAt")),
        skills=_skills(detail)[:12],
        description=description,
        levels=[detail.get("experienceLevel", "")] if detail.get("experienceLevel") else [],
        contract_types=contracts,
        pcd=bool(re.search(r"\bpcd\b|pessoa(?:s)? com defici", pcd_text, re.I)),
        blind_selection=company_slug in {"confidential", "empresa-confidencial"},
    )


def fetch():
    first_rows, first_meta = _page(1)
    available_pages = max(1, int(first_meta.get("lastPage") or 1))
    configured_cap = int(os.environ.get("GEEKHUNTER_MAX_PAGES") or available_pages)
    total_pages = min(available_pages, max(1, configured_cap))
    workers = min(max(1, int(os.environ.get("GEEKHUNTER_WORKERS") or 4)), 6)

    pages = {1: first_rows}
    failed_pages = []
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_page, page): page for page in range(2, total_pages + 1)}
            for future in as_completed(futures):
                page = futures[future]
                try:
                    pages[page] = future.result()[0]
                except Exception:
                    failed_pages.append(page)

    if failed_pages and len(pages) < max(2, total_pages // 2):
        raise RuntimeError(
            f"GeekHunter returned too few usable pages: {len(pages)}/{total_pages}"
        )

    unique = {}
    for page in range(1, total_pages + 1):
        for item in pages.get(page, []):
            row = _normalize(item)
            unique[row["native_id"] or row["url"]] = row
    return list(unique.values())
