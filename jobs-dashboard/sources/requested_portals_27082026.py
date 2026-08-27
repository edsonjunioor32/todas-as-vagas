# -*- coding: utf-8 -*-
"""Adaptadores para os portais solicitados em 27/08/2026.

As funções deste módulo são deliberadamente independentes do catálogo atual:
a validação pode consultar as fontes e a mesclagem posterior pode substituir
somente as linhas pertencentes a estas fontes.
"""
import html
import json
import re
import urllib.parse
from urllib.parse import urljoin

from ._common import is_brazil_location, iso_date, job, strip_html, work_model_label
from ._http import get_json, get_text, post_json


WORKDAY = {
    "avanade": {
        "host": "accenture.wd103.myworkdayjobs.com",
        "tenant": "accenture",
        "site": "AvanadeCareers",
        "company": "Avanade",
        "url": "https://accenture.wd103.myworkdayjobs.com/pt-BR/AvanadeCareers/",
    },
    "santander": {
        "host": "santander.wd3.myworkdayjobs.com",
        "tenant": "santander",
        "site": "SantanderCareers",
        "company": "Santander",
        "url": "https://santander.wd3.myworkdayjobs.com/pt-BR/SantanderCareers",
    },
    "iberdrola": {
        "host": "iberdrola.wd3.myworkdayjobs.com",
        "tenant": "iberdrola",
        "site": "Iberdrola",
        "company": "Iberdrola",
        "url": "https://iberdrola.wd3.myworkdayjobs.com/pt-BR/Iberdrola",
    },
    "iqvia": {
        "host": "iqvia.wd1.myworkdayjobs.com",
        "tenant": "iqvia",
        "site": "IQVIA",
        "company": "IQVIA",
        "url": "https://iqvia.wd1.myworkdayjobs.com/pt-BR/IQVIA",
    },
    "mdlz": {
        "host": "mdlz.wd3.myworkdayjobs.com",
        "tenant": "mdlz",
        "site": "External",
        "company": "Mondelēz International",
        "url": "https://mdlz.wd3.myworkdayjobs.com/pt-BR/External",
    },
}

WORKDAY_API = "https://{host}/wday/cxs/{tenant}/{site}/jobs"
BRAZIL_WORDS = re.compile(
    r"brasil|brazil|s[aã]o paulo|rio de janeiro|campinas|curitiba|recife|"
    r"bras[ií]lia|belo horizonte|salvador|fortaleza|porto alegre|paran[aá]|"
    r"santa catarina|minas gerais|bahia|pernambuco|cear[aá]",
    re.I,
)


NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def _next_data(page):
    match = NEXT_DATA_RE.search(page)
    if not match:
        raise RuntimeError("page without __NEXT_DATA__")
    return json.loads(html.unescape(match.group(1)))



def _workday_rows(name):
    config = WORKDAY[name]
    rows, seen = [], set()
    offset, limit = 0, 20
    while offset < 5000:
        payload = post_json(
            WORKDAY_API.format(**config),
            {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=60,
            retries=3,
        )
        postings = payload.get("jobPostings") or []
        if not postings:
            break
        for item in postings:
            title = str(item.get("title") or "").strip()
            location = str(item.get("locationsText") or item.get("location") or "").strip()
            external = str(item.get("externalPath") or "").strip()
            native_id = str(item.get("bulletFields", [None])[0] or item.get("jobReqId") or external).strip()
            if not title or not external or not native_id or native_id in seen:
                continue
            if not BRAZIL_WORDS.search(location) and not is_brazil_location(location):
                continue
            seen.add(native_id)
            rows.append(job(
                name, native_id, title=title, company=config["company"],
                url=urljoin(config["url"], external.lstrip("/")),
                work_model=work_model_label(raw=f"{title} {location}"),
                city=location or "Brasil", country="BR", market="BR",
                published_date=iso_date(item.get("postedOn") or item.get("postedDate")),
                description=strip_html(item.get("description") or ""),
            ))
        total = int(payload.get("total") or 0)
        offset += limit
        if total and offset >= total:
            break
        if len(postings) < limit:
            break
    if not rows:
        raise RuntimeError(f"Workday/{name} returned no Brazilian vacancies")
    return rows


def fetch_avanade():
    return _workday_rows("avanade")


def fetch_santander():
    return _workday_rows("santander")


def fetch_iberdrola():
    return _workday_rows("iberdrola")


def fetch_iqvia():
    return _workday_rows("iqvia")


def fetch_mdlz():
    return _workday_rows("mdlz")


def _jsonld_rows(source, url, company):
    page = get_text(url, timeout=45, retries=3)
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page, re.I | re.S,
    )
    rows = []
    for block in blocks:
        try:
            payload = json.loads(html.unescape(block))
        except (TypeError, ValueError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            if not isinstance(value, dict) or value.get("@type") != "JobPosting":
                continue
            title = str(value.get("title") or "").strip()
            if not title:
                continue
            location_data = value.get("jobLocation") or {}
            if isinstance(location_data, list):
                location_data = location_data[0] if location_data else {}
            address = (location_data.get("address") or {}) if isinstance(location_data, dict) else {}
            location = ", ".join(
                str(address.get(key) or "").strip()
                for key in ("addressLocality", "addressRegion", "addressCountry")
                if str(address.get(key) or "").strip()
            )
            if location and not is_brazil_location(location) and not BRAZIL_WORDS.search(location):
                continue
            identifier = value.get("identifier") or {}
            native_id = str(identifier.get("value") if isinstance(identifier, dict) else identifier or title)
            rows.append(job(
                source, native_id, title=title, company=company,
                url=str(value.get("url") or url), work_model=work_model_label(raw=f"{title} {location}"),
                city=location or "Brasil", country="BR", market="BR",
                published_date=iso_date(value.get("datePosted")),
                description=strip_html(value.get("description") or ""),
                contract_types=[str(value.get("employmentType") or "").strip()] if value.get("employmentType") else [],
            ))
    return rows


def _anchor_rows(source, url, company, pattern=r'/(?:vaga|vagas|job|jobs)/[^"?#]+'):
    page = get_text(url, timeout=45, retries=3)
    rows, seen = [], set()
    for href, label in re.findall(
        rf'<a[^>]+href=["\']([^"\']*{pattern}[^"\']*)["\'][^>]*>(.*?)</a>',
        page, re.I | re.S,
    ):
        title = strip_html(html.unescape(label))
        absolute = urljoin(url, href)
        if len(title) < 4 or absolute in seen:
            continue
        seen.add(absolute)
        rows.append(job(
            source, absolute.rstrip("/").split("/")[-1], title=title, company=company,
            url=absolute, work_model=work_model_label(raw=title),
            city="Brasil", country="BR", market="BR",
        ))
    if not rows:
        rows = _jsonld_rows(source, url, company)
    if not rows:
        raise RuntimeError(f"{source} returned no public vacancies")
    return rows


def fetch_huntit():
    return _anchor_rows("huntit", "https://huntit.com.br/vagas/", "Hunt IT")


def fetch_forza():
    return _anchor_rows("forza", "https://forzabr.rhgestor.com.br/vagas", "Forza BR")


def fetch_saleco():
    return _anchor_rows("saleco", "https://www.saleco.com.br/jobs", "Saleco")


def fetch_elis():
    return _anchor_rows("elis", "https://elisbrasil.pandape.infojobs.com.br/", "Elis Brasil", r'/Detail/\d+')



def _abler_rows(source, subdomain, company):
    """Read a generic Abler public JSON:API career page."""
    encoded_subdomain = urllib.parse.quote(subdomain, safe="")
    api_root = (
        "https://hulk-smash.abler.com.br/api/company/v1/careers_pages/"
        f"{encoded_subdomain}/vacancies"
    )
    public_root = f"https://ats.abler.com.br/jobs/{encoded_subdomain}"
    rows, seen = [], set()
    for page in range(1, 21):
        query = urllib.parse.urlencode({
            "page": page,
            "per_page": 100,
            "include": "area_of_interests,level_of_interest",
        })
        payload = get_json(
            f"{api_root}?{query}",
            headers={"Origin": "https://ats.abler.com.br", "Referer": public_root},
            timeout=60,
            retries=3,
        )
        values = payload.get("data") or []
        if not isinstance(values, list):
            raise RuntimeError(f"Abler/{subdomain} returned invalid data")
        included = {
            (str(item.get("type") or ""), str(item.get("id") or "")): item
            for item in (payload.get("included") or [])
            if isinstance(item, dict)
        }
        for item in values:
            attrs = item.get("attributes") or {}
            native_id = str(item.get("id") or "").strip()
            title = str(attrs.get("title_formatted") or attrs.get("title") or "").strip()
            country = str(attrs.get("country") or "").strip().casefold()
            if not native_id or not title or native_id in seen:
                continue
            if country and country not in {"br", "bra", "brasil", "brazil"}:
                continue
            seen.add(native_id)
            slug = str(attrs.get("slug") or "").strip()
            url = f"{public_root}?slug={slug}" if slug else f"{public_root}?id={native_id}"
            raw_model = " ".join(
                str(value or "").strip()
                for value in (attrs.get("work_type"), attrs.get("work_type_formatted"))
            )
            contract = str(attrs.get("contracting_regime") or "").strip()
            description = " ".join(
                str(attrs.get(field) or "")
                for field in (
                    "description", "role_description", "mandatory_requirements",
                    "desirable_requirements", "results_and_deliveries",
                )
            )
            rows.append(job(
                source, native_id, title=title, company=company, url=url,
                work_model=work_model_label(
                    remote_flag=attrs.get("available_for_homeoffice") is True,
                    raw=raw_model,
                ),
                city=str(attrs.get("city") or "Brasil").strip(),
                state=str(attrs.get("state") or "").strip(),
                country="BR", market="BR",
                published_date=iso_date(
                    attrs.get("republished_at") or attrs.get("published_at") or attrs.get("created_at")
                ),
                expires_date=iso_date(attrs.get("close_on")),
                description=strip_html(description),
                contract_types=[contract] if contract else [],
            ))
        meta = payload.get("meta") or {}
        last_page = int(meta.get("last") or page)
        if page >= last_page or not values:
            break
    if not rows:
        raise RuntimeError(f"Abler/{subdomain} returned no public vacancies")
    return rows


def _compleo_row(source, url, company):
    data = _next_data(get_text(url, timeout=45, retries=3))
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
    location_text = " ".join(
        str(part or "").strip()
        for part in (
            city.get("label"), city.get("value"), state.get("label"), state.get("value"),
            country_text,
        )
    )
    if country_text and not (is_brazil_location(location_text) or BRAZIL_WORDS.search(location_text)):
        return None
    native_id = str(value.get("pk") or url.rstrip("/").split("/")[-1]).replace("JOB:", "")
    title = str(value.get("title") or "").strip()
    if not native_id or not title:
        return None
    description = " ".join(
        str(value.get(field) or "")
        for field in ("description", "responsibilities", "requirements")
    )
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


def _compleo_rows(source, board, company):
    sitemap = html.unescape(get_text("https://jobs.compleo.app/sitemap.xml", timeout=45, retries=3))
    urls = sorted({
        match for match in re.findall(r"<loc>([^<]+)</loc>", sitemap, re.I)
        if f"/{board.lower()}/" in match.lower()
    })
    if not urls:
        raise RuntimeError(f"Compleo/{board} sitemap returned no detail URLs")
    rows = []
    for url in urls:
        try:
            row = _compleo_row(source, url, company)
        except Exception as error:
            print(f"    [compleo:{board}] {url}: {str(error)[:80]}")
            continue
        if row:
            rows.append(row)
    if not rows:
        raise RuntimeError(f"Compleo/{board} returned no public vacancies")
    return rows


def fetch_abler_talentodovalesc():
    return _abler_rows("talentodovalesc", "talentodovalesc", "Talento do Vale SC")


def fetch_beq():
    return _compleo_rows("beq", "BEQ", "B&Q Energia")


def fetch_lever_board(source, board, company):
    payload = get_json(f"https://api.lever.co/v0/postings/{board}?mode=json", timeout=45, retries=3)
    rows = []
    for item in payload if isinstance(payload, list) else []:
        categories = item.get("categories") or {}
        location = str(categories.get("location") or "").strip()
        rows.append(job(
            source, item.get("id"), title=item.get("text"), company=company,
            url=item.get("hostedUrl") or item.get("applyUrl") or "",
            work_model=work_model_label(raw=f"{categories.get('commitment', '')} {location}"),
            city=location or "Brasil", country="BR", market="BR",
            published_date=iso_date(item.get("createdAt")),
            categories=[str(categories.get("department") or "").strip()] if categories.get("department") else [],
        ))
    if not rows:
        raise RuntimeError(f"Lever/{board} returned no vacancies")
    return rows


def fetch_flash():
    return fetch_lever_board("flash", "flashapp", "Flash")


def fetch_neon():
    return fetch_lever_board("neon", "neon", "Neon Pagamentos")


def fetch_zippi():
    return fetch_lever_board("zippi", "zippi", "Zippi")


def fetch_bv():
    return fetch_lever_board("bv", "bv", "Banco BV")


TARGETS = (
    ("avanade", fetch_avanade),
    ("huntit", fetch_huntit),
    ("talentodovalesc", fetch_abler_talentodovalesc),
    ("beq", fetch_beq),
    ("forza", fetch_forza),
    ("saleco", fetch_saleco),
    ("elis", fetch_elis),
    ("flash", fetch_flash),
    ("neon", fetch_neon),
    ("zippi", fetch_zippi),
    ("bv", fetch_bv),
    ("santander", fetch_santander),
    ("iberdrola", fetch_iberdrola),
    ("iqvia", fetch_iqvia),
    ("mdlz", fetch_mdlz),
)
