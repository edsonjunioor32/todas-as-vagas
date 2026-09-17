# -*- coding: utf-8 -*-
"""Public vacancies from the NTConsult Compleo career page.

The board is a legacy Compleo installation: its public listing is server
rendered and exposes the remaining pages through a small JSON endpoint.  The
collector only reads public listing/detail pages; it never logs in or submits
applications.
"""
import html
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json, get_text


BASE_URL = "https://ntconsult.compleo.com.br"
LISTING_URL = f"{BASE_URL}/"
SEARCH_URL = f"{BASE_URL}/Pesquisar"
DETAIL_RE = re.compile(r'href\s*=\s*["\'](/Visualizar/\d+)(?:[?#][^"\']*)?["\']', re.I)
DATE_RE = re.compile(r"Publicada\s+em:\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return
        data = {str(key).lower(): str(value or "") for key, value in attrs}
        key = (data.get("property") or data.get("name") or "").lower()
        if key in {"og:title", "og:description", "description"}:
            self.values[key] = html.unescape(data.get("content", "")).strip()


class _HeadingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._tag = ""
        self._parts = []
        self.values = []

    def handle_starttag(self, tag, _attrs):
        if tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._tag = tag.lower()
            self._parts = []

    def handle_data(self, data):
        if self._tag:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == self._tag:
            value = strip_html(" ".join(self._parts))
            if value:
                self.values.append(value)
            self._tag = ""
            self._parts = []


def _detail_urls(markup):
    seen = set()
    urls = []
    for match in DETAIL_RE.finditer(markup or ""):
        url = urljoin(BASE_URL + "/", html.unescape(match.group(1))).split("#", 1)[0]
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _listing_markup(page):
    if page == 1:
        return get_text(
            LISTING_URL,
            headers={"Referer": LISTING_URL},
            timeout=45,
            retries=3,
        )
    query = urlencode({"page": page, "pesquisa": ""})
    payload = get_json(
        f"{SEARCH_URL}?{query}",
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": LISTING_URL,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=45,
        retries=3,
    )
    if not isinstance(payload, dict) or payload.get("sucesso") is not True:
        return ""
    return str(payload.get("viewLista") or "")


def _all_detail_urls():
    urls = []
    seen = set()
    for page in range(1, 101):
        markup = _listing_markup(page)
        page_urls = _detail_urls(markup)
        new_urls = [url for url in page_urls if url not in seen]
        if not new_urls:
            break
        urls.extend(new_urls)
        seen.update(new_urls)
        if page > 1 and len(page_urls) < 10:
            break
    if not urls:
        raise RuntimeError("NTConsult returned no public vacancy links")
    return urls


def _date_value(value):
    match = DATE_RE.search(value or "")
    if not match:
        return ""
    try:
        return datetime.strptime(match.group(1), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


def _label_value(headings, prefix):
    prefix = prefix.casefold()
    for heading in headings:
        normalized = " ".join(heading.split())
        if normalized.casefold().startswith(prefix):
            return normalized[len(prefix):].strip(" :-")
    return ""


def _detail_row(url):
    markup = get_text(
        url,
        headers={"Referer": LISTING_URL},
        timeout=45,
        retries=3,
    )
    meta = _MetaParser()
    meta.feed(markup)
    headings = _HeadingParser()
    headings.feed(markup)

    title = meta.values.get("og:title", "")
    if not title:
        title = next(
            (
                value for value in headings.values
                if not value.casefold().startswith(
                    ("tipo de contratação", "publicada em:", "experiência:", "local:")
                )
            ),
            "",
        )
    title = strip_html(title)
    if not title:
        return None

    location = _label_value(headings.values, "Local")
    contract = _label_value(headings.values, "Tipo de Contratação")
    experience = _label_value(headings.values, "Experiência")
    published = next(
        (value for value in headings.values if value.casefold().startswith("publicada em:")),
        "",
    )
    city = location or "Brasil"
    state = ""
    if "/" in city:
        city, state = [part.strip() for part in city.rsplit("/", 1)]
    description = strip_html(
        meta.values.get("og:description") or meta.values.get("description") or ""
    )
    raw_context = " ".join(
        [title, location, contract, experience, description]
    )

    return job(
        "ntconsult",
        url.rstrip("/").rsplit("/", 1)[-1],
        title=title,
        company="NTConsult",
        url=url,
        work_model=work_model_label(raw=raw_context),
        city=city,
        state=state,
        country="BR",
        market="BR",
        published_date=_date_value(published),
        description=description,
        levels=[experience] if experience else [],
        contract_types=[contract] if contract else [],
    )


def fetch():
    rows = []
    for url in _all_detail_urls():
        try:
            row = _detail_row(url)
        except Exception as error:
            print(f"    [ntconsult] {url}: {str(error)[:100]}")
            continue
        if row:
            rows.append(row)
    if not rows:
        raise RuntimeError("NTConsult returned no readable public vacancies")
    return rows
