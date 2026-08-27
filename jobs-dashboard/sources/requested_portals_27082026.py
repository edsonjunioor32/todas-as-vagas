# -*- coding: utf-8 -*-
"""Adaptadores para os portais solicitados em 27/08/2026.

As funções deste módulo são deliberadamente independentes do catálogo atual:
a validação pode consultar as fontes e a mesclagem posterior pode substituir
somente as linhas pertencentes a estas fontes.
"""
import html
import json
import re
from urllib.parse import urljoin

from ._common import is_brazil_location, iso_date, job, strip_html, work_model_label
from ._http import get_json, get_text, post_json


WORKDAY = {
    "avanade": {
        "host": "accenture.wd103.myworkdayjobs.com",
        "tenant": "accenture",
        "site": "AvanadeCareers",
        "company": "Avanade",
        "url": "https://accenture.wd103.myworkdayjobs.com/pt-BR/AvanadeCareers/",
    },
    "santander": {
        "host": "santander.wd3.myworkdayjobs.com",
        "tenant": "santander",
        "site": "SantanderCareers",
        "company": "Santander",
        "url": "https://santander.wd3.myworkdayjobs.com/pt-BR/SantanderCareers",
    },
    "iberdrola": {
        "host": "iberdrola.wd3.myworkdayjobs.com",
        "tenant": "iberdrola",
        "site": "Iberdrola",
        "company": "Iberdrola",
        "url": "https://iberdrola.wd3.myworkdayjobs.com/pt-BR/Iberdrola",
    },
    "iqvia": {
        "host": "iqvia.wd1.myworkdayjobs.com",
        "tenant": "iqvia",
        "site": "IQVIA",
        "company": "IQVIA",
        "url": "https://iqvia.wd1.myworkdayjobs.com/pt-BR/IQVIA",
    },
    "mdlz": {
        "host": "mdlz.wd3.myworkdayjobs.com",
        "tenant": "mdlz",
        "site": "External",
        "company": "Mondelēz International",
        "url": "https://mdlz.wd3.myworkdayjobs.com/pt-BR/External",
    },
}

WORKDAY_API = "https://{host}/wday/cxs/{tenant}/{site}/jobs"
BRAZIL_WORDS = re.compile(
    r"brasil|brazil|s[aã]o paulo|rio de janeiro|campinas|curitiba|recife|"
    r"bras[ií]lia|belo horizonte|salvador|fortaleza|porto alegre|paran[aá]|"
    r"santa catarina|minas gerais|bahia|pernambuco|cear[aá]",
    re.I,
)


def _workday_rows(name):
    config = WORKDAY[name]
    rows, seen = [], set()
    offset, limit = 0, 20
    while offset < 5000:
        payload = post_json(
            WORKDAY_API.format(**config),
            {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=60,
            retries=3,
        )
        postings = payload.get("jobPostings") or []
        if not postings:
            break
        for item in postings:
            title = str(item.get("title") or "").strip()
            location = str(item.get("locationsText") or item.get("location") or "").strip()
            external = str(item.get("externalPath") or "").strip()
            native_id = str(item.get("bulletFields", [None])[0] or item.get("jobReqId") or external).strip()
            if not title or not external or not native_id or native_id in seen:
                continue
            if not BRAZIL_WORDS.search(location) and not is_brazil_location(location):
                continue
            seen.add(native_id)
            rows.append(job(
                name, native_id, title=title, company=config["company"],
                url=urljoin(config["url"], external.lstrip("/")),
                work_model=work_model_label(raw=f"{title} {location}"),
                city=location or "Brasil", country="BR", market="BR",
                published_date=iso_date(item.get("postedOn") or item.get("postedDate")),
                description=strip_html(item.get("description") or ""),
            ))
        total = int(payload.get("total") or 0)
        offset += limit
        if total and offset >= total:
            break
        if len(postings) < limit:
            break
    if not rows:
        raise RuntimeError(f"Workday/{name} returned no Brazilian vacancies")
    return rows


def fetch_avanade():
    return _workday_rows("avanade")


def fetch_santander():
    return _workday_rows("santander")


def fetch_iberdrola():
    return _workday_rows("iberdrola")


def fetch_iqvia():
    return _workday_rows("iqvia")


def fetch_mdlz():
    return _workday_rows("mdlz")


def _jsonld_rows(source, url, company):
    page = get_text(url, timeout=45, retries=3)
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
            location = ", ".join(
                str(address.get(key) or "").strip()
                for key in ("addressLocality", "addressRegion", "addressCountry")
                if str(address.get(key) or "").strip()
            )
            if location and not is_brazil_location(location) and not BRAZIL_WORDS.search(location):
                continue
            identifier = value.get("identifier") or {}
            native_id = str(identifier.get("value") if isinstance(identifier, dict) else identifier or title)
            rows.append(job(
                source, native_id, title=title, company=company,
                url=str(value.get("url") or url), work_model=work_model_label(raw=f"{title} {location}"),
                city=location or "Brasil", country="BR", market="BR",
                published_date=iso_date(value.get("datePosted")),
                description=strip_html(value.get("description") or ""),
                contract_types=[str(value.get("employmentType") or "").strip()] if value.get("employmentType") else [],
            ))
    return rows


def _anchor_rows(source, url, company, pattern=r"/(?:vaga|vagas|job|jobs)/[^"?#]+"):
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
            url=absolute, work_model=work_model_label(raw=title),
            city="Brasil", country="BR", market="BR",
        ))
    if not rows:
        rows = _jsonld_rows(source, url, company)
    if not rows:
        raise RuntimeError(f"{source} returned no public vacancies")
    return rows


def fetch_huntit():
    return _anchor_rows("huntit", "https://huntit.com.br/vagas/", "Hunt IT")


def fetch_forza():
    return _anchor_rows("forza", "https://forzabr.rhgestor.com.br/vagas", "Forza BR")


def fetch_saleco():
    return _anchor_rows("saleco", "https://www.saleco.com.br/jobs", "Saleco")


def fetch_elis():
    return _anchor_rows("elis", "https://elisbrasil.pandape.infojobs.com.br/", "Elis Brasil")


def fetch_abler_talentodovalesc():
    url = "https://ats.abler.com.br/jobs/talentodovalesc"
    return _anchor_rows("talentodovalesc", url, "Talento do Vale SC", r"/jobs/[^"?#]+")


def fetch_beq():
    return _anchor_rows("beq", "https://jobs.compleo.app/BEQ/joblist", "B&Q Energia", r"/(?:job|jobdetail|BEQ)/[^"?#]+")


def fetch_lever_board(source, board, company):
    payload = get_json(f"https://api.lever.co/v0/postings/{board}?mode=json", timeout=45, retries=3)
    rows = []
    for item in payload if isinstance(payload, list) else []:
        categories = item.get("categories") or {}
        location = str(categories.get("location") or "").strip()
        rows.append(job(
            source, item.get("id"), title=item.get("text"), company=company,
            url=item.get("hostedUrl") or item.get("applyUrl") or "",
            work_model=work_model_label(raw=f"{categories.get('commitment', '')} {location}"),
            city=location or "Brasil", country="BR", market="BR",
            published_date=iso_date(item.get("createdAt")),
            categories=[str(categories.get("department") or "").strip()] if categories.get("department") else [],
        ))
    if not rows:
        raise RuntimeError(f"Lever/{board} returned no vacancies")
    return rows


def fetch_flash():
    return fetch_lever_board("flash", "flashapp", "Flash")


def fetch_neon():
    return fetch_lever_board("neon", "neon", "Neon Pagamentos")


def fetch_zippi():
    return fetch_lever_board("zippi", "zippi", "Zippi")


def fetch_bv():
    return fetch_lever_board("bv", "bv", "Banco BV")


TARGETS = (
    ("avanade", fetch_avanade),
    ("huntit", fetch_huntit),
    ("talentodovalesc", fetch_abler_talentodovalesc),
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
)
