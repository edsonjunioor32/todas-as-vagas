# -*- coding: utf-8 -*-
"""Public SONDA vacancies from its SAP SuccessFactors career site.

The site exposes a server-rendered search table and public JobPosting detail
pages. This adapter uses only those public HTML pages, keeping the stable
numeric requisition id from the detail URL and the structured date/location
metadata when available.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
import html
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_text


BASE_URL = "https://carrera.sonda.com"
SEARCH_URL = (
    BASE_URL
    + "/search/?q=&q2=&alertId=&title=&location=Brasil&department="
)
PAGE_SIZE = 25
MAX_PAGES = 40
DETAIL_WORKERS = 4

_MONTHS = {
    "jan": 1,
    "january": 1,
    "fev": 2,
    "feb": 2,
    "fevereiro": 2,
    "february": 2,
    "mar": 3,
    "marco": 3,
    "março": 3,
    "march": 3,
    "abr": 4,
    "apr": 4,
    "abril": 4,
    "april": 4,
    "mai": 5,
    "may": 5,
    "maio": 5,
    "jun": 6,
    "june": 6,
    "junho": 6,
    "jul": 7,
    "july": 7,
    "julho": 7,
    "ago": 8,
    "aug": 8,
    "agosto": 8,
    "august": 8,
    "set": 9,
    "sep": 9,
    "setembro": 9,
    "september": 9,
    "out": 10,
    "oct": 10,
    "outubro": 10,
    "october": 10,
    "nov": 11,
    "novembro": 11,
    "november": 11,
    "dez": 12,
    "dec": 12,
    "dezembro": 12,
    "december": 12,
}


def _classes(attrs):
    return set(dict(attrs).get("class", "").split())


def _clean(value):
    return " ".join(str(value or "").split())


class _ListingParser(HTMLParser):
    """Extract title, URL, location and department from result rows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._in_title = False
        self._in_location = False
        self._in_department = False

    def handle_starttag(self, tag, attrs):
        classes = _classes(attrs)
        if tag == "tr" and "data-row" in classes:
            self._row = {
                "href": "",
                "title": [],
                "location": [],
                "department": [],
            }
            self._in_title = False
            self._in_location = False
            self._in_department = False
            return
        if not self._row:
            return
        if tag == "a" and "jobTitle-link" in classes:
            href = dict(attrs).get("href", "")
            # SuccessFactors renders desktop and mobile anchors for the same
            # requisition. Keep only the first canonical link.
            self._in_title = not self._row["href"] and bool(href)
            if self._in_title:
                self._row["href"] = href
        elif tag == "td" and "colLocation" in classes:
            self._in_location = True
        elif tag == "td" and "colDepartment" in classes:
            self._in_department = True

    def handle_endtag(self, tag):
        if tag == "a":
            self._in_title = False
        elif tag == "td":
            self._in_location = False
            self._in_department = False
        elif tag == "tr" and self._row is not None:
            title = _clean(" ".join(self._row["title"]))
            location = _clean(" ".join(self._row["location"]))
            department = _clean(" ".join(self._row["department"]))
            if title and self._row["href"]:
                self.rows.append(
                    (self._row["href"], title, location, department)
                )
            self._row = None
            self._in_title = False
            self._in_location = False
            self._in_department = False

    def handle_data(self, data):
        if not self._row:
            return
        if self._in_title:
            self._row["title"].append(data)
        elif self._in_location:
            self._row["location"].append(data)
        elif self._in_department:
            self._row["department"].append(data)


class _DescriptionParser(HTMLParser):
    """Read only the public jobdescription block."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._depth = 0

    def handle_starttag(self, _tag, attrs):
        if self._depth:
            self._depth += 1
        elif "jobdescription" in _classes(attrs):
            self._depth = 1

    def handle_endtag(self, _tag):
        if self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth:
            self.parts.append(data)


def _listing_rows(markup):
    parser = _ListingParser()
    parser.feed(markup or "")
    parser.close()
    return [
        (_canonical_url(href), title, location, department)
        for href, title, location, department in parser.rows
    ]


def _canonical_url(href):
    parsed = urlsplit(urljoin(BASE_URL, html.unescape(href)))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _native_id(url):
    match = re.search(r"/(\d+)/?$", urlsplit(url).path)
    return match.group(1) if match else ""


def _result_total(markup):
    plain = strip_html(markup or "")
    match = re.search(
        r"Resultados\s+\d+\s*[–-]\s*\d+\s+de\s+(\d+)",
        plain,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _meta_content(markup, itemprop):
    for tag in re.findall(r"<meta\b[^>]*>", markup or "", flags=re.IGNORECASE):
        attrs = {
            key.casefold(): html.unescape(value)
            for key, value in re.findall(
                r"""([:\w-]+)\s*=\s*["']([^"']*)["']""",
                tag,
                flags=re.IGNORECASE,
            )
        }
        if attrs.get("itemprop", "").casefold() == itemprop.casefold():
            return attrs.get("content", "").strip()
    return ""


def _published_date(value):
    normalized = iso_date(value)
    if normalized:
        return normalized[:10]
    match = re.search(
        r"\b[A-Za-z]{3,9}\s+([A-Za-z]{3,9})\s+(\d{1,2})"
        r"(?:\s+\d{2}:\d{2}:\d{2}\s+\w+)?\s+(\d{4})\b",
        str(value or ""),
    )
    if not match:
        return ""
    month = _MONTHS.get(match.group(1).casefold())
    if not month:
        return ""
    try:
        return date(
            int(match.group(3)), month, int(match.group(2))
        ).isoformat()
    except ValueError:
        return ""


def _location_fields(value):
    parts = [_clean(part) for part in str(value or "").split(",")]
    parts = [part for part in parts if part]
    country_index = next(
        (
            index
            for index, part in enumerate(parts)
            if part.casefold() in {"br", "brasil", "brazil"}
        ),
        None,
    )
    if country_index is None:
        return (parts[0] if parts else ""), "", "", ""
    city = parts[0]
    state = parts[-2] if len(parts) >= 3 else ""
    return city, state, "BR", "BR"


def _description(markup):
    parser = _DescriptionParser()
    parser.feed(markup or "")
    parser.close()
    return _clean(" ".join(parser.parts))[:6000]


def _normalize(card):
    native_id, url, title, location, department = card
    try:
        detail_markup = get_text(url, timeout=20, retries=2)
    except Exception:
        detail_markup = ""

    description = _description(detail_markup)
    detail_location = _meta_content(detail_markup, "addressLocality")
    detail_state = _meta_content(detail_markup, "addressRegion")
    detail_country = _meta_content(detail_markup, "addressCountry")
    city, state, country, market = _location_fields(location)
    if detail_location:
        city = _clean(detail_location)
    if detail_state:
        state = _clean(detail_state)
    if detail_country.casefold() in {"br", "brasil", "brazil"}:
        country, market = "BR", "BR"
    # The listing is explicitly constrained to location=Brasil. Preserve BR
    # even when a detail page omits its schema.org location metadata.
    if not country:
        country, market = "BR", "BR"

    published = _published_date(_meta_content(detail_markup, "datePosted"))
    model_text = " ".join(
        (
            description,
            _meta_content(detail_markup, "jobLocationType"),
            _meta_content(detail_markup, "workplaceType"),
        )
    )
    return job(
        "sonda",
        native_id,
        title=title,
        company="SONDA",
        url=url,
        work_model=work_model_label(raw=model_text),
        city=city,
        state=state,
        country=country,
        market=market,
        published_date=published,
        skills=[],
        categories=[department] if department else ["Carreiras SONDA"],
        description=description,
    )


def fetch():
    """Collect all Brazil vacancies from SONDA's public search."""

    cards = {}
    total = None
    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        url = SEARCH_URL if offset == 0 else f"{SEARCH_URL}&startrow={offset}"
        markup = get_text(url, timeout=35, retries=2)
        listing = _listing_rows(markup)
        if not listing:
            break
        for job_url, title, location, department in listing:
            native_id = _native_id(job_url)
            if native_id:
                cards.setdefault(
                    native_id,
                    (native_id, job_url, title, location, department),
                )
        total = _result_total(markup) or total
        if total is None or len(cards) >= total:
            break

    if not cards:
        raise RuntimeError("SONDA não retornou vagas públicas reconhecíveis")

    workers = min(DETAIL_WORKERS, len(cards))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_normalize, cards.values()))
