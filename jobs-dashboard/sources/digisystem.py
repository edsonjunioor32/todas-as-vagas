# -*- coding: utf-8 -*-
"""Digisystem vacancies published through Recrutei.

The tenant page at ``jobs.recrutei.com.br/digisystem`` is a Next.js shell and
can legitimately render the empty-state HTML even while active vacancy pages
are public.  The Recrutei employment catalogue publishes an XML sitemap with
the active Digisystem URLs; each vacancy page contains a Schema.org
``JobPosting`` object with the authoritative fields.  Reading that data avoids
both the JavaScript-only tenant page and an unbounded catalogue crawl.
"""
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from ._common import iso_date, job, split_location, strip_html, work_model_label
from ._http import get_text


SITEMAP = "https://empregos.recrutei.com.br/sitemap-vagas-1.xml"
DETAIL_RE = re.compile(r"/vaga/digisystem/(\d+)(?:-[^/?#]+)?", re.I)
JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
    re.I,
)
CONTRACT_RE = re.compile(
    r'mdi-clipboard-text[\s\S]{0,500}?<p[^>]*>\s*([^<]+)', re.I
)
LEVEL_RE = re.compile(r"\b(j[uú]nior|pleno|s[eê]nior|especialista|trainee)\b", re.I)


def _sitemap_urls(markup):
    """Return unique active Digisystem detail URLs from the Recrutei sitemap."""
    urls = []
    seen = set()
    for raw in re.findall(r"<loc>([^<]+)</loc>", markup, re.I):
        url = html.unescape(raw).strip().split("?", 1)[0]
        if DETAIL_RE.search(url) and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _json_ld(page):
    for raw in JSON_LD_RE.findall(page):
        try:
            payload = json.loads(html.unescape(raw.strip()))
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("@type") == "JobPosting":
            return payload
    return None


def _location(posting):
    value = posting.get("jobLocation") or {}
    if isinstance(value, list):
        value = value[0] if value else {}
    address = value.get("address") if isinstance(value, dict) else {}
    address = address if isinstance(address, dict) else {}
    city = str(address.get("addressLocality") or "").strip()
    state = str(address.get("addressRegion") or "").strip()
    country = str(address.get("addressCountry") or "Brasil").strip()
    if city and not state and "," in city:
        city, state, _ = split_location(city)
    return city or "Brasil", state, country or "Brasil"


def _normalize(url, page):
    posting = _json_ld(page)
    match = DETAIL_RE.search(url)
    if not posting or not match:
        return None
    title = str(posting.get("title") or "").strip()
    organization = posting.get("hiringOrganization") or {}
    company = str(organization.get("name") or "Digisystem").strip()
    if not title:
        return None

    city, state, country = _location(posting)
    employment = posting.get("employmentType") or []
    if isinstance(employment, str):
        employment = [employment]
    contract_match = CONTRACT_RE.search(page)
    contract = contract_match.group(1).strip() if contract_match else ""
    if not contract:
        contract = {
            "FULL_TIME": "CLT",
            "PART_TIME": "Part-time",
            "CONTRACTOR": "PJ",
            "TEMPORARY": "Temporário",
            "INTERN": "Estágio",
        }.get(str(employment[0]).upper(), "") if employment else ""
    description = strip_html(str(posting.get("description") or ""))
    raw_text = strip_html(page)
    levels = list(dict.fromkeys(
        match.group(1).title() for match in LEVEL_RE.finditer(title + " " + description)
    ))
    skills = posting.get("skills") or ""
    if isinstance(skills, str):
        skills = [part.strip() for part in re.split(r"[,;|]", skills) if part.strip()]
    return job(
        "digisystem",
        match.group(1),
        title=title,
        company=company or "Digisystem",
        url=url,
        work_model=work_model_label(raw=raw_text),
        city=city,
        state=state,
        country=country,
        market="BR",
        published_date=iso_date(posting.get("datePosted")),
        expires_date=iso_date(posting.get("validThrough")),
        contract_types=[contract] if contract else [],
        description=description,
        skills=skills,
        levels=levels,
        categories=["Tecnologia", "Digisystem"],
    )


def _fetch_detail(url):
    try:
        page = get_text(url, timeout=35, retries=2)
        return _normalize(url, page)
    except Exception:
        # A single withdrawn page can remain in a sitemap briefly.  Keep the
        # source healthy when the remaining active pages are readable.
        return None


def fetch():
    sitemap = get_text(SITEMAP, timeout=35, retries=3)
    urls = _sitemap_urls(sitemap)
    if not urls:
        raise RuntimeError("Recrutei sitemap returned no active Digisystem URLs")

    rows = []
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
        futures = [pool.submit(_fetch_detail, url) for url in urls]
        for future in as_completed(futures):
            row = future.result()
            if row:
                rows.append(row)
    rows.sort(key=lambda row: (row.get("published_date") or "", row["native_id"]), reverse=True)
    if not rows:
        raise RuntimeError("Digisystem sitemap contained no readable JobPosting details")
    return rows
