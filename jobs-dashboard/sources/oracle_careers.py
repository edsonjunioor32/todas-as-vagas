# -*- coding: utf-8 -*-
"""Named company career sites hosted on Oracle Recruiting Cloud.

Oracle Candidate Experience exposes the active requisitions of a public career
site through the ``recruitingCEJobRequisitions`` resource. Each company remains
a named source in the dashboard so visitors can filter it directly.
"""
import calendar
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json

PAGE_SIZE = 200
EXPAND = (
    "requisitionList.workLocation,"
    "requisitionList.otherWorkLocations,"
    "requisitionList.secondaryLocations"
)

SITES = {
    "picpay": {
        "host": "https://epdm.fa.la1.oraclecloud.com",
        "site_number": "CX_3001",
        "site_slug": "PicPay",
        "locale": "pt-BR",
        "company": "PicPay",
    },
    "bancooriginal": {
        "host": "https://epdm.fa.la1.oraclecloud.com",
        "site_number": "CX_4001",
        "site_slug": "BancoOriginal",
        "locale": "pt-BR",
        "company": "Banco Original",
    },
    "braskem": {
        "host": "https://epiw.fa.la1.oraclecloud.com",
        "site_number": "CX_1",
        "site_slug": "CX_1",
        "locale": "pt-BR",
        "company": "Braskem",
    },
    "gmfinancial": {
        "host": "https://fa-exvu-saasfaprod1.fa.ocs.oraclecloud.com",
        "site_number": "CX_1003",
        "site_slug": "CX_1003",
        "locale": "pt-BR",
        "company": "GM Financial",
    },
    "dell": {
        "host": "https://iawmqy.fa.ocs.oraclecloud.com",
        "site_number": "CX_1001",
        "site_slug": "careers",
        "locale": "pt-BR",
        "company": "Dell Technologies",
    },
    "arcelormittal": {
        "host": "https://emfg.fa.em4.oraclecloud.com",
        "site_number": "CX_4001",
        "site_slug": "CX_4001",
        "locale": "pt-BR",
        "company": "ArcelorMittal",
    },
    "grupomateus": {
        "host": "https://fa-exvn-saasfaprod1.fa.ocs.oraclecloud.com",
        "site_number": "CX_1",
        "site_slug": "CX_1",
        "locale": "pt-BR",
        "company": "Grupo Mateus",
    },
    "autozone": {
        "host": "https://egud.fa.us2.oraclecloud.com",
        "site_number": "CX_1",
        "site_slug": "CX_1",
        "locale": "en",
        "company": "AutoZone",
    },
    "nov": {
        "host": "https://egay.fa.us6.oraclecloud.com",
        "site_number": "CX_4001",
        "site_slug": "CX_4001",
        "locale": "en",
        "company": "NOV",
    },
    "arcorbrasil": {
        "host": "https://emqm.fa.us6.oraclecloud.com",
        "site_number": "CX_1001",
        "site_slug": "NossasVagas",
        "locale": "pt-BR",
        "company": "Arcor Brasil",
    },
}

PCD_PATTERN = re.compile(
    r"\bpcd\b|pessoa(?:s)?\s+com\s+defici|vaga\s+(?:afirmativa|exclusiva).{0,40}defici",
    re.I,
)

LOCATION_REPLACEMENTS = {
    "Sao Paulo": "São Paulo",
    "Vitoria": "Vitória",
    "Brasilia": "Brasília",
    "Goiania": "Goiânia",
}

LOCAL_TIMEZONE = ZoneInfo("America/Fortaleza")


def _publication_cutoff():
    """Return the configured calendar-month cutoff in Fortaleza time."""
    try:
        months = max(0, int(os.environ.get("JOBS_MAX_AGE_MONTHS", "2")))
    except ValueError:
        months = 2
    today = datetime.now(LOCAL_TIMEZONE).date()
    year, month = today.year, today.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = min(today.day, calendar.monthrange(year, month)[1])
    return today.replace(year=year, month=month, day=day).isoformat()


def _title_case(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if text and text == text.upper():
        text = text.title()
    for plain, accented in LOCATION_REPLACEMENTS.items():
        if text.casefold() == plain.casefold():
            return accented
    return text


def _clean_location(value):
    """Convert ``SAO PAULO, SP, Brasil`` to ``São Paulo, SP``."""
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    if parts and parts[-1].casefold() in {"br", "brasil", "brazil"}:
        parts.pop()
    if not parts:
        return ""
    city = _title_case(parts[0])
    state = parts[1].upper() if len(parts) > 1 and len(parts[1]) <= 3 else ""
    return f"{city}, {state}" if state else city


def _child_items(value):
    """Accept both legacy child arrays and REST Framework v4 wrappers."""
    if isinstance(value, dict):
        return value.get("items") or []
    return value if isinstance(value, list) else []


def _location_values(item):
    values = []
    primary = _clean_location(item.get("PrimaryLocation"))
    if primary:
        values.append(primary)
    for field in ("secondaryLocations", "otherWorkLocations"):
        for entry in _child_items(item.get(field)):
            if not isinstance(entry, dict):
                continue
            raw = (
                entry.get("LocationName")
                or entry.get("PrimaryLocation")
                or entry.get("Name")
                or ""
            )
            cleaned = _clean_location(raw)
            if cleaned:
                values.append(cleaned)
    return list(dict.fromkeys(values))


def _api_url(config, offset):
    finder = (
        "findReqs;"
        f"siteNumber={config['site_number']},"
        f"limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC"
    )
    query = urlencode({"finder": finder, "expand": EXPAND, "onlyData": "true"})
    return (
        f"{config['host']}/hcmRestApi/resources/latest/"
        f"recruitingCEJobRequisitions?{query}"
    )


def _normalize(source, config, item):
    title = str(item.get("Title") or "").strip()
    locations = _location_values(item)
    raw_workplace = " ".join(
        str(value or "")
        for value in (title, item.get("WorkplaceType"), item.get("PrimaryLocation"))
    )
    description = strip_html(
        " ".join(
            str(value or "")
            for value in (
                item.get("ShortDescriptionStr"),
                item.get("ExternalResponsibilitiesStr"),
                item.get("ExternalQualificationsStr"),
            )
        )
    )
    categories = [
        str(item.get(field) or "").strip()
        for field in ("JobFunction", "JobFamily", "Department", "Organization")
        if str(item.get(field) or "").strip()
    ]
    contracts = [
        str(item.get(field) or "").strip()
        for field in ("ContractType", "JobType", "JobSchedule")
        if str(item.get(field) or "").strip()
    ]
    native_id = item.get("Id")
    url = (
        f"{config['host']}/hcmUI/CandidateExperience/{config['locale']}/"
        f"sites/{config['site_slug']}/job/{native_id}"
    )
    country = str(item.get("PrimaryLocationCountry") or "").upper()

    return job(
        source,
        native_id,
        title=title,
        company=config["company"],
        url=url,
        work_model=work_model_label(raw=raw_workplace),
        city=" · ".join(locations),
        country=country,
        market="BR" if country == "BR" else "",
        published_date=iso_date(item.get("PostedDate")),
        expires_date=iso_date(item.get("PostingEndDate")),
        description=description,
        categories=list(dict.fromkeys(categories)),
        contract_types=list(dict.fromkeys(contracts)),
        pcd=bool(PCD_PATTERN.search(f"{title} {description[:700]}")),
    )


def _fetch_page(config, offset):
    payload = get_json(
        _api_url(config, offset),
        headers={"REST-Framework-Version": "4"},
        timeout=45,
        retries=3,
    )
    roots = payload.get("items") or []
    if not roots:
        return [], 0
    root = roots[0]
    return _child_items(root.get("requisitionList")), int(root.get("TotalJobsCount") or 0)


def _keep_recent(page, cutoff, collected):
    dated = [iso_date(item.get("PostedDate")) for item in page]
    collected.extend(
        item for item, published in zip(page, dated)
        if not published or published >= cutoff
    )
    # Oracle returns POSTING_DATES_DESC. As soon as a complete page crosses
    # the cutoff, every following page is older and can be skipped.
    return bool(dated) and all(dated) and any(published < cutoff for published in dated)


def _fetch(source):
    config = SITES[source]
    collected = []
    cutoff = _publication_cutoff()
    try:
        workers = min(6, max(1, int(os.environ.get("ORACLE_WORKERS", "4"))))
    except ValueError:
        workers = 4

    first_page, total = _fetch_page(config, 0)
    if not first_page:
        return []
    if _keep_recent(first_page, cutoff, collected) or len(first_page) < PAGE_SIZE:
        total = len(first_page)

    next_offset = PAGE_SIZE
    stop = next_offset >= total
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while not stop and next_offset < total:
            offsets = list(
                range(next_offset, min(total, next_offset + PAGE_SIZE * workers), PAGE_SIZE)
            )
            pages = list(executor.map(lambda offset: _fetch_page(config, offset)[0], offsets))
            for page in pages:
                if not page or _keep_recent(page, cutoff, collected) or len(page) < PAGE_SIZE:
                    stop = True
                    break
            next_offset += PAGE_SIZE * len(offsets)

    unique = {}
    for item in collected:
        key = str(item.get("Id") or "")
        if key:
            unique[key] = item
    normalized = [_normalize(source, config, item) for item in unique.values()]
    if source == "autozone":
        # AutoZone shares one global Oracle board. The dashboard is focused on
        # Brazil, so never publish jobs from the US, Mexico, India, or entries
        # whose country cannot be confirmed by Oracle.
        normalized = [row for row in normalized if row.get("country") == "BR"]
    return normalized


def fetch_picpay():
    return _fetch("picpay")


def fetch_bancooriginal():
    return _fetch("bancooriginal")


def fetch_braskem():
    return _fetch("braskem")


def fetch_gmfinancial():
    return _fetch("gmfinancial")


def fetch_dell():
    return _fetch("dell")


def fetch_arcelormittal():
    return _fetch("arcelormittal")


def fetch_grupomateus():
    return _fetch("grupomateus")


def fetch_autozone():
    return _fetch("autozone")


def fetch_nov():
    return _fetch("nov")


def fetch_arcorbrasil():
    return _fetch("arcorbrasil")
