# -*- coding: utf-8 -*-
"""Company career pages requested for the Brazilian vacancy collection."""
import html
import re
from urllib.parse import urlencode, urljoin

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json, get_text
from ._rendered import rendered_links

DOCUSIGN = "https://careers.docusign.com/careers-home/jobs?locations=Sao%20Paulo,S%C3%A3o%20Paulo,Brazil%7C,,Brazil&page={page}"
DBC = "https://vagas.dbccompany.com.br/vagas"
CloudWalk = "https://www.cloudwalk.io/jobs"
DOCUSIGN_API = "https://careers.docusign.com/api/jobs"
SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies/dbc/postings"
ANCHOR_RE = re.compile(r'<a[^>]+href=["\']([^"\']*(?:/jobs/|/vagas/)[^"\']*)["\'][^>]*>([\s\S]*?)</a>', re.I)


def _links(url):
    page = get_text(url, timeout=35, retries=2)
    seen, rows = set(), []
    for href, label in ANCHOR_RE.findall(page):
        href = html.unescape(href).strip()
        label = strip_html(html.unescape(label))
        absolute = urljoin(url, href)
        if absolute and label and absolute not in seen:
            seen.add(absolute)
            rows.append((absolute, label))
    if not rows:
        # DBC and DocuSign currently add the cards after JavaScript hydration.
        for href, label in rendered_links(url, r"(?:/jobs/|/vagas/)"):
            label = strip_html(html.unescape(label))
            if href and label and href not in seen:
                seen.add(href)
                rows.append((href, label))
    return rows


def fetch_docusign():
    """Read DocuSign's Jibe JSON catalogue instead of its JS-only cards."""
    query = urlencode({"country": "Brazil", "limit": 100, "page": 1})
    payload = get_json(f"{DOCUSIGN_API}?{query}", timeout=45, retries=3)
    entries = payload.get("jobs") if isinstance(payload, dict) else None
    if not entries:
        raise RuntimeError("DocuSign API returned no Brazil vacancies")

    rows, seen = [], set()
    for entry in entries:
        data = entry.get("data") if isinstance(entry, dict) else None
        if not isinstance(data, dict):
            continue
        native_id = str(data.get("slug") or data.get("req_id") or "").strip()
        title = str(data.get("title") or "").strip()
        if not native_id or not title or native_id in seen:
            continue
        seen.add(native_id)
        location_name = str(data.get("location_name") or "").strip()
        city = str(data.get("city") or "").strip()
        if not city:
            city = "Brasil" if "remote" in location_name.casefold() else (location_name or "Brasil")
        tags = []
        for key in ("tags1", "tags2", "tags3", "tags4", "tags5"):
            value = data.get(key) or []
            tags.extend(value if isinstance(value, list) else [value])
        categories = [
            str(item.get("name") or "").strip()
            for item in (data.get("categories") or [])
            if isinstance(item, dict) and item.get("name")
        ]
        employment = str(data.get("employment_type") or "").strip()
        levels = []
        level_match = re.search(r"\b(junior|jr\.?|pleno|senior|sr\.?|lead|director|manager)\b", title, re.I)
        if level_match:
            levels.append(level_match.group(1))
        rows.append(job(
            "docusign", native_id, title=title, company="DocuSign",
            url=f"https://careers.docusign.com/careers-home/jobs/{native_id}?lang=en-us",
            work_model=work_model_label(raw=" ".join([location_name, *map(str, tags)])),
            city=city, state=str(data.get("state") or "").strip(),
            country=str(data.get("country_code") or "BR").strip(), market="BR",
            published_date=iso_date(data.get("posted_date")),
            description=strip_html(data.get("description") or ""),
            skills=[str(value).strip() for value in tags if str(value).strip()],
            levels=levels, categories=categories or ["Carreiras DocuSign"],
            contract_types=[employment] if employment else [],
        ))
    if not rows:
        raise RuntimeError("DocuSign API returned no recognizable Brazil vacancy records")
    return rows


def fetch_dbccompany():
    """Read DBC's official SmartRecruiters public postings API.

    ``vagas.dbccompany.com.br/vagas`` now returns 404; the live company
    catalogue is served by SmartRecruiters and exposes the same public jobs as
    JSON, including location, modality, contract and seniority metadata.
    """
    payload = get_json(f"{SMARTRECRUITERS_API}?limit=100", timeout=45, retries=3)
    entries = payload.get("content") if isinstance(payload, dict) else None
    if not entries:
        raise RuntimeError("DBC SmartRecruiters API returned no public postings")

    rows, seen = [], set()
    for data in entries:
        if not isinstance(data, dict):
            continue
        native_id = str(data.get("id") or "").strip()
        title = str(data.get("name") or "").strip()
        if not native_id or not title or native_id in seen:
            continue
        seen.add(native_id)
        location = data.get("location") or {}
        location = location if isinstance(location, dict) else {}
        country = str(location.get("country") or "").strip()
        country_code = country.upper() if len(country) == 2 else country
        city = str(location.get("city") or location.get("address") or "Brasil").strip()
        categories = []
        for key in ("industry", "department", "function"):
            value = data.get(key) or {}
            label = value.get("label") if isinstance(value, dict) else ""
            if label:
                categories.append(str(label).strip())
        employment = data.get("typeOfEmployment") or {}
        experience = data.get("experienceLevel") or {}
        slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
        url = f"https://jobs.smartrecruiters.com/DBC/{native_id}-{slug}"
        rows.append(job(
            "dbccompany", native_id, title=title, company="DBC Company", url=url,
            work_model=work_model_label(
                remote_flag=bool(location.get("remote")),
                raw=str(location.get("fullLocation") or location.get("address") or ""),
            ),
            city=city, state=str(location.get("region") or "").strip(),
            country=country_code or "US", market="global",
            published_date=iso_date(data.get("releasedDate")),
            levels=[str(experience.get("label")).strip()] if experience.get("label") else [],
            categories=categories or ["Carreiras DBC"],
            contract_types=[str(employment.get("label")).strip()] if employment.get("label") else [],
        ))
    if not rows:
        raise RuntimeError("DBC SmartRecruiters API returned no recognizable postings")
    return rows


def fetch_cloudwalk():
    """CloudWalk publishes its active Webflow CMS cards in the public HTML.

    The portal exposes no publication date, so the pipeline intentionally uses
    its normal first-seen fallback and removes records after two months.
    """
    page = get_text(CloudWalk, timeout=35, retries=2)
    card_re = re.compile(
        r'<div[^>]+class="jobs-list-cms-position"[^>]*>([\s\S]*?)'
        r'<a[^>]+href="([^"]*/jobs-positions/[^"]+)"', re.I)
    rows, seen = [], set()
    for block, path in card_re.findall(page):
        title_match = re.search(r'is-open-position">([\s\S]*?)</div>', block, re.I)
        if not title_match:
            continue
        title = strip_html(html.unescape(title_match.group(1)))
        native_id = path.rstrip('/').split('/')[-1]
        if not title or native_id in seen:
            continue
        seen.add(native_id)
        details = [strip_html(html.unescape(value)) for value in re.findall(
            r'fs-list-field="(?:location-type|work-type|location)"[^>]*>([\s\S]*?)</div>', block, re.I)]
        detail_text = ' '.join(details)
        location = next((value for value in details if value and value.casefold() not in {"remote", "full time", "full time - remote"}), "Brasil")
        rows.append(job("cloudwalk", native_id, title=title, company="CloudWalk",
            url=urljoin(CloudWalk, path), work_model=work_model_label(raw=detail_text),
            city=location, country="BR", market="BR", categories=["CloudWalk"]))
    if not rows:
        raise RuntimeError("CloudWalk page returned no active vacancy cards")
    return rows
