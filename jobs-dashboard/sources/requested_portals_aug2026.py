# -*- coding: utf-8 -*-
"""Brazilian vacancies from the portals requested on 2026-08-17."""
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_text


NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.I | re.S
)
COMPLETEO_SITEMAP = "https://jobs.compleo.app/sitemap.xml"
COMPLETEO_PREFIX = "https://jobs.compleo.app/providerit/jobdetail/"
FISERV_SEARCH = "https://careers.fiserv.com/us/en/search-results?from={offset}&s=1"
PANDAPE = "https://metalfriosolutions.pandape.infojobs.com.br/"
REVOLUT = "https://www.revolut.com/careers/"
REVOLUT_READER = "https://r.jina.ai/https://www.revolut.com/careers/"
REVOLUT_SEED = Path(__file__).resolve().parent.parent / "data" / "revolut_br_seed.json"
TAGGUI = "https://rs.tagguirh.com.br/grupoinlog"
NESTLE_SEARCH = (
    "https://jobdetails.nestle.com/search/?q=&sortColumn=referencedate&"
    "sortDirection=desc&optionsFacetsDD_country=BR&startrow={offset}"
)


def _next_data(page):
    match = NEXT_DATA_RE.search(page)
    if not match:
        raise RuntimeError("page without __NEXT_DATA__")
    return json.loads(html.unescape(match.group(1)))


def _parallel(urls, parser, workers=10):
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(parser, url): url for url in urls}
        for future in as_completed(futures):
            rows.append(future.result())
    return rows


def _compleo_detail(url):
    data = _next_data(get_text(url, timeout=35, retries=2))
    row = data.get("props", {}).get("pageProps", {}).get("jobViewData") or {}
    if not row.get("isAvailableOnCareersSite", True):
        return None
    location = row.get("location") or {}
    city_data = location.get("city") or {}
    state_data = location.get("provinceOrState") or {}
    country_data = location.get("country") or {}
    model = row.get("workingModel") or {}
    contract = row.get("employmentType") or {}
    category = row.get("category") or {}
    level = row.get("experienceLevel") or {}
    tags = row.get("tags") or []
    if isinstance(tags, dict):
        tags = list(tags.values())
    description = " ".join(
        str(row.get(field) or "")
        for field in ("description", "responsibilities", "requirements")
    )
    native_id = str(row.get("pk") or url.rstrip("/").split("/")[-1]).replace("JOB:", "")
    return job(
        "providerit", native_id, title=row.get("title"), company="Provider IT", url=url,
        work_model=work_model_label(raw=model.get("label") or model.get("label-pt-BR")),
        city=city_data.get("label") or "Brasil", state=city_data.get("uf") or state_data.get("value") or "",
        country="BR", market="BR", published_date=iso_date(row.get("openingDate")),
        expires_date=iso_date(row.get("hiringEndDate")), description=strip_html(description),
        categories=[category.get("label")] if category.get("label") else [],
        levels=[level.get("label")] if level.get("label") else [],
        skills=[str(value) for value in tags if value],
        contract_types=[contract.get("label")] if contract.get("label") else [],
    )


def fetch_providerit():
    sitemap = html.unescape(get_text(COMPLETEO_SITEMAP, timeout=45, retries=2))
    urls = sorted(set(re.findall(r"<loc>(%s[^<]+)</loc>" % re.escape(COMPLETEO_PREFIX), sitemap)))
    if not urls:
        raise RuntimeError("Provider IT sitemap returned no active vacancies")
    return [row for row in _parallel(urls, _compleo_detail, workers=8) if row]


def _phenom_payload(page):
    marker = "phApp.ddo = "
    start = page.find(marker)
    if start < 0:
        raise RuntimeError("Fiserv page without Phenom payload")
    payload, _ = json.JSONDecoder().raw_decode(page[start + len(marker):])
    return payload.get("eagerLoadRefineSearch") or {}


def _fiserv_page(offset):
    return _phenom_payload(get_text(FISERV_SEARCH.format(offset=offset), timeout=35, retries=2))


def fetch_fiserv():
    first = _fiserv_page(0)
    total = int(first.get("totalHits") or 0)
    pages = [first]
    if total > 10:
        # Phenom's relevance order can move while the catalog is paged.  A
        # five-row overlap prevents a vacancy from falling between two pages.
        urls = [FISERV_SEARCH.format(offset=offset) for offset in range(5, total, 5)]
        pages.extend(_parallel(urls, lambda url: _phenom_payload(get_text(url, timeout=35, retries=2)), workers=12))
    rows, seen = [], set()
    for page in pages:
        for value in (page.get("data") or {}).get("jobs") or []:
            locations = [value.get("location"), value.get("cityStateCountry")]
            locations.extend(value.get("multi_location") or [])
            locations.extend(
                item.get("location") for item in (value.get("multi_location_array") or [])
                if isinstance(item, dict)
            )
            location_text = " | ".join(str(part) for part in locations if part)
            if value.get("country") != "Brazil" and not re.search(r"\b(?:Brazil|S[aã]o Paulo)\b", location_text, re.I):
                continue
            native_id = str(value.get("jobId") or value.get("reqId") or value.get("jobSeqNo") or "")
            if not native_id or native_id in seen:
                continue
            seen.add(native_id)
            remote = bool(re.search(r"\bremote\b", location_text, re.I))
            title = value.get("title") or ""
            url = urljoin("https://careers.fiserv.com", value.get("jobUrl") or "")
            if not value.get("jobUrl"):
                slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                url = f"https://careers.fiserv.com/us/en/job/{native_id}/{slug}"
            rows.append(job(
                "fiserv", native_id, title=title, company="Fiserv", url=url,
                work_model="remote" if remote else "on-site",
                city="Brasil" if remote else (value.get("city") or "São Paulo"),
                state="" if remote else (value.get("state") or "SP"), country="BR", market="BR",
                published_date=iso_date(value.get("postedDate")),
                description=strip_html(value.get("descriptionTeaser") or ""),
                categories=value.get("multi_category") or ([value.get("category")] if value.get("category") else []),
                contract_types=[value.get("type")] if value.get("type") else [],
            ))
    if not rows:
        raise RuntimeError("Fiserv catalog returned no Brazilian vacancies")
    return rows


CARD_RE = re.compile(
    r'<a[^>]+class="card card-vacancy[^\"]*"[^>]+href="(/Detail/(\d+))"[^>]*>(.*?)</a>',
    re.I | re.S,
)


def _card_value(block, icon):
    match = re.search(rf"{icon}.*?</div>\s*([^<]+)", block, re.I | re.S)
    return strip_html(html.unescape(match.group(1))) if match else ""


def _short_pt_date(value):
    months = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
              "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}
    match = re.search(r"(\d{1,2})\s+([a-zç]{3})", str(value or "").lower())
    if not match or match.group(2) not in months:
        return ""
    now = datetime.now(timezone.utc)
    month = months[match.group(2)]
    year = now.year - (1 if month > now.month else 0)
    return f"{year:04d}-{month:02d}-{int(match.group(1)):02d}"


def fetch_metalfrio():
    page = get_text(PANDAPE, timeout=35, retries=2)
    rows = []
    for path, native_id, block in CARD_RE.findall(page):
        title_match = re.search(r"<h3[^>]+title=\"([^\"]+)\"", block, re.I)
        if not title_match:
            continue
        location = _card_value(block, "icon-location-pin-1")
        model = _card_value(block, "icon-buildings")
        contract = _card_value(block, "icon-sheet")
        date_match = re.search(r"vacancy-date[^>]*>([^<]+)", block, re.I)
        parts = [part.strip() for part in re.split(r"\s+-\s+", location, maxsplit=1)]
        rows.append(job(
            "metalfrio", native_id, title=html.unescape(title_match.group(1)),
            company="Metalfrio Solutions", url=urljoin(PANDAPE, path),
            work_model=work_model_label(raw=model) or "on-site",
            city=parts[0] if parts else "Brasil", state=parts[1] if len(parts) > 1 else "",
            country="BR", market="BR",
            published_date=_short_pt_date(date_match.group(1) if date_match else ""),
            contract_types=[contract] if contract else [], categories=["Metalfrio"],
        ))
    if not rows:
        raise RuntimeError("Pandapé/Metalfrio returned no vacancies")
    return rows


def _revolut_positions():
    try:
        page = get_text(REVOLUT, timeout=35, retries=1)
        if "__NEXT_DATA__" not in page:
            page = get_text(
                REVOLUT_READER,
                headers={"X-Return-Format": "html"},
                timeout=60,
                retries=2,
            )
        positions = (
            _next_data(page).get("props", {}).get("pageProps", {}).get("positions") or []
        )
        if positions:
            return positions
    except Exception:
        # Revolut and its rendering proxy can reject GitHub-hosted runners.
        # Keep the last verified Brazilian catalog as a resilient fallback;
        # every run still attempts the live source before using this snapshot.
        pass
    return json.loads(REVOLUT_SEED.read_text(encoding="utf-8"))


def fetch_revolut():
    positions = _revolut_positions()
    rows = []
    for value in positions:
        brazil = [item for item in value.get("locations") or [] if item.get("country") == "Brazil"]
        if not brazil:
            continue
        remote = any(item.get("type") == "remote" for item in brazil)
        office = next((item.get("name") for item in brazil if item.get("type") == "office"), "")
        native_id = str(value.get("id") or "")
        slug = re.sub(r"[^a-z0-9]+", "-", str(value.get("text") or "").lower()).strip("-")
        rows.append(job(
            "revolut", native_id, title=value.get("text"), company="Revolut",
            url=f"https://www.revolut.com/careers/position/{slug}-{native_id}/",
            work_model="remote" if remote else "on-site",
            city="Brasil" if remote else (office or "São Paulo"),
            state="" if remote else "SP", country="BR", market="BR",
            description=strip_html(value.get("description") or ""),
            categories=[value.get("team")] if value.get("team") else [],
        ))
    if not rows:
        raise RuntimeError("Revolut catalog returned no Brazilian vacancies")
    return rows


def fetch_inlog():
    page = get_text(TAGGUI, timeout=35, retries=2)
    match = re.search(r'vagas\\":(\[.*?\]),\\"empresaNome', page, re.S)
    if not match:
        raise RuntimeError("Taggui page without vacancy payload")
    values = json.loads(match.group(1).replace('\\"', '"'))
    rows = []
    for value in values:
        model = value.get("modelo_trabalho") or value.get("localizacao") or ""
        remote = work_model_label(raw=model) == "remote"
        contract = value.get("tipo_contrato") or ""
        rows.append(job(
            "inlog", value.get("id"), title=value.get("Titulo_vaga"),
            company=value.get("empresa_nome") or "Inlog",
            url=f"https://rs.tagguirh.com.br/visualizar-vaga/grupoinlog/{value.get('id')}",
            work_model="remote" if remote else (work_model_label(raw=model) or "on-site"),
            city="Brasil" if remote else (value.get("localizacao") or "Brasil"),
            country="BR", market="BR", published_date=iso_date(value.get("created_at")),
            categories=[value.get("Departamento")] if value.get("Departamento") else [],
            contract_types=[contract] if contract else [],
        ))
    return rows


def _english_date(value):
    try:
        return datetime.strptime(strip_html(value), "%b %d, %Y").date().isoformat()
    except ValueError:
        return ""


def _nestle_page(offset):
    return get_text(NESTLE_SEARCH.format(offset=offset), timeout=35, retries=2)


def fetch_nestle():
    first = _nestle_page(0)
    total_match = re.search(r"Results\s*<b>\d+\s*[–-]\s*\d+</b>\s*of\s*<b>(\d+)</b>", first, re.I)
    total = int(total_match.group(1)) if total_match else 10
    pages = [first]
    if total > 10:
        urls = [NESTLE_SEARCH.format(offset=offset) for offset in range(10, total, 10)]
        pages.extend(_parallel(urls, lambda url: get_text(url, timeout=35, retries=2), workers=8))
    rows, seen = [], set()
    for page in pages:
        for block in re.findall(r'<tr class="data-row">(.*?)</tr>', page, re.I | re.S):
            title_match = re.search(r'<a href="([^"]+)" class="jobTitle-link">(.*?)</a>', block, re.I | re.S)
            if not title_match:
                continue
            native_match = re.search(r"/(\d+)/?$", html.unescape(title_match.group(1)))
            if not native_match or native_match.group(1) in seen:
                continue
            native_id = native_match.group(1)
            seen.add(native_id)
            location_match = re.search(r'<td class="colLocation[^>]*>(.*?)</td>', block, re.I | re.S)
            category_match = re.search(r'<td class="colFacility[^>]*>(.*?)</td>', block, re.I | re.S)
            date_match = re.search(r'<td class="colDate[^>]*>(.*?)</td>', block, re.I | re.S)
            title = strip_html(html.unescape(title_match.group(2)))
            location = strip_html(html.unescape(location_match.group(1))) if location_match else "Brasil"
            category = strip_html(html.unescape(category_match.group(1))) if category_match else ""
            city = location.split(",")[0].strip() or "Brasil"
            company = "Nespresso" if "nespresso" in title.lower() else ("Purina" if "purina" in title.lower() else "Nestlé")
            rows.append(job(
                "nestle", native_id, title=title, company=company,
                url=urljoin("https://jobdetails.nestle.com", html.unescape(title_match.group(1))),
                work_model=work_model_label(raw=title) or "on-site", city=city,
                country="BR", market="BR",
                published_date=_english_date(date_match.group(1) if date_match else ""),
                categories=[category] if category else [],
            ))
    if not rows:
        raise RuntimeError("Nestlé catalog returned no Brazilian vacancies")
    return rows
