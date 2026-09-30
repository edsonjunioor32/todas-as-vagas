# -*- coding: utf-8 -*-
"""Public vacancy boards hosted by the Compleo ATS."""
import concurrent.futures
import html
import json
import re
import threading
from functools import partial

from urllib.parse import urlsplit

from ._common import is_brazil_location, iso_date, job, strip_html, work_model_label
from ._http import get_text


SITEMAP_URL = "https://jobs.compleo.app/sitemap.xml"
_SITEMAP_URLS = None
_SITEMAP_LOCK = threading.Lock()
BRAZIL_WORDS = re.compile(
    r"brasil|brazil|s[aã]o paulo|rio de janeiro|campinas|curitiba|recife|"
    r"bras[ií]lia|belo horizonte|salvador|fortaleza|porto alegre|paran[aá]|"
    r"santa catarina|minas gerais|bahia|pernambuco|cear[aá]",
    re.I,
)


def _next_data(page):
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page,
        re.I | re.S,
    )
    if not match:
        raise RuntimeError("Compleo job page has no __NEXT_DATA__ payload")
    return json.loads(html.unescape(match.group(1)))


def _sitemap_urls():
    """Load the large shared Compleo sitemap at most once per process/run."""
    global _SITEMAP_URLS
    if _SITEMAP_URLS is not None:
        return _SITEMAP_URLS
    with _SITEMAP_LOCK:
        if _SITEMAP_URLS is None:
            sitemap = html.unescape(get_text(SITEMAP_URL, timeout=45, retries=2))
            urls = tuple(sorted(set(
                html.unescape(value)
                for value in re.findall(r"<loc>([^<]+)</loc>", sitemap, re.I)
            )))
            if not urls:
                raise RuntimeError("Compleo sitemap returned no URLs")
            _SITEMAP_URLS = urls
    return _SITEMAP_URLS


def _compleo_row(source, url, company):
    data = _next_data(get_text(url, timeout=45, retries=2))
    value = data.get("props", {}).get("pageProps", {}).get("jobViewData") or {}
    if not value or not value.get("isAvailableOnCareersSite", True):
        return None

    location = value.get("location") or {}
    city = location.get("city") or {}
    state = location.get("provinceOrState") or {}
    country = location.get("country") or {}
    model = value.get("workingModel") or {}
    contract = value.get("employmentType") or {}
    category = value.get("category") or {}
    level = value.get("experienceLevel") or {}
    tags = value.get("tags") or []
    if isinstance(tags, dict):
        tags = list(tags.values())

    country_text = str(country.get("label") or country.get("value") or "").strip()
    location_text = " ".join(str(part or "").strip() for part in (
        city.get("label"), city.get("value"), state.get("label"),
        state.get("value"), country_text,
    ))
    if country_text and not (
        is_brazil_location(location_text) or BRAZIL_WORDS.search(location_text)
    ):
        return None

    native_id = str(value.get("pk") or url.rstrip("/").split("/")[-1])
    native_id = native_id.replace("JOB:", "")
    title = str(value.get("title") or "").strip()
    if not native_id or not title:
        return None
    description = " ".join(str(value.get(field) or "") for field in (
        "description", "responsibilities", "requirements",
    ))
    return job(
        source, native_id, title=title, company=company, url=url,
        work_model=work_model_label(raw=model.get("label") or model.get("label-pt-BR")),
        city=str(city.get("label") or city.get("value") or "Brasil").strip(),
        state=str(city.get("uf") or state.get("value") or "").strip(),
        country="BR", market="BR", published_date=iso_date(value.get("openingDate")),
        expires_date=iso_date(value.get("hiringEndDate")),
        description=strip_html(description),
        categories=[str(category.get("label") or "").strip()] if category.get("label") else [],
        levels=[str(level.get("label") or "").strip()] if level.get("label") else [],
        skills=[str(tag).strip() for tag in tags if str(tag).strip()],
        contract_types=[str(contract.get("label") or "").strip()] if contract.get("label") else [],
    )


def fetch_board(source, board, company):
    """Collect all active Brazil vacancies for one Compleo company board."""
    urls = []
    for url in _sitemap_urls():
        parsed = urlsplit(url)
        parts = [part.casefold() for part in parsed.path.strip("/").split("/")]
        if (
            parsed.netloc.casefold() == "jobs.compleo.app"
            and len(parts) == 3
            and parts[0] == board.casefold()
            and parts[1] == "jobdetail"
        ):
            urls.append(url)

    rows = []
    failures = []

    def fetch(url):
        try:
            return _compleo_row(source, url, company)
        except Exception as error:
            failures.append((url, error))
            print(f"    [compleo:{board}] {url}: {str(error)[:120]}")
            return None

    if urls:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(4, len(urls))
        ) as executor:
            rows = [row for row in executor.map(fetch, urls) if row]

    # A legitimate board with no public postings is an empty feed. Any detail
    # outage marks this source unhealthy while carrying successful rows so the
    # catalog can publish partial work and preserve its last healthy snapshot.
    if failures:
        error = RuntimeError(
            f"Compleo/{board}: {len(failures)} of {len(urls)} detail requests failed"
        )
        error.rows = rows
        raise error
    return rows


COMPANIES = (
    ("mootit", "Moot It Consulting"),
    ("slmandic", "São Leopoldo Mandic"),
    ("frigelar", "Frigelar"),
    ("grupokyly", "Grupo Kyly"),
    ("ctdoagro", "Consultoria Talentos do Agro"),
    ("grupolagoa", "Grupo Lagoa"),
    ("lncarreira", "L&N Carreira"),
    ("rhvital", "RH Vital"),
    ("grupobembarato", "Grupo Bem Barato"),
    ("faisrh", "Fais RH"),
    ("excelenciarh", "Excelência RH"),
    ("grandy", "Grandy"),
    ("agiliza", "Agiliza Soluções Empresariais"),
    ("slmandic.slmandichospitais", "São Leopoldo Mandic Hospitais"),
    ("harpiait", "Harpia IT"),
)


def fetch_grandy():
    """Combine Grandy's branded sub-boards and collapse repeated vacancy IDs."""
    rows = []
    failures = []
    seen = set()
    for board in ("grandy", "grandy.supermercadogule", "grandy.sanrafael"):
        try:
            board_rows = fetch_board("grandy", board, "Grandy")
        except Exception as error:
            failures.append(str(error))
            board_rows = getattr(error, "rows", []) or []
        for row in board_rows:
            key = row.get("native_id") or row.get("url")
            if key and key not in seen:
                seen.add(key)
                rows.append(row)
    if failures:
        error = RuntimeError("Compleo/Grandy sub-board failure: " + "; ".join(failures)[:140])
        error.rows = rows
        raise error
    return rows


TARGETS = tuple(
    (board, partial(fetch_board, board, board, company))
    for board, company in COMPANIES if board != "grandy"
) + (("grandy", fetch_grandy),)
