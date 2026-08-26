# -*- coding: utf-8 -*-
"""Public vacancies from InfoVagas, hosted by Quickin."""
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_text
from ._html import PublicPageParser, job_posting
from ._rendered import rendered_links


BASE_URL = "https://jobs.quickin.io"
LIST_URL = f"{BASE_URL}/infovagas/jobs"
DETAIL_RE = re.compile(r"/infovagas/jobs/([a-z0-9]{12,})(?:[/?#]|$)", re.I)
LEVEL_RE = re.compile(
    r"\b(j[uú]nior|jr\.?|pleno|mid(?:[- ]level)?|s[eê]nior|sr\.?|"
    r"especialista|lead|gerente|coordenador|trainee)\b",
    re.I,
)
PCD_RE = re.compile(r"\bpcd\b|pessoa(?:s)?\s+com\s+defici", re.I)
CONTRACT_RE = re.compile(
    r"\b(CLT|PJ|full[- ]?time|part[- ]?time|contract(?:or)?|"
    r"tempor[aá]rio|est[aá]gio)\b",
    re.I,
)


def _text(value):
    if isinstance(value, dict):
        for key in ("name", "label", "value", "text", "description", "city"):
            if value.get(key) not in (None, ""):
                return _text(value[key])
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value if item not in (None, ""))
    return str(value or "").strip()


def _posting_location(posting):
    value = posting.get("jobLocation") or posting.get("jobLocations") or {}
    if isinstance(value, list):
        value = value[0] if value else {}
    value = value if isinstance(value, dict) else {}
    address = value.get("address") or value
    address = address if isinstance(address, dict) else {}
    return (
        _text(address.get("addressLocality") or address.get("city")),
        _text(address.get("addressRegion") or address.get("state")),
        _text(address.get("addressCountry") or "BR"),
    )


def _header_location(header):
    text = re.sub(r"R\$\s*[\d.,]+(?:\s*\([^)]*\))?\s*,?", "", header or "", flags=re.I)
    text = re.sub(
        r"\b(?:clt|pj|full[- ]?time|part[- ]?time|contract(?:or)?|"
        r"tempor[aá]rio|est[aá]gio)\b\s*,?",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(?:remote|remoto|remota|hybrid|h[ií]brido|h[ií]brida|"
        r"on[- ]?site|onsite|presencial)\b",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip(" ,-|")
    if not text:
        return "", ""
    match = re.search(
        r"^(.*?)(?:\s*[-,]\s*|\s*/\s*)([A-Z]{2})$",
        text,
        re.I,
    )
    if match:
        return match.group(1).strip(" ,-|"), match.group(2).upper()
    return text, ""


def _title(parser, fallback):
    for value in parser.headings:
        normalized = value.casefold().strip()
        if normalized not in {"jobs", "requirements", "benefits", "apply"}:
            return value.strip()
    return strip_html(html.unescape(fallback or "")).strip()


def _header(parser, title):
    headings = [value.strip() for value in parser.headings if value.strip()]
    for index, value in enumerate(headings):
        if value == title:
            for candidate in headings[index + 1:]:
                if work_model_label(raw=candidate) or CONTRACT_RE.search(candidate):
                    return candidate
            break
    text = parser.visible_text
    if title and title in text:
        text = text.split(title, 1)[1]
    return text[:500]


def _contract_types(header):
    result = []
    for match in CONTRACT_RE.finditer(header or ""):
        value = match.group(1).strip()
        normalized = {
            "full time": "Full-time",
            "part time": "Part-time",
            "contractor": "Contract",
            "temporary": "Temporário",
            "estágio": "Estágio",
        }.get(value.casefold(), value)
        if normalized not in result:
            result.append(normalized)
    return result


def _normalize(url, markup, fallback_title=""):
    match = DETAIL_RE.search(url)
    if not match:
        return None
    parser = PublicPageParser()
    parser.feed(markup or "")
    posting = job_posting(markup or "")
    title = _text(posting.get("title")) or _title(parser, fallback_title)
    if not title:
        return None

    header = _header(parser, title)
    raw_text = parser.visible_text
    work_model = work_model_label(raw=header)
    if not work_model:
        work_model = work_model_label(raw=raw_text[:1200])

    city, state, country = _posting_location(posting)
    if not city:
        city, state = _header_location(header)
    if not city:
        city = "Brasil" if work_model == "remote" else ""
    if not country:
        country = "BR"

    description = strip_html(_text(posting.get("description")))
    if not description:
        description = strip_html(raw_text)
    levels = list(dict.fromkeys(
        found.group(1).title() for found in LEVEL_RE.finditer(f"{title} {description}")
    ))
    organization = posting.get("hiringOrganization") or {}
    company = _text(organization.get("name")) if isinstance(organization, dict) else ""
    meta_date = (
        parser.meta.get("dateposted")
        or parser.meta.get("article:published_time")
        or parser.meta.get("og:published_time")
    )
    return job(
        "infovagas",
        match.group(1),
        title=title,
        company=company or "InfoVagas",
        url=url.split("?", 1)[0],
        work_model=work_model,
        city=city,
        state=state,
        country=country,
        market="BR",
        published_date=iso_date(posting.get("datePosted") or meta_date),
        expires_date=iso_date(posting.get("validThrough")),
        description=description,
        levels=levels,
        categories=["InfoVagas"],
        contract_types=_contract_types(header),
        pcd=bool(PCD_RE.search(f"{title} {description}")),
    )


def _catalog_page(markup):
    parser = PublicPageParser()
    parser.feed(markup or "")
    detail_links, page_links = [], []
    seen_details, seen_pages = set(), set()
    for href, label in parser.anchors:
        absolute = urljoin(BASE_URL, html.unescape(href).strip())
        detail = DETAIL_RE.search(absolute)
        if detail:
            if detail.group(1).casefold() not in seen_details:
                seen_details.add(detail.group(1).casefold())
                detail_links.append((absolute, strip_html(html.unescape(label))))
            continue
        parsed = urlparse(absolute)
        if (
            parsed.netloc.casefold() == "jobs.quickin.io"
            and parsed.path.rstrip("/").casefold() == "/infovagas/jobs"
            and absolute not in seen_pages
        ):
            seen_pages.add(absolute)
            page_links.append(absolute)
    return detail_links, page_links


def _fetch_detail(url, label):
    try:
        markup = get_text(url, timeout=35, retries=2)
        return _normalize(url, markup, label)
    except Exception:
        return None


def fetch():
    catalog_error = None
    try:
        first_markup = get_text(
            LIST_URL,
            headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "User-Agent": "Mozilla/5.0 (compatible; todas-as-vagas/1.0)",
            },
            timeout=45,
            retries=3,
        )
    except Exception as error:
        first_markup = ""
        catalog_error = error
    links, page_links = _catalog_page(first_markup)
    if not links:
        links = [
            (href, strip_html(label))
            for href, label in rendered_links(
                LIST_URL,
                r"/infovagas/jobs/[a-z0-9]{12,}(?:[/?#]|$)",
                timeout=60,
            )
            if DETAIL_RE.search(href)
        ]

    pages_to_visit = list(page_links)
    if not pages_to_visit and links:
        pages_to_visit = [f"{LIST_URL}?page={page}" for page in range(2, 21)]

    visited_pages = {LIST_URL}
    for page_url in pages_to_visit:
        if page_url in visited_pages:
            continue
        visited_pages.add(page_url)
        try:
            markup = get_text(page_url, timeout=35, retries=2)
        except Exception:
            continue
        page_links_found, additional_pages = _catalog_page(markup)
        known_ids = {DETAIL_RE.search(url).group(1).casefold() for url, _ in links}
        for url, label in page_links_found:
            native_id = DETAIL_RE.search(url).group(1).casefold()
            if native_id not in known_ids:
                known_ids.add(native_id)
                links.append((url, label))
        for additional in additional_pages:
            if additional not in visited_pages and additional not in pages_to_visit:
                pages_to_visit.append(additional)
        if not page_links and not page_links_found and "?" in page_url:
            break

    if not links:
        detail = f": {catalog_error}" if catalog_error else ""
        raise RuntimeError(f"Quickin/InfoVagas returned no public vacancy links{detail}")

    rows = []
    with ThreadPoolExecutor(max_workers=min(8, len(links))) as pool:
        futures = {
            pool.submit(_fetch_detail, url, label): (url, label)
            for url, label in links
        }
        for future in as_completed(futures):
            row = future.result()
            if row:
                rows.append(row)
    if not rows:
        raise RuntimeError("InfoVagas public catalogue contained no readable vacancies")
    rows.sort(key=lambda row: row["native_id"])
    return rows
