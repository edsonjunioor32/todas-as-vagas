#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atualiza somente a fonte Nerdin, preservando todos os demais portais."""
import concurrent.futures
import html
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "jobs-dashboard"
sys.path.insert(0, str(DASHBOARD))

import classify  # noqa: E402
import storage  # noqa: E402
from sources._common import job, strip_html, work_model_label  # noqa: E402
from sources._http import get_text  # noqa: E402


BASE_URL = "https://www.nerdin.com.br/vagas.php"
SOURCE = "Nerdin"
PAGE_SIZE = 20
MAX_WORKERS = 6


def clean(fragment):
    fragment = re.sub(r"<span[^>]*vaga-nova-badge[^>]*>.*?</span>", " ", fragment or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", strip_html(html.unescape(fragment or ""))).strip()


def first(pattern, text):
    match = re.search(pattern, text, re.S | re.I)
    return clean(match.group(1)) if match else ""


def money(value):
    values = []
    for raw in re.findall(r"R\$\s*([\d.]+(?:,\d{2})?)", value or ""):
        try:
            values.append(float(raw.replace(".", "").replace(",", ".")))
        except ValueError:
            pass
    return (min(values), max(values) if len(values) > 1 else None, "BRL") if values else (None, None, None)


def parse_card(block):
    href_match = re.search(r'data-href=["\']([^"\']+)["\']', block, re.I)
    if not href_match:
        return None
    relative_url = html.unescape(href_match.group(1))
    native_id_match = re.search(r"-(\d+)\.php$", relative_url)
    title = first(r'<h3[^>]*class=["\'][^"\']*vaga-titulo[^"\']*["\'][^>]*>(.*?)</h3>', block)
    company = first(r'<span[^>]*class=["\'][^"\']*vaga-empresa-nome[^"\']*["\'][^>]*>(.*?)</span>', block)
    location = first(r'<div[^>]*class=["\'][^"\']*vaga-local-linha[^"\']*["\'][^>]*>(.*?)</div>', block)
    summary = first(r'<p[^>]*class=["\'][^"\']*vaga-resumo-linha[^"\']*["\'][^>]*>(.*?)</p>', block)
    meta = first(r'<p[^>]*class=["\'][^"\']*vaga-meta-extra[^"\']*["\'][^>]*>(.*?)</p>', block)
    published = ""
    datetime_match = re.search(r'<time[^>]+datetime=["\'](\d{4}-\d{2}-\d{2}(?:T[0-9:+-]+)?)', block, re.I)
    if datetime_match:
        published = datetime_match.group(1)
    if not title or not company:
        return None

    parts = [part.strip() for part in summary.split("•") if part.strip()]
    contracts = [part for part in parts if part.lower() in {"clt", "pj", "freelancer", "cooperado"}]
    state = ""
    if "•" in location:
        city_parts = [part.strip() for part in location.split("•") if part.strip()]
        if city_parts and len(city_parts[-1]) == 2:
            state = city_parts[-1].upper()
    categories = [part.strip() for part in meta.split("•")[:1] if part.strip()]
    tags = [clean(value) for value in re.findall(r'<a[^>]*class=["\'][^"\']*hashtag[^"\']*["\'][^>]*>(.*?)</a>', block, re.S | re.I)]
    low, high, currency = money(block)
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


def parse_page(markup):
    cards = re.split(r'(?=<div[^>]*class=["\'][^"\']*vaga-card[^"\']*["\'])', markup, flags=re.I)
    rows = [row for block in cards if (row := parse_card(block))]
    pages_match = re.search(r"Página\s+\d+\s+de\s+(\d+)", markup, re.I)
    pages = int(pages_match.group(1)) if pages_match else 1
    return rows, pages


def fetch_page(page):
    suffix = "" if page == 1 else f"?pagina={page}"
    return parse_page(get_text(f"{BASE_URL}{suffix}", timeout=40, retries=3))


def fetch_all():
    first_rows, total_pages = fetch_page(1)
    pages = {1: first_rows}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_page, page): page for page in range(2, total_pages + 1)}
        for future in concurrent.futures.as_completed(futures):
            page = futures[future]
            pages[page] = future.result()[0]
    unique = {}
    for page in range(1, total_pages + 1):
        for row in pages.get(page, []):
            unique[row["native_id"] or row["url"]] = row
    return list(unique.values()), total_pages


def add_published_times(conn, json_path):
    """Keep Nerdin's portal-provided clock in the public compact snapshot."""
    rows = conn.execute(
        "SELECT url, published_date FROM jobs WHERE source = ? AND published_date LIKE '%T%'",
        (SOURCE,),
    ).fetchall()
    times_by_url = {url: published for url, published in rows if url and published}
    if not times_by_url:
        return
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    source_codes = payload.get("dict", {}).get("source", [])
    jobs = payload.get("jobs", {})
    for index, url in enumerate(jobs.get("url", [])):
        source_index = jobs.get("src", [])[index]
        if source_codes[source_index] == SOURCE and url in times_by_url:
            jobs["pub"][index] = times_by_url[url]
    temporary = json_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(json_path)


def main():
    rows, pages = fetch_all()
    cutoff = storage.publication_cutoff(max_age_months=2)
    rows = [row for row in rows if not row["published_date"] or row["published_date"] >= cutoff]
    if not rows:
        raise SystemExit("Nerdin não retornou vagas recentes; a base não será alterada.")
    for row in rows:
        classify.classify(row)
    db_path = DASHBOARD / "data" / "jobs.db"
    json_path = ROOT / "docs" / "data" / "vagas.json"
    conn = storage.connect(str(db_path))
    storage.upsert(conn, rows)
    storage.prune(conn, keep_days=120, max_age_months=2)
    count, size_mb = storage.export_snapshot(
        conn, str(json_path), fresh_days=3, max_age_months=2,
        source_counts={SOURCE: len(rows)}, failed_sources=[]
    )
    add_published_times(conn, json_path)
    conn.close()
    print(f"Nerdin: {len(rows)} vagas recentes em {pages} páginas.")
    print(f"Painel: {count} vagas · {size_mb:.2f} MB.")


if __name__ == "__main__":
    main()
