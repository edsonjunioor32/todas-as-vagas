# -*- coding: utf-8 -*-
"""Public vacancies from InfoVagas and company boards hosted by Quickin."""
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_text
from ._html import PublicPageParser, job_posting
from ._rendered import rendered_paginated_links


BASE_URL = "https://jobs.quickin.io"
LIST_URL = f"{BASE_URL}/infovagas/jobs"
QUICKIN_PAGE_SIZE = 10
DETAIL_RE = re.compile(r"/infovagas/jobs/([a-z0-9]{12,})(?:[/?#]|$)", re.I)


def _detail_pattern(board):
    return re.compile(
        rf"/{re.escape(board)}/jobs/([a-z0-9]{{12,}})(?:[/?#]|$)",
        re.I,
    )


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


def _normalize(url, markup, fallback_title="", source="infovagas", detail_re=DETAIL_RE,
              company_override=""):
    match = detail_re.search(url)
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
        source,
        match.group(1),
        title=title,
        company=company or company_override or "InfoVagas",
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


def _catalog_page(markup, board="infovagas", detail_re=None):
    detail_re = detail_re or _detail_pattern(board)
    parser = PublicPageParser()
    parser.feed(markup or "")
    detail_links, page_links = [], []
    seen_details, seen_pages = set(), set()
    for href, label in parser.anchors:
        absolute = urljoin(BASE_URL, html.unescape(href).strip())
        detail = detail_re.search(absolute)
        if detail:
            if detail.group(1).casefold() not in seen_details:
                seen_details.add(detail.group(1).casefold())
                detail_links.append((absolute, strip_html(html.unescape(label))))
            continue
        parsed = urlparse(absolute)
        if (
            parsed.netloc.casefold() == "jobs.quickin.io"
            and parsed.path.rstrip("/").casefold() == f"/{board}/jobs"
            and absolute not in seen_pages
        ):
            seen_pages.add(absolute)
            page_links.append(absolute)
    return detail_links, page_links


def _merge_links(links, additional, detail_re):
    merged = list(links)
    known_ids = {
        detail_re.search(url).group(1).casefold()
        for url, _ in merged
        if detail_re.search(url)
    }
    for url, label in additional:
        match = detail_re.search(url)
        if not match:
            continue
        native_id = match.group(1).casefold()
        if native_id in known_ids:
            continue
        known_ids.add(native_id)
        merged.append((url, strip_html(label)))
    return merged


def _fetch_detail(url, label, source="infovagas", detail_re=DETAIL_RE,
                  company_override=""):
    try:
        markup = get_text(url, timeout=35, retries=2)
        return _normalize(
            url, markup, label, source=source, detail_re=detail_re,
            company_override=company_override,
        )
    except Exception:
        return None


def _fetch_board(board, source=None, company_override=""):
    source = source or board
    list_url = f"{BASE_URL}/{board}/jobs"
    detail_re = _detail_pattern(board)
    catalog_error = None
    try:
        first_markup = get_text(
            list_url,
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

    links, page_links = _catalog_page(first_markup, board, detail_re)
    first_page_count = len(links)

    # Keep the cheap HTTP path when the board exposes real page links in HTML.
    # Do not fabricate ?page=N URLs: Quickin's current UI does not guarantee
    # that query-string contract and that fallback silently repeated page 1.
    pages_to_visit = list(page_links)
    visited_pages = {list_url}
    for page_url in pages_to_visit:
        if page_url in visited_pages:
            continue
        visited_pages.add(page_url)
        try:
            markup = get_text(page_url, timeout=35, retries=2)
        except Exception:
            continue
        page_links_found, additional_pages = _catalog_page(markup, board, detail_re)
        links = _merge_links(links, page_links_found, detail_re)
        for additional in additional_pages:
            if additional not in visited_pages and additional not in pages_to_visit:
                pages_to_visit.append(additional)

    # Quickin currently shows 10 vacancies per page. A full first page is not
    # evidence of a complete catalogue: verify it by navigating the visible
    # pagination controls in a browser and merge every discovered vacancy.
    # If that verification fails, propagate the failure so the pipeline keeps
    # the last valid snapshot instead of publishing a partial 10-job board.
    if not links or first_page_count >= QUICKIN_PAGE_SIZE:
        rendered = rendered_paginated_links(
            list_url,
            rf"/{re.escape(board)}/jobs/[a-z0-9]{{12,}}(?:[/?#]|$)",
            timeout=120,
            max_pages=100,
        )
        links = _merge_links(links, rendered, detail_re)

    if not links:
        detail = f": {catalog_error}" if catalog_error else ""
        raise RuntimeError(
            f"Quickin/{source} returned no public vacancy links{detail}"
        )

    rows = []
    with ThreadPoolExecutor(max_workers=min(8, len(links))) as pool:
        futures = {
            pool.submit(
                _fetch_detail, url, label, source, detail_re, company_override
            ): (url, label)
            for url, label in links
        }
        for future in as_completed(futures):
            row = future.result()
            if row:
                rows.append(row)
    if not rows:
        raise RuntimeError(
            f"{source} public catalogue contained no readable vacancies"
        )
    rows.sort(key=lambda row: row["native_id"])
    return rows


def fetch():
    return _fetch_board("infovagas", "infovagas")


def fetch_finayatech():
    return _fetch_board("finayatech", "finayatech")


def fetch_company(board, source=None, company=""):
    """Collect every public vacancy from one Quickin company board."""
    return _fetch_board(
        board,
        source=source or board,
        company_override=company,
    )
