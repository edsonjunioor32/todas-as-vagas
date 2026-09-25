# -*- coding: utf-8 -*-
"""Public listings requested on 2026-09-16."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
import html
import json
import re
from urllib.parse import unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

from . import quickin
from ._common import is_brazil_location, iso_date, job, strip_html, work_model_label
from ._http import get_json, get_text
from .ats_boards import PER_COMPANY


JOBGETHER_API = (
    "https://api.lever.co/v0/postings/jobgether"
    "?mode=json&location=Brazil"
)
ASA_JOBS_URL = "https://elevoplus.app/p/asa/vagas"
ASA_ORIGIN = "https://elevoplus.app"
ASA_TIMEOUT_SECONDS = 35
BRAZIL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
ASA_DETAIL_LABELS = {
    "MODALIDADE",
    "LOCAL",
    "CONTRATO",
    "ÁREA",
    "INSCRIÇÕES ATÉ",
    "PUBLICADA EM",
}
ASA_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b")
ASA_LOCATION_RE = re.compile(r"^(.+?),\s*([A-Z]{2})$")


def fetch_blacklion():
    """Collect Black Lion's published openings from its Quickin company board."""
    return quickin.fetch_company(
        "blacklion",
        source="blacklion",
        company="Black Lion",
    )


def fetch_jobgether():
    """Collect public Jobgether postings whose Lever location is Brazil."""
    payload = get_json(JOBGETHER_API)
    if not isinstance(payload, list):
        raise RuntimeError("Jobgether Lever returned an unexpected payload")

    rows = []
    for posting in payload:
        categories = posting.get("categories") or {}
        location = str(categories.get("location") or "").strip()
        if not is_brazil_location(location):
            continue

        native_id = posting.get("id")
        title = str(posting.get("text") or "").strip()
        url = str(posting.get("hostedUrl") or "").strip()
        if not native_id or not title or not url:
            continue

        rows.append(job(
            "jobgether",
            native_id,
            title=title,
            company="Jobgether",
            url=url,
            work_model=work_model_label(
                raw=f"{categories.get('commitment') or ''} {location}"
            ),
            city=location,
            country="BR",
            market="BR",
            published_date=iso_date(posting.get("createdAt")),
            description=strip_html(
                posting.get("descriptionPlain")
                or posting.get("description")
                or ""
            ),
            categories=[
                str(categories.get("department") or categories.get("team") or "")
            ],
        ))
        if len(rows) >= PER_COMPANY:
            break

    if not rows:
        raise RuntimeError("Jobgether Lever returned no Brazilian vacancies")
    return rows


def _new_asa_driver():
    """Create ASA browser sessions through the shared bounded launcher."""
    from ._rendered import _webdriver

    return _webdriver()

def _wait_for_asa_element(driver, selector, timeout=ASA_TIMEOUT_SECONDS):
    """Wait for a rendered public listing/detail element, never an API response."""
    try:
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as error:
        raise RuntimeError("Selenium is required to collect ASA vacancies") from error

    WebDriverWait(driver, timeout).until(
        lambda current: bool(current.execute_script(
            "return Boolean(document.querySelector(arguments[0]))",
            selector,
        ))
    )


def _card_script():
    """Read visible vacancy-card links and their nearby rendered text."""
    return r"""
      const seen = new Set();
      const rows = [];
      const anchors = document.querySelectorAll(
        'a[href*="/p/asa/vagas/"]'
      );
      for (const anchor of anchors) {
        const url = new URL(anchor.href);
        const slug = url.pathname.replace(/\/$/, "").split("/").pop();
        const title = (anchor.innerText || "").trim();
        if (!slug || !title || seen.has(slug)) continue;
        seen.add(slug);

        let cardText = title;
        let node = anchor.parentElement;
        for (let depth = 0; node && depth < 8; depth++, node = node.parentElement) {
          const candidate = (node.innerText || "").trim();
          if (candidate.includes(title) && candidate.length <= 1200 &&
              (candidate.includes("·") || candidate.includes("Uberlândia"))) {
            cardText = candidate;
            break;
          }
        }
        rows.push({title, url: url.href, text: cardText});
      }
      return rows;
    """


def _detail_script():
    """Read the visible job metadata and description sections from a public page."""
    return r"""
      const sections = Array.from(
        document.querySelectorAll('[id^="verso-"]')
      ).filter(section => !section.id.endsWith("-title"));
      return {
        title: (document.querySelector("#notice-title")?.innerText || "").trim(),
        text: document.body?.innerText || "",
        description: sections
          .map(section => (section.innerText || "").trim())
          .filter(Boolean)
          .join("\n\n")
      };
    """


def _field_after_label(text, label):
    """Return the line following a visible detail-page label."""
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(text or "").splitlines()
    ]
    folded_label = label.casefold()
    for index, line in enumerate(lines):
        if line.casefold() != folded_label:
            continue
        for candidate in lines[index + 1:]:
            if not candidate:
                continue
            if candidate.upper() in ASA_DETAIL_LABELS:
                return ""
            return candidate
    return ""


def _asa_date(value, today, rollover=False):
    """Normalize Elevo+'s visible DD/MM deadline/publication date."""
    match = ASA_DATE_RE.search(str(value or ""))
    if not match:
        return ""
    day, month, year = match.groups()
    year = int(year) if year else today.year
    try:
        parsed = date(year, int(month), int(day))
    except ValueError:
        return ""
    if rollover and not match.group(3) and parsed < today - timedelta(days=30):
        try:
            parsed = parsed.replace(year=parsed.year + 1)
        except ValueError:
            return ""
    return parsed.isoformat()


def _asa_card_base(card):
    """Validate and normalize identity fields derived from the visible card."""
    title = str(card.get("title") or "").strip()
    url = str(card.get("url") or "").strip()
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or parsed_url.netloc.casefold() not in {
        "elevoplus.app",
        "www.elevoplus.app",
    }:
        return None
    prefix = "/p/asa/vagas/"
    if not parsed_url.path.startswith(prefix):
        return None
    native_id = parsed_url.path[len(prefix):].strip("/").split("/")[0]
    if not native_id or not title:
        return None
    return {
        "native_id": native_id,
        "title": title,
        "url": f"{ASA_ORIGIN}{parsed_url.path}",
        "card_text": str(card.get("text") or ""),
    }


def _normalize_asa_card(card, detail, today):
    """Map the card and public detail page into the shared vacancy contract."""
    base = _asa_card_base(card)
    if not base:
        return None

    detail = detail if isinstance(detail, dict) else {}
    detail_text = str(detail.get("text") or "")
    card_text = base["card_text"]
    title = str(detail.get("title") or base["title"]).strip()

    location = _field_after_label(detail_text, "LOCAL")
    location_match = ASA_LOCATION_RE.match(location)
    city = location_match.group(1).strip() if location_match else ""
    state = location_match.group(2) if location_match else ""

    modality = _field_after_label(detail_text, "MODALIDADE")
    contract = _field_after_label(detail_text, "CONTRATO")
    area = _field_after_label(detail_text, "ÁREA")
    published = _field_after_label(detail_text, "PUBLICADA EM")
    expires = _field_after_label(detail_text, "INSCRIÇÕES ATÉ")
    levels = [
        level for level in ("Júnior", "Pleno", "Sênior")
        if re.search(rf"\b{level}\b", f"{title} {card_text}", re.I)
    ]
    contract_types = [contract] if contract else []
    description = strip_html(str(detail.get("description") or ""), limit=6000)

    return job(
        "asa",
        base["native_id"],
        title=title,
        company="ASA Digital",
        url=base["url"],
        work_model=work_model_label(raw=modality or card_text),
        city=city,
        state=state,
        country="BR",
        market="BR",
        published_date=_asa_date(published, today),
        expires_date=_asa_date(expires, today, rollover=True),
        description=description,
        levels=levels,
        categories=[area] if area else [],
        contract_types=contract_types,
    )


def fetch_asa(today=None):
    """Collect ASA Digital's published vacancies from its public rendered portal.

    Selenium reads only rendered listing cards and each card's public detail
    page. It does not inspect or call private endpoints, log in, or submit
    candidate information.
    """
    today = today or datetime.now(BRAZIL_TIMEZONE).date()
    driver = _new_asa_driver()
    try:
        driver.set_page_load_timeout(ASA_TIMEOUT_SECONDS)
        driver.get(ASA_JOBS_URL)
        _wait_for_asa_element(driver, 'a[href*="/p/asa/vagas/"]')
        cards = driver.execute_script(_card_script())
        if not isinstance(cards, list) or not cards:
            raise RuntimeError("ASA public page returned no public vacancies")

        rows = []
        seen = set()
        for card in cards[:PER_COMPANY]:
            base = _asa_card_base(card if isinstance(card, dict) else {})
            if not base or base["native_id"] in seen:
                continue
            seen.add(base["native_id"])

            detail = {}
            try:
                driver.get(base["url"])
                _wait_for_asa_element(driver, "#notice-title")
                payload = driver.execute_script(_detail_script())
                if isinstance(payload, dict):
                    detail = payload
            except Exception:
                # A rendered card is still a valid listing if its details page
                # is briefly unavailable; preserve the vacancy and its URL.
                detail = {}

            row = _normalize_asa_card(card, detail, today)
            if row:
                rows.append(row)
    finally:
        from ._rendered import _close_driver
        _close_driver(driver)

    if not rows:
        raise RuntimeError("ASA public page returned no public vacancies")
    return rows


GFT_LISTING_URL = (
    "https://jobs.gft.com/go/brazil/4412501/"
    "?createNewAlert=false&q=&locationsearch=&optionsFacetsDD_country=BR"
    "&optionsFacetsDD_customfield1=&optionsFacetsDD_shifttype=&optionsFacetsDD_facility="
)
GFT_BASE_URL = "https://jobs.gft.com"
GFT_PAGE_SIZE = 25
GFT_MAX_PAGES = 20
GFT_DETAIL_WORKERS = 4
GFT_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bhref\s*=\s*["\']'
    r'(?P<href>(?:https://jobs\.gft\.com)?/job/[^"\']+)["\'][^>]*>'
    r'(?P<label>.*?)</a>',
    re.I | re.S,
)
GFT_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
    r'(?P<body>.*?)</script>',
    re.I | re.S,
)
GFT_TITLE_RE = re.compile(r"<h1[^>]*>(?P<title>.*?)</h1>", re.I | re.S)


def _gft_text(value):
    return re.sub(
        r"\s+",
        " ",
        strip_html(html.unescape(str(value or ""))).strip(),
    )


def _gft_jsonld(markup):
    """Return the JobPosting object from the public detail page JSON-LD."""
    for raw in GFT_JSONLD_RE.findall(markup or ""):
        try:
            payload = json.loads(html.unescape(raw).strip())
        except (TypeError, ValueError):
            continue

        if isinstance(payload, list):
            candidates = payload
        elif isinstance(payload, dict) and isinstance(payload.get("@graph"), list):
            candidates = payload["@graph"]
        else:
            candidates = [payload]

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            job_type = candidate.get("@type")
            if job_type == "JobPosting" or (
                isinstance(job_type, list) and "JobPosting" in job_type
            ):
                return candidate
    return {}


def _gft_job_url(href):
    url = urljoin(GFT_BASE_URL, html.unescape(str(href or "")).strip())
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != GFT_BASE_URL.removeprefix("https://").casefold()
        or not parsed.path.startswith("/job/")
    ):
        return ""
    return f"{GFT_BASE_URL}{parsed.path}"


def _gft_listing_rows(markup):
    """Extract unique public GFT detail links from one listing page."""
    rows = {}
    for match in GFT_ANCHOR_RE.finditer(markup or ""):
        url = _gft_job_url(match.group("href"))
        if not url:
            continue

        parsed = urlsplit(url)
        parts = [unquote(part).strip() for part in parsed.path.rstrip("/").split("/") if part]
        if len(parts) < 2 or parts[0].casefold() != "job":
            continue

        native_id = parts[-1]
        if not native_id:
            continue
        title = _gft_text(match.group("label"))
        if not title:
            title = re.sub(r"[-_]+", " ", parts[-2]).strip()
        rows.setdefault(
            native_id,
            {
                "native_id": native_id,
                "title": title,
                "url": url,
            },
        )
    return list(rows.values())


def _gft_location(posting):
    location = posting.get("jobLocation") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    if not isinstance(location, dict):
        return "", "", ""

    address = location.get("address") or {}
    if isinstance(address, list):
        address = address[0] if address else {}
    if not isinstance(address, dict):
        address = {}

    city = _gft_text(address.get("addressLocality") or location.get("addressLocality"))
    state = _gft_text(address.get("addressRegion") or location.get("addressRegion"))
    country = _gft_text(
        address.get("addressCountry")
        or location.get("addressCountry")
        or posting.get("jobLocationCountry")
    )
    return city, state, country


def _gft_employment_types(value):
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    return [
        _gft_text(item)
        for item in values
        if _gft_text(item)
    ]


def _gft_fallback(row):
    return job(
        "gft",
        row["native_id"],
        title=row["title"],
        company="GFT Technologies",
        url=row["url"],
        work_model=work_model_label(raw=row["title"]),
        country="BR",
        market="BR",
    )


def _gft_detail(row):
    """Read one public GFT detail page and normalize its JSON-LD."""
    markup = get_text(row["url"], timeout=45, retries=2)
    posting = _gft_jsonld(markup)
    title = _gft_text(posting.get("title"))
    if not title:
        title_match = GFT_TITLE_RE.search(markup or "")
        title = _gft_text(title_match.group("title")) if title_match else ""
    title = title or row["title"]

    description = strip_html(
        str(posting.get("description") or ""),
        limit=12000,
    )
    city, state, country = _gft_location(posting)
    raw_context = " ".join(
        [
            title,
            city,
            state,
            country,
            description[:4000],
            _gft_text(posting.get("employmentType")),
        ]
    )

    return job(
        "gft",
        row["native_id"],
        title=title,
        company="GFT Technologies",
        url=row["url"],
        work_model=work_model_label(raw=raw_context),
        city=city,
        state=state,
        country=country or "BR",
        market="BR",
        published_date=iso_date(posting.get("datePosted")),
        description=description,
        contract_types=_gft_employment_types(posting.get("employmentType")),
        categories=[_gft_text(posting.get("occupationalCategory"))]
        if _gft_text(posting.get("occupationalCategory"))
        else [],
    )


def fetch_gft():
    """Collect every public Brazilian GFT vacancy, preserving official links."""
    cards = {}
    for page in range(GFT_MAX_PAGES):
        offset = page * GFT_PAGE_SIZE
        url = GFT_LISTING_URL
        if offset:
            url = f"{GFT_LISTING_URL}&startrow={offset}"
        markup = get_text(url, timeout=45, retries=3)
        page_rows = _gft_listing_rows(markup)
        if not page_rows:
            break

        previous_count = len(cards)
        for row in page_rows:
            cards.setdefault(row["native_id"], row)
        if len(cards) == previous_count:
            break
        if len(page_rows) < GFT_PAGE_SIZE:
            break

    if not cards:
        raise RuntimeError("GFT public Brazil page returned no public vacancies")

    rows = []
    workers = min(GFT_DETAIL_WORKERS, len(cards))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_gft_detail, row): row
            for row in cards.values()
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                rows.append(future.result())
            except Exception:
                rows.append(_gft_fallback(row))

    if not rows:
        raise RuntimeError("GFT public Brazil page returned no public vacancies")
    return sorted(rows, key=lambda row: row["native_id"])
