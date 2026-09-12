# -*- coding: utf-8 -*-
"""Public vacancies from the general Taggui RH board."""
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, urlunsplit

from ._common import iso_date, job, strip_html, work_model_label
from ._html import PublicPageParser, job_posting
from ._http import get_text
from ._rendered import rendered_links

BOARD_URL = "https://vagas.tagguirh.com.br/"
DETAIL_RE = re.compile(
    r"/visualizar-vaga/([^/?#]+)/([0-9]+)(?:[/?#]|$)", re.I
)
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
DEFAULT_DETAIL_WORKERS = 8


def _canonical_url(href, base_url=BOARD_URL):
    absolute = urljoin(base_url, html.unescape(str(href or "")).strip())
    parsed = urlsplit(absolute)
    match = DETAIL_RE.search(parsed.path or "")
    if not match:
        return ""
    return urlunsplit((
        parsed.scheme or "https", parsed.netloc,
        f"/visualizar-vaga/{match.group(1).casefold()}/{match.group(2)}",
        "", "",
    ))


def _native_id(url):
    match = DETAIL_RE.search(urlsplit(url).path or "")
    return f"{match.group(1).casefold()}:{match.group(2)}" if match else ""


def _listing_links(markup):
    links = {}
    for href in HREF_RE.findall(markup or ""):
        canonical = _canonical_url(href)
        if canonical:
            links.setdefault(canonical, "")
    return list(links.items())


def _detail(url, fallback_text=""):
    markup = get_text(url, timeout=40, retries=2)
    parser = PublicPageParser()
    parser.feed(markup)
    posting = job_posting(markup)
    native_id = _native_id(url)
    if not native_id:
        return None

    title = strip_html(posting.get("title") or "").strip()
    if not title:
        title = next((
            strip_html(value).strip() for value in parser.headings
            if strip_html(value).strip()
            and strip_html(value).casefold() not in {"vagas de emprego", "taggui rh"}
        ), "")
    if not title and fallback_text:
        title = strip_html(fallback_text).split(" · ")[-1].strip()
    if not title:
        return None

    organization = posting.get("hiringOrganization") or {}
    company = (
        str(organization.get("name") or "").strip()
        if isinstance(organization, dict) else ""
    )
    visible = parser.visible_text
    location = posting.get("jobLocation") or {}
    if isinstance(location, list):
        location = next((item for item in location if isinstance(item, dict)), {})
    address = location.get("address") if isinstance(location, dict) else {}
    address = address if isinstance(address, dict) else {}
    city = str(address.get("addressLocality") or "").strip()
    state = str(address.get("addressRegion") or "").strip()
    country = str(address.get("addressCountry") or "BR").strip()
    raw_model = f"{posting.get('jobLocationType') or ''} {visible}"
    description = strip_html(posting.get("description") or visible)
    employment = posting.get("employmentType")
    return job(
        "tagguirh", native_id, title=title, company=company or "Taggui RH",
        url=url, work_model=work_model_label(raw=raw_model),
        city=city or ("Brasil" if re.search(r"\b(remote|remoto)\b", raw_model, re.I) else ""),
        state=state, country=country, market="BR",
        published_date=iso_date(posting.get("datePosted")),
        description=description, categories=["Taggui RH"],
        contract_types=[str(employment).strip()] if employment else [],
    )


def fetch():
    try:
        markup = get_text(BOARD_URL, timeout=45, retries=2)
        links = _listing_links(markup)
    except Exception:
        links = []

    if not links:
        links = rendered_links(
            BOARD_URL,
            r"/visualizar-vaga/[^/?#]+/[0-9]+(?:[/?#]|$)",
            timeout=90,
        )
    if not links:
        raise RuntimeError("Taggui RH não expôs vagas públicas")

    workers = min(max(1, int(
        os.environ.get("TAGGUI_DETAIL_WORKERS") or DEFAULT_DETAIL_WORKERS
    )), 12)
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_detail, url, label): url for url, label in links
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
        raise RuntimeError("Taggui RH não retornou vagas reconhecíveis")
    return list(unique.values())
