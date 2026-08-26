# -*- coding: utf-8 -*-
"""Brazilian public vacancies from Spassu's Zoho Recruit career site."""
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_text
from ._html import PublicPageParser, job_posting
from ._rendered import rendered_links


BASE_URL = "https://spassu.zohorecruit.com"
BOARD_URL = f"{BASE_URL}/jobs/Careers"
DETAIL_RE = re.compile(r"/jobs/careers/(\d+)(?:/[^/?#]*)?", re.I)
ANCHOR_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']*/jobs/Careers/\d+[^"\']*)["\'][^>]*>'
    r"([\s\S]*?)</a>",
    re.I,
)
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
LEVEL_RE = re.compile(
    r"\b(j[uú]nior|jr\.?|pleno|mid(?:[- ]level)?|s[eê]nior|sr\.?|"
    r"especialista|specialist|lead|gerente|coordenador|trainee)\b",
    re.I,
)
PCD_RE = re.compile(r"\bpcd\b|pessoa(?:s)?\s+com\s+defici", re.I)


def _text(value):
    if isinstance(value, dict):
        for key in ("name", "label", "value", "text", "description"):
            if value.get(key) not in (None, ""):
                return _text(value[key])
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value if item not in (None, ""))
    return str(value or "").strip()


def _records(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _records(child)


def _location(posting):
    value = posting.get("jobLocation") or posting.get("jobLocations") or {}
    if isinstance(value, list):
        value = value[0] if value else {}
    if isinstance(value, str):
        return value.strip(), "", "BR"
    value = value if isinstance(value, dict) else {}
    address = value.get("address") or value
    address = address if isinstance(address, dict) else {}
    city = _text(address.get("addressLocality") or address.get("city"))
    state = _text(address.get("addressRegion") or address.get("state"))
    country = _text(address.get("addressCountry") or "BR")
    return city, state, country


def _date(value, raw_text=""):
    normalized = iso_date(value)
    if normalized:
        return normalized
    match = DATE_RE.search(raw_text or "")
    if match:
        day, month, year = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def _contract_types(posting, raw_text):
    value = posting.get("employmentType") or posting.get("employment_type") or ""
    values = value if isinstance(value, list) else [value]
    labels = []
    contract_map = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "TEMPORARY": "Temporário",
        "INTERN": "Estágio",
    }
    for item in values:
        text = _text(item)
        if not text:
            continue
        labels.append(contract_map.get(text.upper(), text))
    if labels:
        return list(dict.fromkeys(labels))
    match = re.search(
        r"\b(?:efetivo|full[- ]?time|part[- ]?time|contract|tempor[aá]rio|est[aá]gio)\b",
        raw_text or "",
        re.I,
    )
    return [match.group(0)] if match else []


def _skills(value):
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        text = _text(item)
        result.extend(part.strip() for part in re.split(r"[,;|]", text) if part.strip())
    return list(dict.fromkeys(result))[:20]


def _fallback_title(label):
    text = strip_html(html.unescape(label or ""))
    text = re.split(r"\s+\|\s+|\s+-\s+(?:Remoto|Remota|Presencial)\b", text, maxsplit=1, flags=re.I)[0]
    return text.strip()


def _normalize(url, markup, fallback_title=""):
    match = DETAIL_RE.search(url)
    if not match:
        return None
    parser = PublicPageParser()
    parser.feed(markup or "")
    posting = job_posting(markup or {})
    title = _text(posting.get("title")) or (parser.headings[0] if parser.headings else "")
    title = title.strip() or _fallback_title(fallback_title)
    if not title or title.casefold() in {"more info", "mais informações"}:
        return None

    raw_text = parser.visible_text
    city, state, country = _location(posting)
    location_type = _text(
        posting.get("jobLocationType") or posting.get("job_location_type")
    ).casefold()
    model_raw = " ".join(
        (
            raw_text,
            _text(posting.get("workplaceType")),
            _text(posting.get("workModel")),
        )
    )
    work_model = "remote" if location_type in {
        "telecommute", "remote", "remoto", "work from home"
    } else work_model_label(raw=model_raw)
    if not city and re.search(r"\btrabalho\s+remoto\b|\bremot[oa]\b", raw_text, re.I):
        city = "Brasil"
    if not city:
        city = "Brasil"

    organization = posting.get("hiringOrganization") or {}
    company = _text(organization.get("name")) if isinstance(organization, dict) else ""
    description = strip_html(_text(posting.get("description")))
    if not description:
        description = strip_html(raw_text)
    categories = []
    for key in ("industry", "occupationalCategory", "department"):
        value = _text(posting.get(key))
        if value and value not in categories:
            categories.append(value)
    if not categories:
        categories = ["Spassu"]
    levels = list(dict.fromkeys(
        found.group(1).title() for found in LEVEL_RE.finditer(f"{title} {description}")
    ))
    return job(
        "spassu",
        match.group(1),
        title=title,
        company=company or "Spassu",
        url=url.split("?", 1)[0],
        work_model=work_model,
        city=city,
        state=state,
        country=country or "BR",
        market="BR",
        published_date=_date(posting.get("datePosted"), raw_text),
        expires_date=_date(posting.get("validThrough")),
        description=description,
        skills=_skills(posting.get("skills")),
        levels=levels,
        categories=categories,
        contract_types=_contract_types(posting, raw_text),
        pcd=bool(PCD_RE.search(f"{title} {description}")),
    )


def _catalog_links(markup):
    parser = PublicPageParser()
    parser.feed(markup or "")
    candidates = parser.anchors or [
        (href, label) for href, label in ANCHOR_RE.findall(markup or "")
    ]
    rows, seen = [], set()
    for href, label in candidates:
        absolute = urljoin(BASE_URL, html.unescape(href).strip())
        match = DETAIL_RE.search(absolute)
        label = strip_html(html.unescape(label))
        if not match or not label or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        rows.append((absolute, label))
    return rows


def _fetch_detail(url, label):
    try:
        markup = get_text(url, timeout=35, retries=2)
        return _normalize(url, markup, label)
    except Exception:
        return None


def fetch():
    markup = get_text(
        BOARD_URL,
        headers={
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (compatible; todas-as-vagas/1.0)",
        },
        timeout=45,
        retries=3,
    )
    links = _catalog_links(markup)
    if not links:
        links = [
            (href, strip_html(label))
            for href, label in rendered_links(
                BOARD_URL,
                r"/jobs/Careers/\d+(?:/|$)",
                timeout=60,
            )
            if DETAIL_RE.search(href)
        ]
    if not links:
        raise RuntimeError("Zoho Recruit/Spassu returned no public vacancy links")

    rows = []
    with ThreadPoolExecutor(max_workers=min(8, len(links))) as pool:
        futures = {
            pool.submit(_fetch_detail, url, label): (url, label)
            for url, label in links
        }
        for future in as_completed(futures):
            row = future.result()
            if row:
                rows.append(row)
    if not rows:
        raise RuntimeError("Spassu public catalogue contained no readable vacancies")
    rows.sort(
        key=lambda row: (row.get("published_date") or "", row["native_id"]),
        reverse=True,
    )
    return rows
