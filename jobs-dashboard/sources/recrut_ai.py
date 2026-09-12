# -*- coding: utf-8 -*-
"""Public vacancy feeds hosted by Recrut.AI."""
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, urlunsplit

from ._common import iso_date, job, strip_html, work_model_label
from ._html import PublicPageParser, job_posting
from ._http import get_text
from ._rendered import rendered_paginated_links

JOB_RE = re.compile(r"/job/([A-Z0-9]{6})(?:/|$)", re.I)
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
DEFAULT_MAX_PAGES = 100
DEFAULT_DETAIL_WORKERS = 8
DEFAULT_BOARD_WORKERS = 3

TENANTS = (
    {"source": "petlove", "company": "Petlove",
     "urls": ("https://petlove.jobs.recrut.ai/",)},
    {"source": "economart", "company": "Economart",
     "urls": ("https://economart.jobs.recrut.ai/",)},
    {"source": "savegnago", "company": "Grupo Savegnago",
     "urls": (
         "https://carreiragruposavegnago.jobs.recrut.ai/",
         "https://carreiragruposavegnago.jobs.recrut.ai/paulistaoatacadista/",
     )},
    {"source": "grupoluck", "company": "Grupo Luck",
     "urls": ("https://grupoluck.jobs.recrut.ai/",)},
    {"source": "grupokoch", "company": "Grupo Koch",
     "urls": ("https://grupokoch.jobs.recrut.ai/",)},
    {"source": "atakarejo", "company": "Atakarejo",
     "urls": ("https://atakarejo.jobs.recrut.ai/",)},
    {"source": "bravante", "company": "Grupo Bravante",
     "urls": ("https://bravante.jobs.recrut.ai/",)},
    {"source": "supermercadosvianense", "company": "Supermercados Vianense",
     "urls": ("https://supermercadosvianense.jobs.recrut.ai/",)},
    {"source": "recibom", "company": "Recibom",
     "urls": ("https://recibom.jobs.recrut.ai/",)},
    {"source": "vagasdiaadia", "company": "Atacadão Dia a Dia",
     "urls": ("https://vagasdiaadia.jobs.recrut.ai/",)},
    {"source": "grupovanguarda", "company": "Grupo Vanguarda",
     "urls": ("https://grupovanguarda.jobs.recrut.ai/",)},
    {"source": "tirol", "company": "Laticínios Tirol",
     "urls": ("https://tirol.jobs.recrut.ai/",)},
    {"source": "novomateus", "company": "Novo Mateus",
     "urls": ("https://novomateus.jobs.recrut.ai/",)},
)


def _canonical_url(href, base_url=""):
    absolute = urljoin(base_url, html.unescape(str(href or "")).strip())
    parsed = urlsplit(absolute)
    match = JOB_RE.search(parsed.path or "")
    if not match:
        return ""
    return urlunsplit((
        parsed.scheme or "https", parsed.netloc,
        f"/job/{match.group(1).upper()}", "", "",
    ))


def _job_id(url):
    match = JOB_RE.search(urlsplit(url).path or "")
    return match.group(1).upper() if match else ""


def _static_links(url, markup):
    host = urlsplit(url).netloc.casefold()
    links = {}
    for href in HREF_RE.findall(markup or ""):
        absolute = _canonical_url(href, url)
        if absolute and urlsplit(absolute).netloc.casefold() == host:
            links.setdefault(absolute, "")
    return list(links.items())


def _listing_links(url):
    try:
        markup = get_text(url, timeout=35, retries=2)
        links = _static_links(url, markup)
        if links:
            return links
    except Exception:
        pass
    return rendered_paginated_links(
        url, r"/job/[A-Z0-9]{6}(?:[/?#]|$)", timeout=120,
        max_pages=max(1, int(
            os.environ.get("RECRUT_AI_MAX_PAGES") or DEFAULT_MAX_PAGES
        )),
    )


def _location(posting):
    location = posting.get("jobLocation") or {}
    if isinstance(location, list):
        location = next((item for item in location if isinstance(item, dict)), {})
    if not isinstance(location, dict):
        location = {}
    address = location.get("address") or location
    if isinstance(address, list):
        address = next((item for item in address if isinstance(item, dict)), {})
    if not isinstance(address, dict):
        address = {}
    return (
        str(address.get("addressLocality") or address.get("city") or "").strip(),
        str(address.get("addressRegion") or address.get("region") or "").strip(),
        str(address.get("addressCountry") or address.get("country") or "BR").strip(),
    )


def _skills(posting):
    value = posting.get("skills") or posting.get("qualifications") or ""
    values = value if isinstance(value, list) else re.split(r"[,;|\n]+", str(value))
    return list(dict.fromkeys(
        strip_html(item).strip() for item in values if strip_html(item).strip()
    ))[:20]


def _parse_detail(source, fallback_company, url, fallback_text=""):
    markup = get_text(url, timeout=40, retries=2)
    parser = PublicPageParser()
    parser.feed(markup)
    posting = job_posting(markup)
    title = strip_html(posting.get("title") or "").strip()
    if not title:
        title = next((
            strip_html(value).strip() for value in parser.headings
            if strip_html(value).strip()
            and strip_html(value).casefold() not in {"careers", "our openings"}
        ), "")
    if not title and fallback_text:
        title = strip_html(fallback_text).split(" · ")[0].strip()
    native_id = _job_id(url)
    if not native_id or not title:
        return None

    organization = posting.get("hiringOrganization") or {}
    if isinstance(organization, list):
        organization = next((item for item in organization if isinstance(item, dict)), {})
    company = (
        str(organization.get("name") or "").strip()
        if isinstance(organization, dict) else ""
    ) or fallback_company
    city, state, country = _location(posting)
    visible = parser.visible_text
    raw_model = " ".join(
        str(posting.get(key) or "")
        for key in ("jobLocationType", "employmentType", "description")
    ) + " " + visible
    description = strip_html(posting.get("description") or visible)
    employment = posting.get("employmentType")
    return job(
        source, native_id, title=title, company=company, url=url,
        work_model=work_model_label(raw=raw_model),
        city=city or ("Brasil" if re.search(r"\b(remote|remoto)\b", raw_model, re.I) else ""),
        state=state, country=country or "BR", market="BR",
        published_date=iso_date(posting.get("datePosted")),
        description=description, skills=_skills(posting),
        categories=["Recrut.AI"],
        contract_types=[str(employment).strip()] if employment else [],
    )


def _fetch_tenant(config):
    links = {}
    for listing_url in config["urls"]:
        for href, label in _listing_links(listing_url):
            canonical = _canonical_url(href, listing_url)
            if canonical:
                links.setdefault(canonical, label)
    if not links:
        raise RuntimeError(f"{config['company']} não expôs links públicos de vagas")

    workers = min(max(1, int(
        os.environ.get("RECRUT_AI_DETAIL_WORKERS") or DEFAULT_DETAIL_WORKERS
    )), 12)
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_parse_detail, config["source"], config["company"], url, label): url
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
        raise RuntimeError(f"{config['company']} não retornou vagas reconhecíveis")
    return list(unique.values())


def fetch_petlove():
    return _fetch_tenant(TENANTS[0])


def fetch_economart():
    return _fetch_tenant(TENANTS[1])


def fetch_savegnago():
    return _fetch_tenant(TENANTS[2])


def fetch_grupoluck():
    return _fetch_tenant(TENANTS[3])


def fetch_grupokoch():
    return _fetch_tenant(TENANTS[4])


def fetch_atakarejo():
    return _fetch_tenant(TENANTS[5])


def fetch_bravante():
    return _fetch_tenant(TENANTS[6])


def fetch_supermercadosvianense():
    return _fetch_tenant(TENANTS[7])


def fetch_recibom():
    return _fetch_tenant(TENANTS[8])


def fetch_vagasdiaadia():
    return _fetch_tenant(TENANTS[9])


def fetch_grupovanguarda():
    return _fetch_tenant(TENANTS[10])


def fetch_tirol():
    return _fetch_tenant(TENANTS[11])


def fetch_novomateus():
    return _fetch_tenant(TENANTS[12])


TARGETS = tuple(
    (config["source"], globals()[f"fetch_{config['source']}"])
    for config in TENANTS
)
