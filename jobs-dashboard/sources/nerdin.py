# -*- coding: utf-8 -*-
"""Nerdin — public Brazilian vacancies parsed from the portal cards."""
import concurrent.futures
import html
import os
import re

from ._common import job, strip_html, work_model_label
from ._http import get_text


BASE_URL = "https://www.nerdin.com.br/vagas.php"
SOURCE = "Nerdin"
DEFAULT_WORKERS = 6


def _clean(fragment):
    fragment = re.sub(
        r"<span[^>]*vaga-nova-badge[^>]*>.*?</span>",
        " ",
        fragment or "",
        flags=re.S | re.I,
    )
    return re.sub(r"\s+", " ", strip_html(html.unescape(fragment or ""))).strip()


def _first(pattern, text):
    match = re.search(pattern, text, re.S | re.I)
    return _clean(match.group(1)) if match else ""


def _money(value):
    values = []
    for raw in re.findall(r"R\$\s*([\d.]+(?:,\d{2})?)", value or ""):
        try:
            values.append(float(raw.replace(".", "").replace(",", ".")))
        except ValueError:
            pass
    if not values:
        return None, None, None
    return min(values), max(values) if len(values) > 1 else None, "BRL"


def _parse_card(block):
    href_match = re.search(r'data-href=["\']([^"\']+)["\']', block, re.I)
    if not href_match:
        return None
    relative_url = html.unescape(href_match.group(1))
    native_id_match = re.search(r"-(\d+)\.php$", relative_url)
    title = _first(r'<h3[^>]*class=["\'][^"\']*vaga-titulo[^"\']*["\'][^>]*>(.*?)</h3>', block)
    company = _first(r'<span[^>]*class=["\'][^"\']*vaga-empresa-nome[^"\']*["\'][^>]*>(.*?)</span>', block)
    location = _first(r'<div[^>]*class=["\'][^"\']*vaga-local-linha[^"\']*["\'][^>]*>(.*?)</div>', block)
    summary = _first(r'<p[^>]*class=["\'][^"\']*vaga-resumo-linha[^"\']*["\'][^>]*>(.*?)</p>', block)
    meta = _first(r'<p[^>]*class=["\'][^"\']*vaga-meta-extra[^"\']*["\'][^>]*>(.*?)</p>', block)
    published = ""
    datetime_match = re.search(
        r'<time[^>]+datetime=["\'](\d{4}-\d{2}-\d{2}(?:T[0-9:+-]+)?)',
        block,
        re.I,
    )
    if datetime_match:
        published = datetime_match.group(1)
    if not title or not company:
        return None

    parts = [part.strip() for part in summary.split("•") if part.strip()]
    contracts = [
        part for part in parts
        if part.lower() in {"clt", "pj", "freelancer", "cooperado"}
    ]
    state = ""
    if "•" in location:
        city_parts = [part.strip() for part in location.split("•") if part.strip()]
        if city_parts and len(city_parts[-1]) == 2:
            state = city_parts[-1].upper()
    categories = [part.strip() for part in meta.split("•")[:1] if part.strip()]
    tags = [
        _clean(value)
        for value in re.findall(
            r'<a[^>]*class=["\'][^"\']*hashtag[^"\']*["\'][^>]*>(.*?)</a>',
            block,
            re.S | re.I,
        )
    ]
    low, high, currency = _money(block)
    return job(
        SOURCE,
        native_id_match.group(1) if native_id_match else relative_url,
        title=title,
        company=company,
        url=f"https://www.nerdin.com.br/{relative_url.lstrip('/')}",
        work_model=work_model_label(raw=summary),
        city=location,
        state=state,
        country="BR",
        market="BR",
        salary_min=low,
        salary_max=high,
        salary_currency=currency,
        published_date=published,
        skills=[tag.lstrip("#") for tag in tags if tag],
        levels=parts,
        categories=categories + tags,
        contract_types=contracts,
        pcd="pcd" in f"{title} {summary}".lower(),
    )


def _parse_page(markup):
    cards = re.split(
        r'(?=<div[^>]*class=["\'][^"\']*vaga-card[^"\']*["\'])',
        markup,
        flags=re.I,
    )
    rows = [row for block in cards if (row := _parse_card(block))]
    pages_match = re.search(r"Página\s+\d+\s+de\s+(\d+)", markup, re.I)
    return rows, int(pages_match.group(1)) if pages_match else 1


def _fetch_page(page):
    suffix = "" if page == 1 else f"?pagina={page}"
    return _parse_page(get_text(f"{BASE_URL}{suffix}", timeout=40, retries=3))


def fetch():
    first_rows, total_pages = _fetch_page(1)
    workers = min(
        max(1, int(os.environ.get("NERDIN_WORKERS") or DEFAULT_WORKERS)),
        8,
    )
    pages = {1: first_rows}
    if total_pages > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_fetch_page, page): page
                for page in range(2, total_pages + 1)
            }
            for future in concurrent.futures.as_completed(futures):
                pages[futures[future]] = future.result()[0]

    unique = {}
    for page in range(1, total_pages + 1):
        for row in pages.get(page, []):
            unique[row["native_id"] or row["url"]] = row
    return list(unique.values())
