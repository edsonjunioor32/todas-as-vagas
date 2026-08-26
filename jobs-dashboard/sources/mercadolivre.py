# -*- coding: utf-8 -*-
"""Mercado Livre's official Brazil careers catalogue.

The positions page is a JavaScript application and its CDN can reject a
plain HTTP client.  The adapter first accepts any structured data embedded in
the public document and falls back to the same visible links a normal browser
sees.  It never fabricates a modality, location or publication date when the
portal does not expose one.
"""
import html
import json
import re
from urllib.parse import parse_qs, urljoin, urlparse

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_text
from ._rendered import rendered_links


POSITIONS = "https://careers-meli.mercadolibre.com/pt/positions?country=Brazil"
BASE_URL = "https://careers-meli.mercadolibre.com"
JSON_SCRIPT_RE = re.compile(
    r"<script[^>]+(?:type=[\"']application/json[\"']|id=[\"']__NEXT_DATA__[\"'])[^>]*>"
    r"([\s\S]*?)</script>",
    re.I,
)
ANCHOR_RE = re.compile(
    r"<a[^>]+href=[\"']([^\"']*(?:/pt|/en|/es)/positions\?[^\"']*\bid=\d+[^\"']*)"
    r"[\"'][^>]*>([\s\S]*?)</a>",
    re.I,
)
ID_RE = re.compile(r"\b\d{4,}\b")
LEVEL_RE = re.compile(
    r"\b(j[uú]nior|jr\.?|pleno|mid(?:[- ]level)?|s[eê]nior|sr\.?|"
    r"especialista|specialist|lead|manager|director|trainee|intern)\b",
    re.I,
)

_ID_KEYS = ("id", "positionId", "position_id", "jobId", "job_id", "requisitionId", "requisition_id")
_TITLE_KEYS = ("title", "jobTitle", "job_title", "positionTitle", "position_title", "name")
_URL_KEYS = ("url", "href", "link", "jobUrl", "job_url", "positionUrl", "position_url")
_LOCATION_KEYS = ("location", "locations", "city", "cities", "localization", "workplace")
_COUNTRY_KEYS = ("country", "countryCode", "country_code", "countries")
_DATE_KEYS = ("publishedAt", "published_at", "publicationDate", "publication_date", "postedAt", "posted_at", "datePosted", "createdAt", "created_at")


def _first(record, keys):
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def _text(value):
    if isinstance(value, dict):
        for key in ("name", "label", "value", "city", "description", "title"):
            if value.get(key) not in (None, ""):
                return _text(value[key])
        return " ".join(_text(item) for item in value.values() if item not in (None, ""))
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_text(item) for item in value if item not in (None, ""))
    return str(value or "").strip()


def _records(value):
    """Yield nested dictionaries; the site has changed its JSON envelope before."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _records(child)


def _native_id(value):
    text = _text(value)
    match = ID_RE.search(text)
    return match.group(0) if match else ""


def _is_brazil(record, raw_text=""):
    country = _text(_first(record, _COUNTRY_KEYS)).casefold()
    if not country:
        return True  # the requested page already applies country=Brazil
    if country in {"br", "brasil", "brazil", "brasil (br)"}:
        return True
    return bool(re.search(r"\b(?:br|brasil|brazil)\b", raw_text, re.I))


def _levels(record, title, description):
    values = _first(record, ("seniority", "level", "experience", "experienceLevel", "experience_level"))
    labels = [_text(item) for item in (values if isinstance(values, list) else [values]) if _text(item)]
    labels.extend(match.group(1) for match in LEVEL_RE.finditer(f"{title} {description}"))
    return list(dict.fromkeys(label.title() for label in labels if label))


def _categories(record):
    values = _first(record, ("area", "department", "category", "categories", "team", "businessUnit", "business_unit"))
    labels = [_text(item) for item in (values if isinstance(values, list) else [values]) if _text(item)]
    return list(dict.fromkeys(labels))


def _contract_types(record):
    values = _first(record, ("contractType", "contract_type", "employmentType", "employment_type", "hireType", "hire_type"))
    labels = [_text(item) for item in (values if isinstance(values, list) else [values]) if _text(item)]
    return list(dict.fromkeys(labels))


def _record_url(record, native_id):
    value = _first(record, _URL_KEYS)
    if value:
        url = urljoin(BASE_URL, _text(value))
        if "/positions" in url and "id=" in url:
            return url
    return f"{BASE_URL}/pt/positions?id={native_id}"


def _record_job(record):
    native_id = _native_id(_first(record, _ID_KEYS))
    title = _text(_first(record, _TITLE_KEYS))
    if not native_id or not title or len(title) > 240:
        return None
    location = _text(_first(record, _LOCATION_KEYS))
    country = _text(_first(record, _COUNTRY_KEYS))
    description = strip_html(_text(_first(record, ("description", "jobDescription", "job_description", "summary"))))
    raw = " ".join((location, country, _text(_first(record, ("workModel", "work_model", "remote", "workplaceType", "workplace_type")))))
    if not _is_brazil(record, raw):
        return None
    remote_flag = _first(record, ("remote", "isRemote", "is_remote"))
    remote_flag = remote_flag if isinstance(remote_flag, bool) else None
    country_code = "BR" if not country or country.casefold() in {"br", "brasil", "brazil"} else country
    skills_value = _first(record, ("skills", "keywords", "tags"))
    skill_values = skills_value if isinstance(skills_value, list) else [skills_value]
    skills = []
    for item in skill_values:
        text = _text(item)
        if not text:
            continue
        skills.extend(part.strip() for part in re.split(r"[,;|]", text) if part.strip())
    return job(
        "mercadolivre",
        native_id,
        title=title,
        company="Mercado Livre",
        url=_record_url(record, native_id),
        work_model=work_model_label(remote_flag=remote_flag, raw=raw),
        city=location,
        country=country_code,
        market="BR",
        published_date=iso_date(_first(record, _DATE_KEYS)),
        description=description,
        skills=list(dict.fromkeys(skills)),
        levels=_levels(record, title, description),
        categories=_categories(record) or ["Mercado Livre"],
        contract_types=_contract_types(record),
    )


def _anchor_job(href, label):
    parsed = urlparse(urljoin(BASE_URL, html.unescape(href).strip()))
    native_id = _native_id((parse_qs(parsed.query).get("id") or [""])[0])
    title = strip_html(html.unescape(label))
    if not native_id or not title:
        return None
    return job(
        "mercadolivre",
        native_id,
        title=title,
        company="Mercado Livre",
        url=parsed.geturl(),
        country="BR",
        market="BR",
        categories=["Mercado Livre"],
    )


def _parse_markup(markup):
    rows, seen = [], set()
    for raw in JSON_SCRIPT_RE.findall(markup or ""):
        try:
            payload = json.loads(html.unescape(raw))
        except (TypeError, ValueError):
            continue
        for record in _records(payload):
            row = _record_job(record)
            if row and row["native_id"] not in seen:
                seen.add(row["native_id"])
                rows.append(row)
    for href, label in ANCHOR_RE.findall(markup or ""):
        row = _anchor_job(href, label)
        if row and row["native_id"] not in seen:
            seen.add(row["native_id"])
            rows.append(row)
    return rows


def _parse_rendered_links(links):
    rows, seen = [], set()
    for href, label in links:
        row = _anchor_job(href, label)
        if row and row["native_id"] not in seen:
            seen.add(row["native_id"])
            rows.append(row)
    return rows


def fetch():
    """Collect Brazil vacancies without touching the public catalogue."""
    errors = []
    try:
        markup = get_text(
            POSITIONS,
            headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "User-Agent": "Mozilla/5.0 (compatible; todas-as-vagas/1.0)",
            },
            timeout=45,
            retries=2,
        )
        rows = _parse_markup(markup)
        if rows:
            return rows
        errors.append("documento público sem registros reconhecíveis")
    except Exception as error:
        errors.append(str(error))

    try:
        rows = _parse_rendered_links(
            rendered_links(
                POSITIONS,
                r"/(?:pt|en|es)/positions\?[^#]*\bid=\d+",
                timeout=60,
            )
        )
        if rows:
            return rows
        errors.append("renderização sem links públicos de vagas")
    except Exception as error:
        errors.append(str(error))

    detail = "; ".join(dict.fromkeys(error for error in errors if error))
    raise RuntimeError(f"Mercado Livre não expôs vagas públicas: {detail[:300]}")
