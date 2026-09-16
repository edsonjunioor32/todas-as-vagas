# -*- coding: utf-8 -*-
"""Public listings requested on 2026-09-16."""
from datetime import date, datetime, timedelta
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import quickin
from ._common import is_brazil_location, iso_date, job, strip_html, work_model_label
from ._http import get_json
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
    """Create a headless Chrome session, using Selenium already in requirements."""
    try:
        from selenium import webdriver
    except ImportError as error:
        raise RuntimeError("Selenium is required to collect ASA vacancies") from error

    options = webdriver.ChromeOptions()
    for argument in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-notifications",
        "--window-size=1440,3000",
        "--lang=pt-BR",
    ):
        options.add_argument(argument)
    options.page_load_strategy = "eager"
    return webdriver.Chrome(options=options)


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


def _asa_date(value, today):
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
    if not match.group(3) and parsed < today - timedelta(days=30):
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
        expires_date=_asa_date(expires, today),
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
        driver.quit()

    if not rows:
        raise RuntimeError("ASA public page returned no public vacancies")
    return rows
