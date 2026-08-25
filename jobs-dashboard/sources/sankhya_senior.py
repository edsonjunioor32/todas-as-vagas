# -*- coding: utf-8 -*-
"""Structured public career feeds for Sankhya and Senior Sistemas."""
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

from ._common import iso_date, job, work_model_label
from ._http import get_text, post_json


SANKHYA = "https://oportunidades.mindsight.com.br/sankhya"
SENIOR = "https://vemprasenior.portaldetalentos.senior.com.br/jobs"
SENIOR_API = (
    "https://platform.senior.com.br/t/senior.com.br/bridge/1.0/"
    "anonymous/rest/hcm/careersmanagercandidate/queries/searchVacancies"
)
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>', re.I
)
LEVEL_RE = re.compile(r"\b(j[uú]nior|pleno|s[eê]nior|especialista|trainee|lead)\b", re.I)


def _levels(title):
    return list(dict.fromkeys(match.group(1).title() for match in LEVEL_RE.finditer(title or "")))


def _sankhya_rows():
    # Mindsight chooses the locale through Accept-Language. Supplying it is
    # important: a bare urllib request can be redirected back to /sankhya and
    # never receive the Next.js data payload.
    markup = get_text(
        SANKHYA,
        headers={
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (compatible; todas-as-vagas/1.0)",
        },
        timeout=45,
        retries=3,
    )
    match = NEXT_DATA_RE.search(markup)
    if not match:
        raise RuntimeError("Mindsight did not expose its public vacancy data")
    try:
        payload = json.loads(html.unescape(match.group(1)))
    except (TypeError, ValueError) as error:
        raise RuntimeError("Mindsight exposed invalid public vacancy JSON") from error
    entries = ((payload.get("props") or {}).get("pageProps") or {}).get("publicJobPostings")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("Sankhya public feed returned no active vacancy cards")

    model_map = {"REMOTE": "remote", "HYBRID": "hybrid", "IN_PERSON": "on-site"}
    hire_map = {
        "EFFECTIVE_CLT": "CLT",
        "CONTRACTOR": "PJ",
        "INTERNSHIP": "Estágio",
        "TEMPORARY": "Temporário",
    }
    rows, seen = [], set()
    for data in entries:
        if not isinstance(data, dict):
            continue
        native_id = str(data.get("id") or "").strip()
        title = str(data.get("name") or "").strip()
        if not native_id or not title or native_id in seen:
            continue
        seen.add(native_id)
        model = str(data.get("work_model") or "").upper()
        hire_model = str(data.get("hire_model") or "").upper()
        row = job(
            "sankhya", native_id, title=title, company="Sankhya",
            url=urljoin(SANKHYA + "/", native_id),
            work_model=model_map.get(model, work_model_label(raw=model)),
            city=str(data.get("city") or "Brasil").strip(),
            state=str(data.get("state") or "").strip(), country="BR", market="BR",
            published_date=iso_date(data.get("external_publication_start_at") or data.get("created_at")),
            expires_date=iso_date(data.get("external_publication_end_at")),
            levels=_levels(title), categories=["Carreiras Sankhya"],
            contract_types=[hire_map.get(hire_model, hire_model.title())] if hire_model else [],
        )
        for key, target in (("start_salary_range", "salary_min"), ("end_salary_range", "salary_max")):
            try:
                if data.get(key) not in (None, ""):
                    row[target] = float(data[key])
                    row["salary_currency"] = "BRL"
            except (TypeError, ValueError):
                pass
        rows.append(row)
    if not rows:
        raise RuntimeError("Sankhya public feed contained no recognizable vacancy records")
    return rows


def fetch_sankhya():
    return _sankhya_rows()


def _senior_page(page, size=100):
    return post_json(
        SENIOR_API,
        {"page": page, "size": size, "filter": {}, "match": {}},
        headers={"Accept": "application/json;seniorx.version=2"},
        timeout=45,
        retries=3,
    )


def _senior_rows():
    first = _senior_page(0)
    total_pages = int(first.get("totalPages") or 1)
    if total_pages > 100:
        raise RuntimeError(f"Senior API returned an unexpected page count: {total_pages}")
    payloads = [first]
    # The public catalogue currently spans a few dozen pages.  Fetch those
    # independent pages in a small bounded pool; sequential requests can take
    # several minutes and make the whole update look stalled.
    with ThreadPoolExecutor(max_workers=min(6, max(1, total_pages - 1))) as pool:
        futures = [pool.submit(_senior_page, page) for page in range(1, total_pages)]
        for future in futures:
            payloads.append(future.result())

    model_map = {"REMOTE": "remote", "HYBRID": "hybrid", "IN_PERSON": "on-site"}
    rows, seen = [], set()
    for payload in payloads:
        for item in payload.get("contents") or []:
            vacancy = item.get("vacancy") if isinstance(item, dict) else None
            company = item.get("company") if isinstance(item, dict) else None
            vacancy = vacancy if isinstance(vacancy, dict) else {}
            company = company if isinstance(company, dict) else {}
            native_id = str(vacancy.get("id") or "").strip()
            title = str(vacancy.get("title") or "").strip()
            if not native_id or not title or native_id in seen:
                continue
            seen.add(native_id)
            localization = vacancy.get("localization") or {}
            localization = localization if isinstance(localization, dict) else {}
            publication = vacancy.get("publication") or {}
            publication = publication if isinstance(publication, dict) else {}
            models = vacancy.get("jobModel") or []
            if isinstance(models, str):
                models = [models]
            model_values = [str(value).upper() for value in models]
            country = str(localization.get("country") or "Brasil").strip()
            country_code = "BR" if country.casefold() in {"brasil", "brazil", "br"} else country
            company_name = str(company.get("name") or "Senior Sistemas").strip()
            rows.append(job(
                "senior", native_id, title=title, company=company_name,
                url=f"https://www.portaldetalentos.senior.com.br/vacancy/{native_id}",
                work_model=next((model_map[value] for value in model_values if value in model_map), ""),
                city=str(localization.get("city") or "Brasil").strip(),
                state=str(localization.get("province") or "").strip(),
                country=country_code, market="BR" if country_code == "BR" else "global",
                published_date=iso_date(publication.get("startDate")),
                expires_date=iso_date(publication.get("endDate")),
                levels=_levels(title),
                categories=[str(company.get("sector") or "").strip()] if company.get("sector") else ["Portal de Talentos Senior"],
            ))
    if not rows:
        raise RuntimeError("Senior public API returned no active vacancy records")
    return rows


def fetch_senior():
    return _senior_rows()
