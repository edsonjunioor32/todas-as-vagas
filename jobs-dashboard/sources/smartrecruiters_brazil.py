# -*- coding: utf-8 -*-
"""Global SmartRecruiters discovery and Brazil catalogue collector."""
import html
import os
import re
import unicodedata
from urllib.parse import urlencode, urljoin, urlparse

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json, get_text
from ._rendered import rendered_links


DISCOVERY_URL = "https://jobs.smartrecruiters.com/?keyword=brazil"
SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
SMARTRECRUITERS_PAGE_SIZE = 100
MAX_COMPANIES = min(
    100,
    max(1, int(os.environ.get("SMARTRECRUITERS_MAX_COMPANIES", "100"))),
)
MAX_CATALOG_REQUESTS = min(
    1000,
    max(1, int(os.environ.get("SMARTRECRUITERS_MAX_REQUESTS", "500"))),
)

_ANCHOR_RE = re.compile(
    r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>",
    re.I,
)
_JOB_PATH_RE = re.compile(r"^/([^/?#]+)/([0-9][^/?#]*)/?$", re.I)
_RENDERED_JOB_RE = r"https?://jobs\.smartrecruiters\.com/[^/?#]+/[0-9][^/?#]*"


def _company_identifier(href):
    """Return a SmartRecruiters company slug only for a public job URL."""
    absolute = urljoin(DISCOVERY_URL, html.unescape(str(href or "")).strip())
    parsed = urlparse(absolute)
    if parsed.netloc.casefold() not in {
        "jobs.smartrecruiters.com",
        "www.jobs.smartrecruiters.com",
    }:
        return ""
    match = _JOB_PATH_RE.match(parsed.path)
    return match.group(1) if match else ""


def discover_companies(markup):
    """Extract stable company identifiers from public job links."""
    companies = []
    seen = set()
    for href in _ANCHOR_RE.findall(markup or ""):
        identifier = _company_identifier(href)
        if identifier and identifier.casefold() not in seen:
            seen.add(identifier.casefold())
            companies.append(identifier)
    return companies


def _discover_rendered_companies():
    rows = rendered_links(DISCOVERY_URL, _RENDERED_JOB_RE, timeout=60)
    markup_links = "".join(f'<a href="{html.escape(href)}"></a>' for href, _ in rows)
    return discover_companies(markup_links)


def _location_parts(location):
    if isinstance(location, dict):
        values = []
        for key in (
            "country",
            "countryCode",
            "country_code",
            "fullLocation",
            "address",
            "city",
            "region",
        ):
            value = location.get(key)
            if isinstance(value, dict):
                values.extend(str(item) for item in value.values() if item)
            elif value:
                values.append(str(value))
        return location, " ".join(values)
    if isinstance(location, list):
        text = " ".join(str(value) for value in location if value)
        return {}, text
    return {}, str(location or "")


def _country_code(location):
    location, text = _location_parts(location)
    value = (
        location.get("country")
        or location.get("countryCode")
        or location.get("country_code")
        or ""
    )
    if isinstance(value, dict):
        value = value.get("code") or value.get("name") or value.get("label") or ""
    normalized = str(value).strip().casefold()
    if normalized in {"br", "brasil", "brazil"}:
        return "BR"
    if len(normalized) == 2:
        return normalized.upper()
    if re.search(r"\b(?:brasil|brazil)\b", text, re.I):
        return "BR"
    return str(value).strip().upper()


def _is_brazil_location(location):
    return _country_code(location) == "BR"


def _slugify(title):
    normalized = unicodedata.normalize("NFKD", str(title or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")


def _text_value(value):
    if isinstance(value, dict):
        return " ".join(_text_value(item) for item in value.values() if item)
    if isinstance(value, list):
        return " ".join(_text_value(item) for item in value if item)
    return str(value or "")


def _company_name(data, identifier):
    value = data.get("company") or data.get("companyName") or identifier
    if isinstance(value, dict):
        value = value.get("name") or value.get("label") or identifier
    return str(value).strip() or identifier


def _catalog_entries(company, budget):
    offset = 0
    while True:
        if budget[0] >= MAX_CATALOG_REQUESTS:
            raise RuntimeError(
                f"limite seguro de {MAX_CATALOG_REQUESTS} requisições atingido"
            )
        query = urlencode({
            "country": "br",
            "limit": SMARTRECRUITERS_PAGE_SIZE,
            "offset": offset,
        })
        endpoint = SMARTRECRUITERS_API.format(company=company)
        budget[0] += 1
        payload = get_json(f"{endpoint}?{query}", timeout=45, retries=3)
        entries = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(entries, list) or not entries:
            break
        yield from entries

        total = payload.get("totalFound") if isinstance(payload, dict) else None
        try:
            total = int(total) if total is not None else None
        except (TypeError, ValueError):
            total = None
        offset += len(entries)
        if (
            len(entries) < SMARTRECRUITERS_PAGE_SIZE
            or total is None
            or offset >= total
        ):
            break


def _row(company, data):
    if not isinstance(data, dict):
        return None
    location, location_text = _location_parts(data.get("location") or {})
    if not _is_brazil_location(location):
        return None

    native_id = str(data.get("id") or data.get("refNumber") or "").strip()
    title = str(data.get("name") or data.get("title") or "").strip()
    if not native_id or not title:
        return None
    canonical = (
        f"https://jobs.smartrecruiters.com/{company}/"
        f"{native_id}-{_slugify(title)}"
    )
    employment = data.get("typeOfEmployment") or {}
    experience = data.get("experienceLevel") or {}
    categories = []
    for key in ("industry", "department", "function"):
        value = data.get(key) or {}
        label = value.get("label") if isinstance(value, dict) else value
        if label:
            categories.append(str(label).strip())
    city = str(location.get("city") or "").strip()
    if not city:
        city = str(location.get("address") or "").strip() or "Brasil"
    return job(
        "smartrecruiters_brazil",
        native_id,
        title=title,
        company=_company_name(data, company),
        url=canonical,
        work_model=work_model_label(
            remote_flag=bool(location.get("remote")),
            raw=location_text,
        ),
        city=city,
        state=str(location.get("region") or "").strip(),
        country="BR",
        market="BR",
        published_date=iso_date(
            data.get("releasedDate")
            or data.get("released_date")
            or data.get("createdOn")
        ),
        description=strip_html(
            _text_value(data.get("jobAd") or data.get("description") or "")
        ),
        levels=(
            [str(experience.get("label")).strip()]
            if isinstance(experience, dict) and experience.get("label")
            else []
        ),
        categories=categories or [f"Carreiras {_company_name(data, company)}"],
        contract_types=(
            [str(employment.get("label")).strip()]
            if isinstance(employment, dict) and employment.get("label")
            else []
        ),
    )


def _company_rows(company, budget=None):
    budget = budget if budget is not None else [0]
    rows = []
    seen = set()
    for data in _catalog_entries(company, budget):
        row = _row(company, data)
        if not row or row["native_id"] in seen:
            continue
        seen.add(row["native_id"])
        rows.append(row)
    return rows


def fetch():
    """Discover companies globally, then collect each complete Brazil catalogue."""
    budget = [0]
    try:
        markup = get_text(DISCOVERY_URL, timeout=45, retries=3)
        companies = discover_companies(markup)
    except Exception as error:
        print(f"[smartrecruiters_brazil] descoberta HTML falhou: {error}")
        companies = []

    if not companies:
        try:
            companies = _discover_rendered_companies()
        except Exception as error:
            raise RuntimeError(
                "SmartRecruiters não expôs links públicos de empresas; "
                f"HTML e fallback renderizado falharam: {error}"
            ) from error

    if len(companies) > MAX_COMPANIES:
        print(
            "[smartrecruiters_brazil] "
            f"{len(companies)} empresas descobertas; limitando a {MAX_COMPANIES}"
        )
        companies = companies[:MAX_COMPANIES]

    rows = []
    successful = 0
    failed = 0
    seen_jobs = set()
    for company in companies:
        try:
            company_rows = _company_rows(company, budget)
        except Exception as error:
            failed += 1
            print(
                f"[smartrecruiters_brazil] empresa {company} falhou isoladamente: "
                f"{error}"
            )
            continue
        successful += 1
        for row in company_rows:
            key = f"{row['company']}:{row['native_id']}"
            if key not in seen_jobs:
                seen_jobs.add(key)
                rows.append(row)
        if budget[0] >= MAX_CATALOG_REQUESTS:
            print(
                "[smartrecruiters_brazil] limite seguro de catálogo atingido; "
                "demais empresas ficaram para o próximo ciclo"
            )
            break

    if not rows:
        raise RuntimeError(
            "SmartRecruiters não retornou vagas brasileiras "
            f"(empresas bem-sucedidas: {successful}; falhas: {failed})"
        )
    print(
        f"[smartrecruiters_brazil] {len(rows)} vagas de {successful} empresas; "
        f"{failed} empresas falharam isoladamente"
    )
    return rows
