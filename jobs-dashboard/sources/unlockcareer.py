# -*- coding: utf-8 -*-
"""Public, browser-rendered job board for Mavila Consulting on UnlockCareer."""
from datetime import date, datetime
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ._common import is_brazil_location, job, strip_html, work_model_label
from .ats_boards import PER_COMPANY


MAVILA_JOBS_URL = "https://unlockcareer.ai/jobs/mavila-consulting"
MAVILA_ORIGIN = "https://unlockcareer.ai"
TIMEOUT_SECONDS = 35
BRAZIL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
POSTED_DATE_RE = re.compile(
    r"\bPosted\s+(\d{1,2})/(\d{1,2})/(\d{4})\b",
    re.I,
)
APPLY_PATH_PREFIX = "/jobs/mavila-consulting/apply/"


def _new_driver():
    """Use the shared bounded Chromium launcher for this rendered source."""
    from ._rendered import _webdriver

    return _webdriver()

def _wait_for_element(driver, selector, timeout=TIMEOUT_SECONDS):
    """Wait for a rendered public element; this adapter does not call site APIs."""
    try:
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as error:
        raise RuntimeError("Selenium is required to collect Mavila Consulting") from error

    WebDriverWait(driver, timeout).until(
        lambda current: bool(current.execute_script(
            "return Boolean(document.querySelector(arguments[0]))",
            selector,
        ))
    )


def _cards_script():
    """Extract visible public job cards and their apply links from rendered DOM."""
    return r"""
      const rows = [];
      const seen = new Set();
      const selector = 'a[href*="/jobs/mavila-consulting/apply/"]';
      for (const link of document.querySelectorAll(selector)) {
        const url = new URL(link.href);
        const id = url.pathname.replace(/\/$/, "").split("/").pop();
        if (!id || seen.has(id)) continue;
        seen.add(id);

        let card = null;
        let node = link;
        for (let depth = 0; node && depth < 12; depth++, node = node.parentElement) {
          const text = (node.innerText || "").trim();
          const applyLinks = node.querySelectorAll(selector);
          const heading = node.querySelector("h1, h2, h3, h4, h5, h6");
          if (applyLinks.length === 1 && heading && text.length > 80 &&
              text.length <= 12000) {
            card = node;
            break;
          }
        }
        const text = (card?.innerText || link.parentElement?.innerText || "").trim();
        const title = (card?.querySelector("h1, h2, h3, h4, h5, h6")?.innerText ||
                       link.innerText || "").trim();
        if (!title || !text) continue;
        rows.push({id, title, url: url.href, text});
      }
      return rows;
    """


def _mavila_card_base(card):
    """Accept only Mavila's public apply links with explicit Brazil eligibility."""
    title = str(card.get("title") or "").strip()
    text = str(card.get("text") or "")
    url = str(card.get("url") or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.casefold() not in {
        "unlockcareer.ai",
        "www.unlockcareer.ai",
    }:
        return None
    if not parsed.path.startswith(APPLY_PATH_PREFIX):
        return None
    native_id = parsed.path[len(APPLY_PATH_PREFIX):].strip("/").split("/")[0]
    if not native_id or not title or not is_brazil_location(text):
        return None
    return {
        "native_id": native_id,
        "title": title,
        "url": f"{MAVILA_ORIGIN}{parsed.path}",
        "text": text,
    }


def _posted_date(text):
    """Parse the portal's visible dates, preferring its pt-BR day/month format."""
    match = POSTED_DATE_RE.search(str(text or ""))
    if not match:
        return ""
    first, second, year = (int(part) for part in match.groups())
    if first > 12 and second <= 12:
        day, month = first, second
    elif second > 12 and first <= 12:
        month, day = first, second
    else:
        day, month = first, second
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _normalize_mavila_card(card):
    """Map one rendered public listing to the shared vacancy contract."""
    base = _mavila_card_base(card if isinstance(card, dict) else {})
    if not base:
        return None

    text = base["text"]
    levels = [
        label
        for label, pattern in (
            ("Junior", r"\b(?:junior|j[uú]nior|entry.level)\b"),
            ("Mid-level", r"\b(?:mid.level|pleno)\b"),
            ("Senior", r"\b(?:senior|s[eê]nior|principal|staff)\b"),
        )
        if re.search(pattern, text, re.I)
    ]
    return job(
        "unlockcareer_mavila",
        base["native_id"],
        title=base["title"],
        company="Mavila Consulting",
        url=base["url"],
        work_model=work_model_label(raw=text),
        country="BR",
        market="BR",
        published_date=_posted_date(text),
        description=strip_html(text, limit=6000),
        levels=levels,
    )


def fetch_mavila_consulting(today=None):
    """Collect Brazil-eligible roles from Mavila's public UnlockCareer board.

    The collector types a fixed country term into the public search field, reads
    only rendered listing cards and links, and never logs in or submits data.
    """
    del today  # Kept for consistency with date-injectable source adapters.
    driver = _new_driver()
    try:
        driver.set_page_load_timeout(TIMEOUT_SECONDS)
        driver.get(MAVILA_JOBS_URL)
        _wait_for_element(driver, "#career-page-search")
        try:
            from selenium.webdriver.common.by import By
        except ImportError as error:
            raise RuntimeError("Selenium is required to collect Mavila Consulting") from error

        search = driver.find_element(By.ID, "career-page-search")
        search.clear()
        search.send_keys("Brazil")
        _wait_for_element(
            driver,
            'a[href*="/jobs/mavila-consulting/apply/"]',
        )
        cards = driver.execute_script(_cards_script())
        if not isinstance(cards, list) or not cards:
            raise RuntimeError("Mavila Consulting returned no public vacancies")

        rows = []
        seen = set()
        for card in cards[:PER_COMPANY]:
            row = _normalize_mavila_card(card)
            if not row or row["native_id"] in seen:
                continue
            seen.add(row["native_id"])
            rows.append(row)
    finally:
        from ._rendered import _close_driver
        _close_driver(driver)

    if not rows:
        raise RuntimeError("Mavila Consulting returned no Brazilian vacancies")
    return rows
