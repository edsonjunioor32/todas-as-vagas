# -*- coding: utf-8 -*-
"""Public jobs from Wellfound location pages.

Wellfound exposes the location catalogue as server-rendered HTML and publishes
Schema.org JobPosting data on each detail page. The five requested locations
are read as one source because the same posting can appear in more than one
location view.
"""
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, urlunsplit

from ._common import iso_date, job, strip_html, work_model_label
from ._html import PublicPageParser, job_posting
from ._http import get_text


LOCATION_URLS = (
    "https://wellfound.com/location/brazil",
    "https://wellfound.com/location/brasil-mg",
    "https://wellfound.com/location/brasilia",
    "https://wellfound.com/location/brasilia-df",
    "https://wellfound.com/location/brasil-nova-iguacu",
)
JOB_RE = re.compile(r"/jobs/([0-9]+)(?:-[^/?#]+)?(?:[/?#]|$)", re.I)
ANCHOR_RE = re.compile(
    r"""<a\b(?P<attrs>[^>]*\bhref\s*=\s*["'](?P<href>[^"']+)["'][^>]*)>
    (?P<body>[\s\S]*?)</a>""",
    re.I | re.X,
)
PAGE_RE = re.compile(r"\bPage\s+([0-9]+)\s+of\s+([0-9]+)\b", re.I)
DEFAULT_MAX_PAGES = 10
DEFAULT_DETAIL_WORKERS = 8


def _canonical_url(href, base_url):
    absolute = urljoin(base_url, str(href or "").strip())
    parsed = urlsplit(absolute)
    match = JOB_RE.search(parsed.path or "")
    if not match:
        return ""
    return urlunsplit((
        parsed.scheme or "https",
        parsed.netloc or "wellfound.com",
        f"/jobs/{match.group(1)}",
        "",
        "",
    ))


def _listing_links(markup, base_url):
    """Return unique detail links and their visible card labels."""
    links = {}
    for match in ANCHOR_RE.finditer(markup or ""):
        canonical = _canonical_url(match.group("href"), base_url)
        if not canonical:
            continue
        label = strip_html(match.group("body") or "").strip()
        links.setdefault(canonical, label)
    return list(links.items())


def _page_count(markup):
    matches = PAGE_RE.findall(markup or "")
    return max((int(total) for _page, total in matches), default=1)


def _location(posting):
    values = posting.get("jobLocation") or []
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, list):
        values = []

    locations = []
    for place in values:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if not isinstance(address, dict):
            continue
        locations.append({
            "city": str(address.get("addressLocality") or "").strip(),
            "state": str(address.get("addressRegion") or "").strip(),
            "country": str(address.get("addressCountry") or "").strip(),
        })

    first = locations[0] if locations else {}
    return (
        first.get("city", ""),
        first.get("state", ""),
        first.get("country", ""),
    )


def _organization(posting):
    organization = posting.get("hiringOrganization") or {}
    if isinstance(organization, list):
        organization = next(
            (item for item in organization if isinstance(item, dict)), {}
        )
    if not isinstance(organization, dict):
        return ""
    return str(organization.get("name") or "").strip()


def _employment_types(posting):
    values = posting.get("employmentType") or []
    if not isinstance(values, list):
        values = [values]
    return list(dict.fromkeys(
        str(value).strip() for value in values if str(value).strip()
    ))


def _categories(posting):
    value = posting.get("industry") or ""
    values = re.split(r",|\\band\\b", str(value), flags=re.I)
    return list(dict.fromkeys(
        strip_html(item).strip(" ,") for item in values if strip_html(item).strip(" ,")
    ))[:12]


def _salary(posting):
    value = posting.get("baseSalary") or {}
    if not isinstance(value, dict):
        return None, None, None
    currency = str(value.get("currency") or "").strip() or None
    amount = value.get("value") or {}
    if not isinstance(amount, dict):
        return None, None, currency
    return amount.get("minValue"), amount.get("maxValue"), currency


def _normalize_detail(url, markup, fallback_title=""):
    parser = PublicPageParser()
    parser.feed(markup)
    posting = job_posting(markup)

    title = strip_html(posting.get("title") or "").strip()
    if not title:
        title = next((
            strip_html(value).strip()
            for value in parser.headings
            if strip_html(value).strip()
            and strip_html(value).casefold() not in {"about the job", "about the company"}
        ), "")
    title = title or strip_html(fallback_title).strip()

    match = JOB_RE.search(urlsplit(url).path or "")
    native_id = (
        str((posting.get("identifier") or {}).get("value") or "").strip()
        if isinstance(posting.get("identifier"), dict) else ""
    ) or (match.group(1) if match else "")
    if not native_id or not title:
        return None

    company = _organization(posting) or "Wellfound"
    city, state, country = _location(posting)
    visible = parser.visible_text
    location_type = str(posting.get("jobLocationType") or "").strip()
    raw_model = f"{location_type} {visible}"
    work_model = work_model_label(
        remote_flag=location_type.casefold() in {"telecommute", "remote"},
        raw=raw_model,
    )
    if not work_model and re.search(r"\\b(remote|remoto)\\b", raw_model, re.I):
        work_model = "remote"

    salary_min, salary_max, salary_currency = _salary(posting)
    description = strip_html(posting.get("description") or visible)
    country = country or ("BR" if re.search(r"\\b(brazil|brasil)\\b", visible, re.I) else "")
    city = city or ("Brasil" if work_model == "remote" and country in {"BR", "Brazil", "Brasil"} else "")

    return job(
        "wellfound",
        native_id,
        title=title,
        company=company,
        url=_canonical_url(url, url),
        work_model=work_model,
        city=city,
        state=state,
        country=country,
        market="BR",
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        published_date=iso_date(posting.get("datePosted")),
        description=description,
        categories=_categories(posting),
        contract_types=_employment_types(posting),
    )


def fetch():
    links = {}
    errors = []
    for location_url in LOCATION_URLS:
        try:
            first_markup = get_text(
                location_url,
                headers={"Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8"},
                timeout=45,
                retries=3,
            )
            page_count = min(
                DEFAULT_MAX_PAGES,
                max(1, _page_count(first_markup)),
            )
            for href, label in _listing_links(first_markup, location_url):
                links.setdefault(href, label)

            for page in range(2, page_count + 1):
                page_url = f"{location_url}?page={page}"
                markup = get_text(
                    page_url,
                    headers={"Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8"},
                    timeout=45,
                    retries=3,
                )
                for href, label in _listing_links(markup, page_url):
                    links.setdefault(href, label)
        except Exception as error:
            errors.append(f"{location_url}: {str(error)[:120]}")

    if errors:
        for error in errors:
            print(f"    [wellfound] {error}")
    if not links:
        raise RuntimeError("Wellfound não expôs vagas públicas nas localidades configuradas")

    workers = min(max(1, int(
        os.environ.get("WELLFOUND_DETAIL_WORKERS") or DEFAULT_DETAIL_WORKERS
    )), 12)
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_normalize_detail, url, get_text(
                url,
                headers={"Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8"},
                timeout=45,
                retries=2,
            ), label): url
            for url, label in links.items()
        }
        for future in as_completed(futures):
            try:
                row = future.result()
            except Exception:
                continue
            if row:
                rows.append(row)

    unique = {row["native_id"]: row for row in rows}
    if not unique:
        raise RuntimeError("Wellfound não retornou vagas reconhecíveis")
    return list(unique.values())
