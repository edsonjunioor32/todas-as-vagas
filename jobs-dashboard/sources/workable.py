# -*- coding: utf-8 -*-
"""Public RecargaPay vacancies from its Workable careers board.

The requested RecargaPay page delegates the live openings to Workable. The
public Workable board is rendered without authentication; this adapter clicks
its public "Show more" control and hydrates each detail page for descriptions.
"""
import os
import re
import time
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, urlunsplit

from ._common import iso_date, job, strip_html, work_model_label
from ._html import PublicPageParser
from ._http import get_text
from ._rendered import _webdriver


ORIGIN_URL = "https://recargapay.com.br/carreiras#nossasvagas"
LIST_URL = "https://apply.workable.com/recargapay/"
JOB_RE = re.compile(r"/recargapay/j/([A-Z0-9]+)(?:/|[?#]|$)", re.I)
ANCHOR_RE = re.compile(
    r"""<a\b(?P<attrs>[^>]*\bhref\s*=\s*["'](?P<href>[^"']+)["'][^>]*)>
    (?P<body>[\s\S]*?)</a>""",
    re.I | re.X,
)
ID_TEXT_RE = re.compile(
    r"""<(?:h[1-6]|small|div|p)\b[^>]*\bid=["']([^"']+)["'][^>]*>
    ([\s\S]*?)</(?:h[1-6]|small|div|p)>""",
    re.I | re.X,
)
DEFAULT_TIMEOUT = 90
DEFAULT_MAX_CLICKS = 12
DEFAULT_DETAIL_WORKERS = 6
LOAD_MORE_SELECTOR = '[data-ui="load-more-button"]'


def _canonical_url(href, base_url=LIST_URL):
    absolute = urljoin(base_url, str(href or "").strip())
    parsed = urlsplit(absolute)
    match = JOB_RE.search(parsed.path or "")
    if not match:
        return ""
    return urlunsplit((
        parsed.scheme or "https",
        parsed.netloc or "apply.workable.com",
        f"/recargapay/j/{match.group(1).upper()}/",
        "",
        "",
    ))


def _listing_links_from_markup(markup):
    """Parse the initial server-rendered Workable cards without a browser."""
    id_text = {
        identifier: strip_html(body).strip()
        for identifier, body in ID_TEXT_RE.findall(markup or "")
    }
    links = {}
    for match in ANCHOR_RE.finditer(markup or ""):
        canonical = _canonical_url(match.group("href"))
        if not canonical:
            continue
        label = strip_html(match.group("body") or "").strip()
        if not label:
            labelled = re.search(
                r"""aria-labelledby\s*=\s*["']([^"']+)["']""",
                match.group("attrs") or "",
                re.I,
            )
            if labelled:
                label = " ".join(
                    id_text.get(identifier, "")
                    for identifier in labelled.group(1).split()
                ).strip()
        links.setdefault(canonical, label)
    return list(links.items())


def _rendered_links():
    driver = _webdriver()
    try:
        driver.set_page_load_timeout(DEFAULT_TIMEOUT)
        driver.get(LIST_URL)
        deadline = time.monotonic() + DEFAULT_TIMEOUT
        collected = {}
        last_count = 0

        for _ in range(DEFAULT_MAX_CLICKS + 1):
            rows = []
            while time.monotonic() < deadline:
                rows = driver.execute_script(
                    """
                    const result = [];
                    const seen = new Set();
                    for (const anchor of document.querySelectorAll('a[href]')) {
                      const href = anchor.href || '';
                      if (!/\/recargapay\/j\/[A-Z0-9]+(?:[\/?#]|$)/i.test(href)) continue;
                      if (seen.has(href)) continue;
                      const ids = (anchor.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
                      const labelled = ids.map(id => {
                        const node = document.getElementById(id);
                        return node ? (node.innerText || node.textContent || '') : '';
                      }).join(' ');
                      const text = (anchor.innerText || anchor.textContent || labelled)
                        .replace(/\s+/g, ' ').trim();
                      if (!text) continue;
                      seen.add(href);
                      result.push([href, text]);
                    }
                    return result;
                    """
                ) or []
                if rows:
                    break
                time.sleep(0.5)

            for href, label in rows:
                collected.setdefault(_canonical_url(href), str(label))

            if len(collected) <= last_count:
                return list(collected.items())
            last_count = len(collected)

            state = driver.execute_script(
                """
                const button = document.querySelector(arguments[0]);
                if (!button) return {present:false};
                const style = window.getComputedStyle(button);
                const rect = button.getBoundingClientRect();
                return {
                  present:true,
                  disabled:button.disabled || button.getAttribute('aria-disabled') === 'true',
                  visible:style.display !== 'none' && style.visibility !== 'hidden' &&
                    rect.width > 0 && rect.height > 0
                };
                """,
                LOAD_MORE_SELECTOR,
            )
            if not state or not state.get("present") or state.get("disabled") or not state.get("visible"):
                return list(collected.items())

            before = set(collected)
            driver.execute_script(
                "document.querySelector(arguments[0]).click();",
                LOAD_MORE_SELECTOR,
            )
            while time.monotonic() < deadline:
                time.sleep(0.25)
                current = driver.execute_script(
                    """
                    return Array.from(document.querySelectorAll('a[href]'))
                      .filter(a => /\/recargapay\/j\/[A-Z0-9]+(?:[\/?#]|$)/i.test(a.href))
                      .map(a => a.href);
                    """
                ) or []
                if any(_canonical_url(href) not in before for href in current):
                    break
        return list(collected.items())
    finally:
        driver.quit()


def _relative_date(label):
    text = str(label or "").casefold()
    today = date.today()
    if re.search(r"posted\s+(?:few hours|an hour|today)", text):
        return today.isoformat()
    match = re.search(r"posted\s+(\d+)\s+day", text)
    if match:
        return (today - timedelta(days=int(match.group(1)))).isoformat()
    match = re.search(r"posted\s+(?:about\s+)?(\d+)\s+week", text)
    if match:
        return (today - timedelta(days=int(match.group(1)) * 7)).isoformat()
    match = re.search(r"posted\s+(?:about\s+)?(\d+)\s+month", text)
    if match:
        return (today - timedelta(days=int(match.group(1)) * 30)).isoformat()
    return ""


def _section_text(markup, section_name):
    pattern = re.compile(
        r"<section\b(?=[^>]*data-ui=["']job-"
        + re.escape(section_name)
        + r"["'])[^>]*>([\s\S]*?)</section>",
        re.I,
    )
    match = pattern.search(markup or "")
    return strip_html(match.group(1)) if match else ""


def _contracts(visible):
    values = []
    if re.search(r"\bfull[ -]time\b", visible, re.I):
        values.append("Full time")
    if re.search(r"\bpart[ -]time\b", visible, re.I):
        values.append("Part time")
    if re.search(r"\b(contract|contractor)\b", visible, re.I):
        values.append("Contract")
    return values


def _normalize_detail(url, markup, fallback_label=""):
    parser = PublicPageParser()
    parser.feed(markup)
    title = next((
        strip_html(value).strip()
        for value in parser.headings
        if strip_html(value).strip()
    ), "")
    match = JOB_RE.search(urlsplit(url).path or "")
    native_id = match.group(1).upper() if match else ""
    if not native_id or not title:
        return None

    visible = parser.visible_text
    raw_model = f"{fallback_label} {visible}"
    description_parts = [
        _section_text(markup, name)
        for name in ("description", "requirements", "benefits")
    ]
    description = strip_html(
        " ".join(part for part in description_parts if part)
        or visible
    )
    country = "BR" if re.search(r"\b(brazil|brasil)\b", raw_model, re.I) else ""
    city = "Brasil" if country else ""
    return job(
        "recargapay",
        native_id,
        title=title,
        company="RecargaPay",
        url=_canonical_url(url),
        work_model=work_model_label(raw=raw_model) or "remote",
        city=city,
        country=country or "BR",
        market="BR",
        published_date=_relative_date(fallback_label),
        description=description,
        categories=["Fintech"],
        contract_types=_contracts(visible),
    )


def fetch():
    try:
        links = _rendered_links()
    except Exception as error:
        print(f"    [recargapay] renderização indisponível: {str(error)[:120]}")
        try:
            links = _listing_links_from_markup(get_text(
                LIST_URL,
                headers={"Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8"},
                timeout=45,
                retries=2,
            ))
        except Exception:
            links = []

    if not links:
        raise RuntimeError("RecargaPay não expôs vagas públicas no Workable")

    workers = min(max(1, int(
        os.environ.get("RECARGAPAY_DETAIL_WORKERS") or DEFAULT_DETAIL_WORKERS
    )), 12)
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                lambda u=url, l=label: _normalize_detail(
                    u,
                    get_text(
                        u,
                        headers={"Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8"},
                        timeout=45,
                        retries=2,
                    ),
                    l,
                )
            ): url
            for url, label in links
        }
        for future in as_completed(futures):
            try:
                row = future.result()
            except Exception:
                continue
            if row:
                rows.append(row)

    unique = {row["native_id"]: row for row in rows}
    if not unique:
        raise RuntimeError("RecargaPay não retornou vagas reconhecíveis")
    return list(unique.values())
