# -*- coding: utf-8 -*-
"""Public NG.CASH careers page (Revolut People)."""

from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

from ._common import job
from ._rendered import _webdriver


CAREERS_URL = "https://people-jobs.com/ngcash/"
FRAME_SELECTOR = "iframe#careerWebsite"
POSITION_RE = re.compile(
    r"/ngcash/public/careers/position/([^/?#]+)",
    re.IGNORECASE,
)
DEFAULT_TIMEOUT = 90
MAX_POSITIONS = 200


def _switch_to_careers(driver, timeout=DEFAULT_TIMEOUT):
    """Enter the cross-origin career iframe after each outer-page navigation."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    driver.switch_to.default_content()
    frame = WebDriverWait(driver, timeout).until(
        lambda current: current.find_element(By.CSS_SELECTOR, FRAME_SELECTOR)
    )
    driver.switch_to.frame(frame)
    WebDriverWait(driver, timeout).until(
        lambda current: current.find_element(By.TAG_NAME, "body")
    )


def _page(driver):
    """Read the visible iframe content without depending on React internals."""
    return driver.execute_script(
        """
        const root = document.querySelector("main,[role='main']") || document.body;
        const links = Array.from(
          root.querySelectorAll('a[href*="/ngcash/public/careers/position/"]')
        ).map((anchor) => ({
          href: anchor.href,
          text: (anchor.innerText || anchor.textContent || "").trim(),
        }));
        const buttons = Array.from(root.querySelectorAll("button"));
        const loadMore = buttons.find((button) =>
          /load more|carregar mais|ver mais/i.test(
            (button.innerText || button.textContent || "").trim()
          )
        );
        const heading = root.querySelector("h1,h2");
        return {
          heading: heading ? (heading.innerText || heading.textContent || "").trim() : "",
          text: (root.innerText || root.textContent || "").trim(),
          links,
          loadMore: loadMore || null,
        };
        """
    )


def _collect_listing(driver):
    """Collect all currently exposed positions, including future load-more batches."""
    from selenium.webdriver.support.ui import WebDriverWait

    positions = {}
    previous_count = -1
    stagnant_rounds = 0

    for _ in range(MAX_POSITIONS):
        page = _page(driver)
        for item in page.get("links") or []:
            href = str(item.get("href") or "").strip()
            match = POSITION_RE.search(urlsplit(href).path)
            if not match:
                continue
            positions[href] = {
                "slug": match.group(1),
                "title": str(item.get("text") or "").strip(),
                "listing_text": page.get("text") or "",
            }

        button = page.get("loadMore")
        if not button:
            break
        count_before = len(positions)
        if count_before == previous_count:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
        if stagnant_rounds >= 2:
            break
        previous_count = count_before

        try:
            driver.execute_script("arguments[0].click();", button)
            WebDriverWait(driver, 15).until(
                lambda current: len(_page(current).get("links") or []) > count_before
            )
        except Exception:
            break

    if not positions:
        raise RuntimeError("NG.CASH não exibiu nenhuma vaga no quadro público")
    if len(positions) > MAX_POSITIONS:
        raise RuntimeError("NG.CASH excedeu o limite de segurança de vagas coletadas")
    return list(positions.values())


def _canonical_url(slug):
    return f"{CAREERS_URL.rstrip('/')}/public/careers/position/{slug}"


def _work_model(raw):
    if re.search(r"\b(remote|remoto|home\s*office)\b", raw, re.IGNORECASE):
        return "remote"
    if re.search(r"\b(office|on[-\s]?site|presencial)\b", raw, re.IGNORECASE):
        return "on-site"
    return ""


def _location(raw):
    if re.search(r"\b(são\s+paulo|sao\s+paulo)\b", raw, re.IGNORECASE):
        return "São Paulo", "SP"
    if re.search(r"\b(brasil|brazil)\b", raw, re.IGNORECASE):
        return "Brasil", ""
    return "", ""


def _normalize_position(slug, title, listing_text, detail_text):
    """Normalize a position into the catalog contract."""
    detail = str(detail_text or "").strip()
    listing = str(listing_text or "").strip()
    raw = detail or listing
    city, state = _location(raw)
    return job(
        "ngcash",
        slug,
        title=title.strip() or slug.replace("-", " ").title(),
        company="NG.CASH",
        url=_canonical_url(slug),
        work_model=_work_model(raw),
        city=city,
        state=state,
        country="BR" if re.search(r"\b(brasil|brazil)\b", raw, re.IGNORECASE) else "",
        market="BR" if re.search(r"\b(brasil|brazil)\b", raw, re.IGNORECASE) else "",
        description=detail[:60000],
    )


def fetch():
    """Collect NG.CASH positions from the public rendered page."""
    driver = _webdriver()
    rows = []
    try:
        driver.set_page_load_timeout(DEFAULT_TIMEOUT)
        driver.get(CAREERS_URL)
        _switch_to_careers(driver)
        from selenium.webdriver.support.ui import WebDriverWait

        WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            lambda current: bool(_page(current).get("links"))
        )
        listings = _collect_listing(driver)

        for listing in listings:
            url = _canonical_url(listing["slug"])
            detail_text = ""
            try:
                driver.get(url)
                _switch_to_careers(driver)
                detail = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
                    lambda current: _page(current)
                )
                detail_text = str(detail.get("text") or "").strip()
                detail_title = str(detail.get("heading") or "").strip()
                title = detail_title or listing["title"]
            except Exception:
                title = listing["title"]
            rows.append(
                _normalize_position(
                    listing["slug"],
                    title,
                    listing["listing_text"],
                    detail_text,
                )
            )
        return rows
    finally:
        driver.quit()
