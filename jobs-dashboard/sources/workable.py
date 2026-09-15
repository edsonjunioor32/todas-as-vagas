# -*- coding: utf-8 -*-
"""Public RecargaPay vacancies from its Workable careers board.

The account exposes a key-free Workable widget feed. The adapter reads that
JSON first, retaining a browser-rendered fallback for transient feed changes.
"""
import os
import re
import time
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, urlunsplit

from ._common import iso_date, job, strip_html, work_model_label
from ._html import PublicPageParser
from ._http import get_json, get_text
from ._rendered import _webdriver


ORIGIN_URL = "https://recargapay.com.br/carreiras#nossasvagas"
LIST_URL = "https://apply.workable.com/recargapay/"
PUBLIC_API_URL = "https://apply.workable.com/api/v1/widget/accounts/recargapay"
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
    path = parsed.path or ""
    match = JOB_RE.search(path)
    if not match:
        match = re.search(
            r"/jobs/([A-Z0-9_-]+)(?:/|$)",
            path,
            re.I,
        )
    if not match:
        return ""
    return urlunsplit((
        "https",
        "apply.workable.com",
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
        r'<section\b(?=[^>]*data-ui=["\']job-'
        + re.escape(section_name)
        + r'["\'])[^>]*>([\s\S]*?)</section>',
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


def _text(value):
    return str(value or "").strip()


def _api_native_id(item):
    for key in ("shortcode", "id", "code"):
        value = _text(item.get(key))
        if value:
            return value.upper()
    for key in ("shortlink", "url", "application_url"):
        match = re.search(
            r"/(?:j|jobs)/([A-Z0-9_-]+)(?:/|$)",
            _text(item.get(key)),
            re.I,
        )
        if match:
            return match.group(1).upper()
    return ""


def _api_job_url(item, native_id):
    for key in ("shortlink", "application_url", "url"):
        canonical = _canonical_url(item.get(key))
        if canonical:
            return canonical
    return (
        f"https://apply.workable.com/recargapay/j/{native_id}/"
        if native_id
        else ""
    )


def _api_location(item):
    city = ""
    state = ""
    country = ""
    values = []

    location = item.get("location")
    if isinstance(location, dict):
        city = _text(location.get("city"))
        state = _text(
            location.get("state")
            or location.get("region")
            or location.get("state_code")
            or location.get("region_code")
        )
        country = _text(
            location.get("country")
            or location.get("country_name")
            or location.get("countryName")
            or location.get("country_code")
        )
        values.append(_text(location.get("location_str")))
    elif location:
        values.append(_text(location))

    locations = item.get("locations") or []
    if not isinstance(locations, list):
        locations = [locations]
    for entry in locations:
        if isinstance(entry, dict):
            if not city:
                city = _text(entry.get("city"))
            if not state:
                state = _text(
                    entry.get("state")
                    or entry.get("subregion")
                    or entry.get("state_code")
                    or entry.get("region")
                )
            if not country:
                country = _text(
                    entry.get("country")
                    or entry.get("country_name")
                    or entry.get("countryName")
                    or entry.get("country_code")
                )
            values.append(
                _text(
                    entry.get("location_str")
                    or entry.get("name")
                    or entry.get("city")
                )
            )
        elif _text(entry):
            values.append(_text(entry))

    visible = " ".join(value for value in values if value)
    if not city and visible:
        parts = [part.strip() for part in visible.split(",") if part.strip()]
        if parts and parts[0].casefold() not in {"brazil", "brasil", "remote"}:
            city = parts[0]
        if len(parts) >= 2 and not state:
            state = parts[-2] if len(parts) >= 3 else ""
        if not country and parts and parts[-1].casefold() in {"brazil", "brasil", "br"}:
            country = parts[-1]

    is_brazil = (
        country.casefold() in {"brazil", "brasil", "br"}
        or "brazil" in visible.casefold()
        or "brasil" in visible.casefold()
    )
    return {
        "city": city or "Brasil",
        "state": state,
        "country": "BR" if is_brazil or not country else country,
        "text": visible,
    }


def _api_work_model(item, location):
    telecommuting = item.get("telecommuting")
    if telecommuting is True or _text(telecommuting).casefold() in {"true", "1", "yes"}:
        return "remote"
    raw = " ".join(
        _text(value)
        for value in (
            item.get("workplace_type"),
            item.get("workplace"),
            item.get("location_type"),
            location.get("text"),
        )
        if _text(value)
    )
    return work_model_label(raw=raw) or "on-site"


def _api_contracts(item):
    value = (
        item.get("employment_type")
        or item.get("employmentType")
        or item.get("contract_type")
        or item.get("work_type")
    )
    if isinstance(value, list):
        return [_text(part) for part in value if _text(part)]
    return [_text(value)] if _text(value) else []


def _api_description(item):
    parts = [
        item.get("full_description"),
        item.get("description"),
        item.get("requirements"),
        item.get("benefits"),
    ]
    values = [_text(part) for part in parts if _text(part)]
    return strip_html(" ".join(values))[:6000]


def _normalize_api_job(item):
    if not isinstance(item, dict):
        return None
    native_id = _api_native_id(item)
    title = _text(item.get("title"))
    url = _api_job_url(item, native_id)
    if not native_id or not title or not url:
        return None

    location = _api_location(item)
    department = _text(item.get("department"))
    return job(
        "recargapay",
        native_id,
        title=title,
        company="RecargaPay",
        url=url,
        work_model=_api_work_model(item, location),
        city=location["city"],
        state=location["state"],
        country=location["country"],
        market="BR",
        published_date=iso_date(
            item.get("published_on")
            or item.get("published_at")
            or item.get("created_at")
        ),
        description=_api_description(item),
        categories=[department] if department else [],
        contract_types=_api_contracts(item),
    )


def _fetch_public_api():
    payload = get_json(
        f"{PUBLIC_API_URL}?details=true",
        headers={"Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8"},
        timeout=45,
        retries=3,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Workable RecargaPay retornou um payload inválido")
    jobs = payload.get("jobs") or []
    if not isinstance(jobs, list):
        raise RuntimeError("Workable RecargaPay retornou uma lista de vagas inválida")
    rows = {}
    for item in jobs:
        row = _normalize_api_job(item)
        if row:
            rows.setdefault(row["native_id"], row)
    return list(rows.values())


def fetch():
    api_error = ""
    try:
        rows = _fetch_public_api()
        if rows:
            return rows
        api_error = "feed público sem vagas reconhecíveis"
    except Exception as error:
        api_error = str(error)[:180]
        print(f"    [recargapay] API pública indisponível: {api_error}")

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
        raise RuntimeError(
            "RecargaPay não expôs vagas públicas no Workable"
            + (f" ({api_error})" if api_error else "")
        )

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
