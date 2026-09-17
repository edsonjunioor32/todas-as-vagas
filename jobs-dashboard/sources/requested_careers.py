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
CLOUDWALK_CURRENT = "https://lp.cloudwalk.io/jobs"
CLOUDWALK_LEGACY = "https://www.cloudwalk.io"
DOCUSIGN_API = "https://careers.docusign.com/api/jobs"
SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
SMARTRECRUITERS_PAGE_SIZE = 100
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



def _smartrecruiters_location_text(location):
    values = []
    for key in ("country", "countryCode", "country_code", "fullLocation", "address", "city", "region"):
        value = location.get(key)
        if isinstance(value, dict):
            values.extend(str(item).strip() for item in value.values() if item)
        elif value:
            values.append(str(value).strip())
    return " ".join(value for value in values if value)


def _smartrecruiters_country_code(location):
    value = location.get("country") or location.get("countryCode") or location.get("country_code") or ""
    if isinstance(value, dict):
        value = value.get("code") or value.get("label") or value.get("name") or ""
    value = str(value).strip()
    normalized = value.casefold()
    if normalized in {"br", "brasil", "brazil"}:
        return "BR"
    return value.upper() if len(value) == 2 else value


def _is_brazil_location(location):
    country = _smartrecruiters_country_code(location)
    if country == "BR":
        return True
    return bool(re.search(r"\b(?:brasil|brazil)\b", _smartrecruiters_location_text(location), re.I))


def _smartrecruiters_entries(company_id):
    offset = 0
    while True:
        endpoint = SMARTRECRUITERS_API.format(company=company_id)
        query = urlencode({"limit": SMARTRECRUITERS_PAGE_SIZE, "offset": offset})
        payload = get_json(f"{endpoint}?{query}", timeout=45, retries=3)
        entries = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(entries, list) or not entries:
            break
        yield from entries

        offset += len(entries)
        total = (
            (payload.get("totalFound") or payload.get("total"))
            if isinstance(payload, dict)
            else None
        )
        try:
            total = int(total) if total is not None else None
        except (TypeError, ValueError):
            total = None
        if len(entries) < SMARTRECRUITERS_PAGE_SIZE or total is None or offset >= total:
            break


def fetch_smartrecruiters(company_id, source, company, *, market="global", country_filter=None):
    """Collect one SmartRecruiters company feed using the shared adapter."""
    rows, seen = [], set()
    for data in _smartrecruiters_entries(company_id):
        if not isinstance(data, dict):
            continue
        location = data.get("location") or {}
        location = location if isinstance(location, dict) else {}
        if country_filter == "BR" and not _is_brazil_location(location):
            continue

        native_id = str(data.get("id") or "").strip()
        title = str(data.get("name") or "").strip()
        if not native_id or not title or native_id in seen:
            continue
        seen.add(native_id)

        country_code = _smartrecruiters_country_code(location)
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
        url = f"https://jobs.smartrecruiters.com/{company_id}/{native_id}-{slug}"
        rows.append(job(
            source, native_id, title=title, company=company, url=url,
            work_model=work_model_label(
                remote_flag=bool(location.get("remote")),
                raw=str(location.get("fullLocation") or location.get("address") or ""),
            ),
            city=city, state=str(location.get("region") or "").strip(),
            country=country_code or ("BR" if country_filter == "BR" else "US"),
            market=market,
            published_date=iso_date(data.get("releasedDate")),
            levels=[str(experience.get("label")).strip()] if experience.get("label") else [],
            categories=categories or [f"Carreiras {company}"],
            contract_types=[str(employment.get("label")).strip()] if employment.get("label") else [],
        ))
    return rows


def fetch_dbccompany():
    """Read DBC's official SmartRecruiters public postings API."""
    rows = fetch_smartrecruiters(
        "DBC",
        "dbccompany",
        "DBC Company",
        market="global",
    )
    if not rows:
        raise RuntimeError("DBC SmartRecruiters API returned no recognizable postings")
    return rows


def fetch_boschgroup():
    """Read Bosch's SmartRecruiters postings limited to Brazil."""
    rows = fetch_smartrecruiters(
        "BoschGroup",
        "boschgroup",
        "Bosch",
        market="BR",
        country_filter="BR",
    )
    if not rows:
        raise RuntimeError("Bosch SmartRecruiters API returned no Brazil postings")
    return rows


def _cloudwalk_title(markup):
    """Extract a vacancy title from either a heading or a visible link label."""
    heading = re.search(r"<h[1-6][^>]*>([\s\S]*?)</h[1-6]>", markup, re.I)
    value = heading.group(1) if heading else markup
    value = strip_html(html.unescape(value))
    value = re.sub(
        r"\s+(?:apply|view job|view opening|view openings)\s*$",
        "",
        value,
        flags=re.I,
    )
    if value.casefold() in {"apply", "view job", "view opening", "view openings"}:
        return ""
    return value.strip(" -|")


def _cloudwalk_link_rows(page):
    """Extract current CloudWalk /jobs/<id> links from the public listing."""
    candidates = {}
    for href, label in ANCHOR_RE.findall(page):
        href = html.unescape(href).strip()
        if not re.search(r"/jobs/[^/?#]+", href, re.I):
            continue
        title = _cloudwalk_title(label)
        if not title:
            continue
        absolute = urljoin(CLOUDWALK_CURRENT, href)
        native_id = re.search(r"/jobs/([^/?#]+)", absolute, re.I).group(1)
        current = candidates.get(absolute)
        if current is None or len(title) > len(current[0]):
            candidates[absolute] = (title, native_id, label)

    if not candidates:
        for href, label in rendered_links(
            CLOUDWALK_CURRENT, r"/jobs/[^/?#]+", timeout=45
        ):
            title = _cloudwalk_title(label)
            if not title:
                continue
            absolute = urljoin(CLOUDWALK_CURRENT, href)
            native_match = re.search(r"/jobs/([^/?#]+)", absolute, re.I)
            if not native_match:
                continue
            candidates.setdefault(
                absolute, (title, native_match.group(1), label)
            )
    return list(candidates.items())


def fetch_cloudwalk():
    """Collect active CloudWalk vacancies from both old and current layouts.

    CloudWalk moved its listing from the old Webflow /jobs-positions pages
    to the current lp.cloudwalk.io/jobs/<id> application. Keep the legacy
    parser for existing layouts and use the link catalogue as the fallback.
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
            url=urljoin(CLOUDWALK_LEGACY, path), work_model=work_model_label(raw=detail_text),
            city=location, country="BR", market="BR", categories=["CloudWalk"]))
    if rows:
        return rows

    for absolute, (title, native_id, label) in _cloudwalk_link_rows(page):
        rows.append(job(
            "cloudwalk",
            native_id,
            title=title,
            company="CloudWalk",
            url=absolute,
            work_model=work_model_label(raw=label),
            city="Brasil",
            country="BR",
            market="BR",
            categories=["CloudWalk"],
        ))
    if not rows:
        raise RuntimeError("CloudWalk page returned no active vacancy links")
    return rows
