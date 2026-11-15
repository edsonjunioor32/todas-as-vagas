# -*- coding: utf-8 -*-
"""Adaptadores para os portais solicitados em 27/08/2026.

Os quadros Workday, Abler e Lever por empresa vivem agora em ``workday.py``,
``abler.py`` e ``ats_boards.py``; este módulo mantém apelidos para eles e os
adaptadores específicos de cada empresa.

As funções deste módulo são deliberadamente independentes do catálogo atual:
a validação pode consultar as fontes e a mesclagem posterior pode substituir
somente as linhas pertencentes a estas fontes.
"""
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import urllib.parse
from html.parser import HTMLParser
from urllib.parse import urljoin

from ._common import BRAZIL_WORDS, is_brazil_location, iso_date, job, strip_html, work_model_label
from ._http import get_text
from . import abler as abler_source
from . import ats_boards as ats_boards_source
from . import compleo as compleo_source
from . import workday as workday_source


# Workday, Abler e Lever por empresa migraram em 15/11/2026 para módulos por
# plataforma (workday.py, abler.py, ats_boards.py). Os nomes antigos seguem
# disponíveis como apelidos para o validador/mesclador de portais dinâmicos.
WORKDAY = workday_source.TENANTS
WORKDAY_API = workday_source.API

BRAZIL_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}


NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def _next_data(page):
    match = NEXT_DATA_RE.search(page)
    if not match:
        raise RuntimeError("page without __NEXT_DATA__")
    return json.loads(html.unescape(match.group(1)))



_workday_rows = workday_source.fetch_tenant
fetch_avanade = workday_source.FETCHERS["avanade"]
fetch_santander = workday_source.FETCHERS["santander"]
fetch_iberdrola = workday_source.FETCHERS["iberdrola"]
fetch_iqvia = workday_source.FETCHERS["iqvia"]
fetch_mdlz = workday_source.FETCHERS["mdlz"]
fetch_edenred = workday_source.FETCHERS["edenred"]
fetch_acciona = workday_source.FETCHERS["acciona"]


def _normalised_value(value):
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or value.get("code") or ""
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _is_brazilian_job_posting(country, region, location):
    country_value = _normalised_value(country).casefold()
    if country_value in {"br", "bra", "brasil", "brazil"}:
        return True
    if _normalised_value(region).upper() in BRAZIL_UFS:
        return True
    return bool(
        is_brazil_location(location) or BRAZIL_WORDS.search(str(location or ""))
    )



def _structured_work_model(text):
    """Prefer an explicit hybrid/on-site declaration over prose mentions."""
    value = str(text or "").casefold()
    if re.search(r"\b(?:h[ií]brid[oa]|hybrid)\b", value):
        return "hybrid"
    if re.search(r"\b(?:on[- ]?site|presencial|in[- ]office)\b", value):
        return "on-site"
    if re.search(r"\b(?:remote|remot[oa]|anywhere|home[- ]?office)\b", value):
        return "remote"
    return ""


def _visible_page_text(page):
    visible = re.sub(
        r"<(script|style|noscript|template)\b[^>]*>.*?</\1>",
        " ",
        page or "",
        flags=re.I | re.S,
    )
    return strip_html(visible, limit=max(6000, len(visible)))


def _huntit_work_model(page, description):
    """Read explicit Hunt IT badges before full-page prose."""
    visible = _visible_page_text(page)
    match = re.search(
        r"\(\s*(presencial|h[ií]brido|remoto)\s*\)",
        visible,
        re.I,
    )
    if match:
        model = match.group(1).casefold()
        if model == "presencial":
            return "on-site"
        if model in {"híbrido", "hibrido"}:
            return "hybrid"
        return "remote"
    return _structured_work_model(description) or _structured_work_model(visible)


def _jsonld_rows_from_page(source, url, company, page):
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page, re.I | re.S,
    )
    rows = []
    for block in blocks:
        try:
            payload = json.loads(html.unescape(block))
        except (TypeError, ValueError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            if not isinstance(value, dict) or value.get("@type") != "JobPosting":
                continue
            title = str(value.get("title") or "").strip()
            if not title:
                continue
            location_data = value.get("jobLocation") or {}
            if isinstance(location_data, list):
                location_data = location_data[0] if location_data else {}
            address = (location_data.get("address") or {}) if isinstance(location_data, dict) else {}
            locality = str(address.get("addressLocality") or "").strip()
            region = str(address.get("addressRegion") or "").strip()
            raw_country = address.get("addressCountry")
            country = _normalised_value(raw_country) or "BR"
            location = ", ".join(part for part in (locality, region) if part)
            if location and not _is_brazilian_job_posting(raw_country, region, location):
                continue
            identifier = value.get("identifier") or {}
            native_id = str(
                identifier.get("value")
                if isinstance(identifier, dict) else identifier or title
            )
            raw_description = value.get("description") or ""
            description = strip_html(raw_description)
            full_description = _visible_page_text(raw_description)
            rows.append(job(
                source, native_id, title=title, company=company,
                url=str(value.get("url") or url),
                work_model=(
                    _huntit_work_model(page, full_description)
                    if source == "huntit"
                    else _structured_work_model(
                        f"{title} {location} {description[:1800]}"
                    )
                ),
                city=location, country=country or "BR", market="BR",
                published_date=iso_date(value.get("datePosted")),
                description=description,
                contract_types=[
                    str(value.get("employmentType") or "").strip()
                ] if value.get("employmentType") else [],
            ))
    return rows


def _jsonld_rows(source, url, company, timeout=45, retries=3):
    page = get_text(url, timeout=timeout, retries=retries)
    return _jsonld_rows_from_page(source, url, company, page)




def _anchor_rows(source, url, company, pattern=r'/(?:vaga|vagas|job|jobs)/[^"?#]+'):
    page = get_text(url, timeout=45, retries=3)
    rows, seen = [], set()
    for href, label in re.findall(
        rf'<a[^>]+href=["\']([^"\']*{pattern}[^"\']*)["\'][^>]*>(.*?)</a>',
        page, re.I | re.S,
    ):
        title = strip_html(html.unescape(label))
        absolute = urljoin(url, href)
        if len(title) < 4 or absolute in seen:
            continue
        seen.add(absolute)
        rows.append(job(
            source, absolute.rstrip("/").split("/")[-1], title=title, company=company,
            url=absolute,
            work_model="" if source == "huntit" else work_model_label(raw=title),
            city="", country="BR", market="BR",
        ))
    if not rows:
        rows = _jsonld_rows(source, url, company)
    if not rows:
        raise RuntimeError(f"{source} returned no public vacancies")
    return rows


def _enrich_huntit_rows(rows):
    """Use the detail page as the authority for location, modality and date."""
    enriched = list(rows)
    workers = min(8, max(1, len(enriched)))

    def load(index, fallback):
        try:
            details = _jsonld_rows(
                "huntit", fallback["url"], "Hunt IT", timeout=30, retries=1
            )
            if not details:
                return index, fallback
            detail = details[0]
            detail["native_id"] = fallback["native_id"]
            detail["url"] = fallback["url"]
            detail["title"] = detail.get("title") or fallback["title"]
            for field in ("work_model", "city", "state", "country", "market", "published_date"):
                if not detail.get(field) and fallback.get(field):
                    detail[field] = fallback[field]
            return index, detail
        except Exception:
            return index, fallback

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(load, index, row)
            for index, row in enumerate(enriched)
        ]
        for future in as_completed(futures):
            index, row = future.result()
            enriched[index] = row
    return enriched


def fetch_huntit():
    rows = _anchor_rows("huntit", "https://huntit.com.br/vagas/", "Hunt IT")
    return _enrich_huntit_rows(rows)


def fetch_forza():
    return _anchor_rows("forza", "https://forzabr.rhgestor.com.br/vagas", "Forza BR")


class _SalecoListingParser(HTMLParser):
    """Pair each vacancy link with the heading in its listing card."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.last_heading = ""
        self._heading_tag = ""
        self._heading_parts = []
        self._anchor_href = ""
        self._anchor_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = dict(attrs)
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_tag = tag
            self._heading_parts = []
        elif tag == "a" and self._anchor_href == "":
            self._anchor_href = attributes.get("href") or ""
            self._anchor_parts = []

    def handle_data(self, data):
        if self._heading_tag:
            self._heading_parts.append(data)
        if self._anchor_href:
            self._anchor_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == self._heading_tag:
            heading = strip_html(" ".join(self._heading_parts))
            if heading:
                self.last_heading = heading
            self._heading_tag = ""
            self._heading_parts = []
        elif tag == "a" and self._anchor_href:
            label = strip_html(" ".join(self._anchor_parts))
            self.links.append((self._anchor_href, label, self.last_heading))
            self._anchor_href = ""
            self._anchor_parts = []


def _saleco_slug_title(url):
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    title = re.sub(r"[-_]+", " ", urllib.parse.unquote(slug)).strip()
    return re.sub(r"\s{2,}", " ", title)


def fetch_saleco():
    listing_url = "https://www.saleco.com.br/jobs"
    page = get_text(listing_url, timeout=45, retries=3)
    parser = _SalecoListingParser()
    parser.feed(page)
    rows, seen = [], set()
    for href, label, heading in parser.links:
        absolute = urljoin(listing_url, html.unescape(href)).split("#", 1)[0]
        parsed = urllib.parse.urlsplit(absolute)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.netloc.casefold() not in {"www.saleco.com.br", "saleco.com.br"}
            or not parsed.path.casefold().startswith("/jobs/")
        ):
            continue
        if absolute.rstrip("/") == listing_url.rstrip("/") or absolute in seen:
            continue
        seen.add(absolute)
        title = heading if heading and heading.casefold() != "exibir vaga" else ""
        if not title:
            title = _saleco_slug_title(absolute)
        if len(title) < 4 or title.casefold() == "exibir vaga":
            continue
        rows.append(job(
            "saleco",
            absolute.rstrip("/").rsplit("/", 1)[-1],
            title=title,
            company="Saleco",
            url=absolute,
            work_model=work_model_label(raw=title),
            city="Brasil",
            country="BR",
            market="BR",
        ))
    if not rows:
        rows = _jsonld_rows("saleco", listing_url, "Saleco")
    if not rows:
        raise RuntimeError("saleco returned no public vacancies")
    return rows

def fetch_elis():
    return _anchor_rows("elis", "https://elisbrasil.pandape.infojobs.com.br/", "Elis Brasil", r'/Detail/\d+')



_abler_rows = abler_source.fetch_board


def _compleo_row(source, url, company):
    return compleo_source._compleo_row(source, url, company)


def _compleo_rows(source, board, company):
    return compleo_source.fetch_board(source, board, company)


fetch_abler_talentodovalesc = abler_source.BOARD_FETCHERS["talentodovalesc"]
fetch_precisionrh = abler_source.BOARD_FETCHERS["precisionrh"]


def fetch_beq():
    return _compleo_rows("beq", "BEQ", "B&Q Energia")


fetch_lever_board = ats_boards_source.fetch_lever_board
fetch_flash = ats_boards_source.LEVER_BOARD_FETCHERS["flash"]
fetch_neon = ats_boards_source.LEVER_BOARD_FETCHERS["neon"]
fetch_zippi = ats_boards_source.LEVER_BOARD_FETCHERS["zippi"]
fetch_bv = ats_boards_source.LEVER_BOARD_FETCHERS["bv"]


TARGETS = (
    ("avanade", fetch_avanade),
    ("huntit", fetch_huntit),
    ("talentodovalesc", fetch_abler_talentodovalesc),
    ("precisionrh", fetch_precisionrh),
    ("beq", fetch_beq),
    ("forza", fetch_forza),
    ("saleco", fetch_saleco),
    ("elis", fetch_elis),
    ("flash", fetch_flash),
    ("neon", fetch_neon),
    ("zippi", fetch_zippi),
    ("bv", fetch_bv),
    ("santander", fetch_santander),
    ("iberdrola", fetch_iberdrola),
    ("iqvia", fetch_iqvia),
    ("mdlz", fetch_mdlz),
    ("edenred", fetch_edenred),
)

