# -*- coding: utf-8 -*-
"""Adaptadores para os portais solicitados em 28/08/2026.

Os dois portais desta leva são mantidos em funções isoladas para que cada
fonte possa ser validada antes de integrar o resultado ao catálogo geral.
"""
import html
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from ._common import is_brazil_location, job, strip_html, work_model_label
from ._http import get_text


LUZA_URL = "https://www.careers-page.com/luza-group"
LUZA_COMPANY = "LUZA Group"
BTG_URL = "https://carreiras.btgpactual.com/vagas"
BTG_SITEMAP_URL = "https://carreiras.btgpactual.com/sitemap.xml"
BTG_COMPANY = "BTG Pactual"


def _configured_int(name, default, minimum=1, maximum=100):
    try:
        value = int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _positive_count(page):
    text = strip_html(page)
    match = re.search(r"([\d.]+)\s+Posi(?:ções|coes)\s+abertas", text, re.I)
    if not match:
        return 0
    try:
        return int(match.group(1).replace(".", ""))
    except ValueError:
        return 0


class _LuzaListingParser(HTMLParser):
    """Extract one title/location pair from each LUZA vacancy card."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._li_depth = 0
        self._href = ""
        self._heading = False
        self._heading_parts = []
        self._location_depth = 0
        self._location_parts = []

    def _reset_card(self):
        self._href = ""
        self._heading = False
        self._heading_parts = []
        self._location_depth = 0
        self._location_parts = []

    def _finish_card(self):
        title = strip_html(" ".join(self._heading_parts))
        location = strip_html(" ".join(self._location_parts))
        if self._href and title:
            self.rows.append((self._href, title, location))
        self._reset_card()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = dict(attrs)
        if tag == "li":
            if self._li_depth == 0:
                self._reset_card()
            self._li_depth += 1
            return
        if not self._li_depth:
            return
        if tag == "a" and not self._href:
            href = str(attributes.get("href") or "").strip()
            if re.search(r"/luza-group/job/[^/?#]+", href, re.I):
                self._href = href
        elif tag == "h5":
            self._heading = True
        elif tag == "span":
            classes = str(attributes.get("class") or "").split()
            if "text-secondary" in classes:
                self._location_depth += 1

    def handle_data(self, data):
        if self._heading:
            self._heading_parts.append(data)
        if self._location_depth:
            self._location_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "h5":
            self._heading = False
        elif tag == "span" and self._location_depth:
            self._location_depth -= 1
        elif tag == "li" and self._li_depth:
            self._li_depth -= 1
            if self._li_depth == 0:
                self._finish_card()


def _luza_page(page_number):
    url = LUZA_URL if page_number == 1 else f"{LUZA_URL}?page={page_number}"
    markup = get_text(url, timeout=45, retries=3)
    parser = _LuzaListingParser()
    parser.feed(markup)
    return parser.rows, _positive_count(markup)


def _luza_row(item):
    href, title, location = item
    absolute = urljoin(LUZA_URL, html.unescape(href)).split("#", 1)[0]
    parsed = urlsplit(absolute)
    if parsed.netloc.casefold() != "www.careers-page.com":
        return None
    if not is_brazil_location(location):
        return None
    parts = [part.strip() for part in location.split(",") if part.strip()]
    city = parts[0] if parts else ""
    state = parts[1] if len(parts) > 2 else ""
    native_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not native_id or len(title) < 4:
        return None
    return job(
        "luza",
        native_id,
        title=title,
        company=LUZA_COMPANY,
        url=absolute,
        work_model=work_model_label(raw=f"{title} {location}"),
        city=city,
        state=state,
        country="BR",
        market="BR",
    )


def fetch_luza():
    first_items, total_count = _luza_page(1)
    if not first_items:
        raise RuntimeError("luza returned no public vacancy cards")
    page_size = len(first_items)
    estimated_pages = math.ceil(total_count / page_size) if total_count else 60
    total_pages = min(
        estimated_pages,
        _configured_int("LUZA_MAX_PAGES", estimated_pages, maximum=100),
    )
    workers = _configured_int("LUZA_WORKERS", 6, maximum=8)
    pages = {1: first_items}
    failed_pages = []

    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_luza_page, page): page
                for page in range(2, total_pages + 1)
            }
            for future in as_completed(futures):
                page = futures[future]
                try:
                    pages[page] = future.result()[0]
                except Exception:
                    failed_pages.append(page)

    unique = {}
    for page in range(1, total_pages + 1):
        for item in pages.get(page, []):
            row = _luza_row(item)
            if row:
                unique[row["native_id"] or row["url"]] = row

    if failed_pages:
        error = RuntimeError(
            f"luza pagination failed on {len(failed_pages)}/{total_pages - 1} pages"
        )
        error.rows = list(unique.values())
        raise error
    if not unique:
        raise RuntimeError("luza returned no Brazil vacancy cards")
    return list(unique.values())


def _btg_job_href(value):
    parsed = urlsplit(str(value or ""))
    path = parsed.path.rstrip("/").casefold()
    path_job = bool(re.search(r"/\d{6,}$", path))
    query_job = bool(re.search(r"(?:^|&)gh_jid=\d{6,}(?:&|$)", parsed.query))
    return path.startswith("/vagas") and (path_job or query_job)


class _BtgListingParser(HTMLParser):
    """Extract cards from the rendered BTG all-vacancies page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._card_depth = 0
        self._href = ""
        self._title_parts = []
        self._anchor_active = False
        self._location_active = False
        self._location_parts = []

    def _reset_card(self):
        self._href = ""
        self._title_parts = []
        self._anchor_active = False
        self._location_active = False
        self._location_parts = []

    def _finish_card(self):
        title = strip_html(" ".join(self._title_parts))
        location = strip_html(" ".join(self._location_parts))
        if self._href and title and title.casefold() != "ver vaga":
            self.rows.append((self._href, title, location))
        self._reset_card()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = dict(attrs)
        classes = str(attributes.get("class") or "").split()
        if tag == "div":
            if self._card_depth == 0 and "card-job" in classes:
                self._card_depth = 1
                self._reset_card()
                return
            if self._card_depth:
                self._card_depth += 1
        if not self._card_depth:
            return
        if tag == "a" and not self._href:
            href = str(attributes.get("href") or "").strip()
            if _btg_job_href(href):
                self._href = href
                self._anchor_active = True
        elif tag == "p" and "subtitle" in classes:
            self._location_active = True

    def handle_data(self, data):
        if self._anchor_active:
            self._title_parts.append(data)
        if self._location_active:
            self._location_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self._anchor_active:
            self._anchor_active = False
        elif tag == "p" and self._location_active:
            self._location_active = False
        elif tag == "div" and self._card_depth:
            self._card_depth -= 1
            if self._card_depth == 0:
                self._finish_card()


def _btg_listing_items(markup):
    parser = _BtgListingParser()
    parser.feed(markup)
    if parser.rows:
        return parser.rows
    # Keep a fallback for a minor markup change that removes the card wrapper.
    rows, seen = [], set()
    for href, label in re.findall(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        markup,
        re.I | re.S,
    ):
        if not _btg_job_href(href):
            continue
        absolute = urljoin(BTG_URL, html.unescape(href))
        title = strip_html(html.unescape(label))
        if len(title) < 4 or title.casefold() == "ver vaga" or absolute in seen:
            continue
        seen.add(absolute)
        rows.append((absolute, title, ""))
    return rows


def _btg_slug_title(url):
    parts = [unquote(part) for part in urlsplit(url).path.rstrip("/").split("/") if part]
    if len(parts) >= 2 and re.fullmatch(r"\d{6,}", parts[-1]):
        slug = parts[-2]
    elif parts:
        slug = parts[-1]
    else:
        slug = ""
    if slug.casefold() == "vagas":
        job_id = _btg_native_id(url)
        return f"Vaga BTG Pactual {job_id}" if job_id else ""
    return re.sub(r"[-_]+", " ", slug).strip()


def _btg_native_id(url):
    match = re.search(r"/(\d{6,})/?(?:\?|$)", urlsplit(url).path + ("?" + urlsplit(url).query if urlsplit(url).query else ""))
    if match:
        return match.group(1)
    query_id = re.search(r"(?:^|&)gh_jid=(\d+)(?:&|$)", urlsplit(url).query)
    return query_id.group(1) if query_id else url.rstrip("/").rsplit("/", 1)[-1]


def _btg_row(url, title, location="", category="", description="", raw=""):
    title = strip_html(html.unescape(title))
    location = strip_html(html.unescape(location))
    if not title or not _btg_job_href(url):
        return None
    if location and not is_brazil_location(location):
        return None
    parts = [part.strip() for part in location.split(",") if part.strip()]
    city = parts[0] if parts else "Brasil"
    state = parts[1] if len(parts) > 2 else ""
    raw_text = " ".join((title, category, location, description, raw))
    return job(
        "btg",
        _btg_native_id(url),
        title=title,
        company=BTG_COMPANY,
        url=urljoin(BTG_URL, url),
        work_model=work_model_label(raw=raw_text),
        city=city,
        state=state,
        country="BR",
        market="BR",
        description=strip_html(description),
        categories=[category] if category else [],
    )


def _btg_listing_rows(markup):
    return [
        row
        for href, title, location in _btg_listing_items(markup)
        if (row := _btg_row(href, title, location=location, raw=markup)) is not None
    ]


def _html_heading(markup, tag):
    match = re.search(
        rf"<{tag}\b[^>]*>(.*?)</{tag}>",
        markup,
        re.I | re.S,
    )
    return strip_html(match.group(1)) if match else ""


def _html_meta(markup, name):
    match = re.search(
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\'](.*?)["\']',
        markup,
        re.I | re.S,
    )
    return html.unescape(match.group(1)).strip() if match else ""


def _btg_detail_row(url, markup):
    title = _html_heading(markup, "h1")
    if not title:
        title = _html_meta(markup, "og:title")
    if not title:
        title = _html_meta(markup, "twitter:title")
    if " | " in title:
        title = title.split(" | ", 1)[0].strip()
    if not title:
        title = _btg_slug_title(url)
    category = _html_heading(markup, "h2")
    location = _html_heading(markup, "h3")
    description = _html_meta(markup, "description")
    return _btg_row(
        url,
        title,
        location=location,
        category=category,
        description=description,
        raw=strip_html(markup),
    )


def _sitemap_locs(markup):
    decoded = html.unescape(markup or "")
    values = re.findall(r"<loc>\s*(.*?)\s*</loc>", decoded, re.I | re.S)
    if not values:
        values = re.findall(
            r"https?://carreiras\.btgpactual\.com[^<\"'\s]+",
            decoded,
            re.I,
        )
    return list(dict.fromkeys(html.unescape(value).strip() for value in values))


def _sitemap_urls(markup, depth=0):
    direct = [
        value for value in _sitemap_locs(markup)
        if _btg_job_href(value)
    ]
    if direct or depth >= 3:
        return list(dict.fromkeys(direct))

    nested = []
    for value in _sitemap_locs(markup):
        location = urlsplit(value)
        sitemap_path = location.path.casefold()
        if (
            "sitemap" not in sitemap_path
            and ".xml" not in sitemap_path
            and "sitemap" not in location.query.casefold()
        ):
            continue
        try:
            child = get_text(value, timeout=45, retries=3)
        except Exception:
            continue
        nested.extend(_sitemap_urls(child, depth=depth + 1))
    return list(dict.fromkeys(nested))


def _btg_detail_fetch(url):
    markup = get_text(url, timeout=45, retries=3)
    return _btg_detail_row(url, markup)


def _new_btg_driver():
    try:
        from selenium import webdriver
    except ImportError as error:
        raise RuntimeError("Selenium is required for the rendered BTG careers page") from error

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


def _btg_rendered_items(driver):
    return driver.execute_script(
        r"""
        const seen = new Set();
        const rows = [];
        const countText = (document.querySelector(".vacancies-found") || {}).innerText || "";
        const countMatch = countText.match(/([\d.]+)\s+vagas encontradas/i);
        const total = countMatch ? Number(countMatch[1].replace(/\./g, "")) : 0;

        for (const anchor of document.querySelectorAll("a[href]")) {
          const href = anchor.href || "";
          let parsed;
          try {
            parsed = new URL(href);
          } catch (_error) {
            continue;
          }
          if (parsed.hostname !== "carreiras.btgpactual.com"
              || !parsed.pathname.toLowerCase().startsWith("/vagas")) {
            continue;
          }
          const pathId = (parsed.pathname.match(/\/(\d{6,})\/?$/) || [])[1];
          const queryId = (parsed.search.match(/[?&]gh_jid=(\d{6,})(?:&|$)/i) || [])[1];
          const id = pathId || queryId;
          if (!id || seen.has(id)) continue;

          const card = anchor.closest(".card-job")
            || anchor.closest("app-card-job")
            || anchor.closest("article")
            || anchor.parentElement;
          const titleNode = (card && card.querySelector("h3 a[href]")) || anchor;
          const locationNode = card && card.querySelector("p.subtitle");
          const title = (titleNode.innerText || titleNode.textContent || "")
            .replace(/\s+/g, " ").trim();
          if (!title || title.toLowerCase() === "ver vaga") continue;
          seen.add(id);
          rows.push({
            href: href,
            title: title,
            location: ((locationNode && (locationNode.innerText || locationNode.textContent)) || "")
              .replace(/\s+/g, " ").trim(),
            raw: ((card && card.innerText) || title).replace(/\s+/g, " ").trim(),
          });
        }
        return {total: total, rows: rows};
        """,
    )


def _btg_rendered_rows():
    timeout = _configured_int("BTG_RENDER_TIMEOUT", 90, maximum=120)
    driver = _new_btg_driver()
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(BTG_URL)
        deadline = time.monotonic() + timeout
        current = {"total": 0, "rows": []}
        collected = {}
        previous_count = 0
        while time.monotonic() < deadline:
            current = _btg_rendered_items(driver)
            for item in current["rows"]:
                key = _btg_native_id(item.get("href")) or item.get("href")
                collected[key] = item
            if collected and (
                not current["total"] or len(collected) >= current["total"]
            ):
                break
            # BTG initially exposes only the first 100 cards. Scroll and
            # activate the public continuation control, when present, until
            # the number shown by the page is reached.
            if len(collected) == previous_count:
                driver.execute_script(
                    r"""
                    window.scrollTo(0, document.body.scrollHeight);
                    const labels = /^(?:carregar mais|ver mais|próximo|proximo|next|mais vagas)$/i;
                    const nodes = Array.from(document.querySelectorAll("button, a"));
                    const candidate = nodes.find(node => {
                      const text = (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
                      const aria = (node.getAttribute("aria-label") || "").trim();
                      const disabled = node.disabled
                        || node.getAttribute("aria-disabled") === "true";
                      return !disabled && (
                        labels.test(text)
                        || /(?:próximo|proximo|next)/i.test(aria)
                      );
                    });
                    if (candidate) candidate.click();
                    """,
                )
            else:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            previous_count = len(collected)
            time.sleep(1)
        if not collected:
            raise RuntimeError("BTG did not expose public vacancy cards after rendering")
        if current["total"] and len(collected) < current["total"]:
            raise RuntimeError(
                f"BTG rendered only {len(collected)}/{current['total']} vacancy cards"
            )

        rows = []
        for item in collected.values():
            row = _btg_row(
                item["href"],
                item["title"],
                location=item.get("location", ""),
                raw=item.get("raw", ""),
            )
            if row:
                rows.append(row)
        if not rows:
            raise RuntimeError("BTG rendered no Brazil vacancy cards")
        unique = {row["native_id"] or row["url"]: row for row in rows}
        return list(unique.values())
    finally:
        driver.quit()


def fetch_btg():
    rendered_error = None
    try:
        rows = _btg_rendered_rows()
        if rows:
            return rows
    except Exception as error:
        rendered_error = error

    listing = get_text(BTG_URL, timeout=45, retries=3)
    rows = _btg_listing_rows(listing)
    if rows:
        unique = {row["native_id"] or row["url"]: row for row in rows}
        return list(unique.values())

    sitemap = get_text(BTG_SITEMAP_URL, timeout=45, retries=3)
    urls = _sitemap_urls(sitemap)
    if not urls:
        detail = f"; rendered: {rendered_error}" if rendered_error else ""
        raise RuntimeError(f"btg returned no public vacancy cards or sitemap URLs (listing={len(listing)} bytes, sitemap={len(sitemap)} bytes{detail})")

    workers = _configured_int("BTG_WORKERS", 8, maximum=12)
    details, failed = {}, []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_btg_detail_fetch, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                row = future.result()
                if row:
                    details[row["native_id"] or row["url"]] = row
            except Exception:
                failed.append(url)

    if failed:
        error = RuntimeError(
            f"btg detail requests failed on {len(failed)}/{len(urls)} pages"
        )
        error.rows = list(details.values())
        raise error
    if not details:
        raise RuntimeError("btg sitemap contained no usable Brazil vacancies")
    return list(details.values())


TARGETS = (
    ("btg", fetch_btg),
    ("luza", fetch_luza),
)
