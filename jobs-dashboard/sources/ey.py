# -*- coding: utf-8 -*-
"""Public EY #TechEY vacancies from the SuccessFactors career site.

The public search renders ordinary HTML, so this adapter deliberately uses the
server-rendered listing instead of browser automation or an authenticated SAP
endpoint. Each vacancy keeps its public detail URL and the stable numeric
identifier embedded in that URL.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from ._http import get_text


BASE_URL = "https://careers.ey.com"
SEARCH_URL = BASE_URL + "/search/?q=%23TechEY"
PAGE_SIZE = 25
MAX_PAGES = 20
DETAIL_WORKERS = 4

_MONTHS = {
    "jan": 1, "janeiro": 1, "january": 1,
    "fev": 2, "fevereiro": 2, "feb": 2, "february": 2,
    "mar": 3, "março": 3, "marco": 3, "march": 3,
    "abr": 4, "abril": 4, "apr": 4, "april": 4,
    "mai": 5, "maio": 5, "may": 5,
    "jun": 6, "junho": 6, "june": 6,
    "jul": 7, "julho": 7, "july": 7,
    "ago": 8, "agosto": 8, "aug": 8, "august": 8,
    "set": 9, "setembro": 9, "sep": 9, "sept": 9, "september": 9,
    "out": 10, "outubro": 10, "oct": 10, "october": 10,
    "nov": 11, "novembro": 11, "november": 11,
    "dez": 12, "dezembro": 12, "dec": 12, "december": 12,
}


def _classes(attrs):
    return set(dict(attrs).get("class", "").split())


def _clean(value):
    return " ".join(str(value or "").split())


class _ListingParser(HTMLParser):
    """Extract a title, public detail link and location from result rows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._in_title = False
        self._in_location = False

    def handle_starttag(self, tag, attrs):
        classes = _classes(attrs)
        if tag == "tr" and "data-row" in classes:
            self._row = {"href": "", "title": [], "location": []}
            self._in_title = False
            self._in_location = False
            return
        if not self._row:
            return
        if tag == "a" and "jobTitle-link" in classes:
            href = dict(attrs).get("href", "")
            # The markup includes a duplicate mobile anchor. The first
            # desktop link is canonical and prevents duplicate title tokens.
            self._in_title = not self._row["href"] and bool(href)
            if self._in_title:
                self._row["href"] = href
        elif tag == "td" and "colLocation" in classes:
            self._in_location = True

    def handle_endtag(self, tag):
        if tag == "a":
            self._in_title = False
        elif tag == "td":
            self._in_location = False
        elif tag == "tr" and self._row is not None:
            title = _clean(" ".join(self._row["title"]))
            location = _clean(" ".join(self._row["location"]))
            href = self._row["href"]
            if title and href:
                self.rows.append((href, title, location))
            self._row = None
            self._in_title = False
            self._in_location = False

    def handle_data(self, data):
        if not self._row:
            return
        if self._in_title:
            self._row["title"].append(data)
        elif self._in_location:
            self._row["location"].append(data)


class _DescriptionParser(HTMLParser):
    """Read only the vacancy description, excluding shared page chrome."""

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


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._ignored_depth = 0

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if not self._ignored_depth:
            self.parts.append(data)


def _listing_rows(markup):
    parser = _ListingParser()
    parser.feed(markup)
    parser.close()
    return [
        (_canonical_url(href), title, location)
        for href, title, location in parser.rows
    ]


def _canonical_url(href):
    parsed = urlsplit(urljoin(BASE_URL, href))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _native_id(url):
    match = re.search(r"/(\d+)/?$", url)
    return match.group(1) if match else ""


def _detail(markup):
    description_parser = _DescriptionParser()
    description_parser.feed(markup)
    description_parser.close()

    text_parser = _TextParser()
    text_parser.feed(markup)
    text_parser.close()
    return _clean(" ".join(description_parser.parts)), _clean(" ".join(text_parser.parts))


def _published_date(text):
    match = re.search(
        r"(?:data da abertura da vaga|posting date|date posted)\s*:?\s*"
        r"(\d{1,2})\s+(?:de\s+)?([a-zç]+)\.?\s*(?:de\s+)?(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    month = _MONTHS.get(match.group(2).casefold())
    if not month:
        return ""
    try:
        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return ""


def _location_fields(location):
    parts = [_clean(part) for part in location.split(",") if _clean(part)]
    city = parts[0] if parts else ""
    state = ""
    country = ""
    for index, part in enumerate(parts):
        normalized = part.casefold()
        if normalized in {"br", "brasil", "brazil"}:
            country = "BR"
            if index > 0 and re.fullmatch(r"[A-Za-z]{2}", parts[index - 1]):
                state = parts[index - 1].upper()
            break
    if not country and len(parts) > 1 and re.fullmatch(r"[A-Za-z]{2}", parts[1]):
        state = parts[1].upper()
    return city, state, country, "BR" if country == "BR" else "Global"


def _work_model(text):
    normalized = text.casefold()
    if re.search(r"modelo\s+(híbrido|hibrido|hybrid)", normalized):
        return "hybrid"
    if re.search(r"modelo\s+(remoto|remote)", normalized):
        return "remote"
    if re.search(r"modelo\s+(presencial|on-site)", normalized):
        return "on-site"
    if "híbrido" in normalized or "hibrido" in normalized or "hybrid" in normalized:
        return "hybrid"
    if "remoto" in normalized or "remote" in normalized:
        return "remote"
    if "presencial" in normalized or "on-site" in normalized:
        return "on-site"
    return ""


def _normalize(card):
    native_id, url, title, location = card
    try:
        detail_markup = get_text(url, timeout=15, retries=1)
    except Exception:
        detail_markup = ""
    description, detail_text = _detail(detail_markup)
    city, state, country, market = _location_fields(location)
    return {
        "source": "ey",
        "native_id": native_id,
        "title": title,
        "company": "EY",
        "url": url,
        "work_model": _work_model(detail_text),
        "city": city,
        "state": state,
        "country": country,
        "market": market,
        "skills": [],
        "levels": [],
        "categories": ["TechEY"],
        "contract_types": [],
        "published_date": _published_date(detail_text),
        "description": description,
    }


def fetch():
    """Collect every page of EY's public #TechEY search."""

    cards = {}
    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        url = SEARCH_URL if not offset else f"{SEARCH_URL}&startrow={offset}"
        listing = _listing_rows(get_text(url))
        if not listing:
            break
        for job_url, title, location in listing:
            native_id = _native_id(job_url)
            if native_id:
                cards.setdefault(native_id, (native_id, job_url, title, location))
        if len(listing) < PAGE_SIZE:
            break

    if not cards:
        raise RuntimeError("EY #TechEY não retornou vagas reconhecíveis")

    workers = min(DETAIL_WORKERS, len(cards))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_normalize, cards.values()))
