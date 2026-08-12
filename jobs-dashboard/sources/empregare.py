# -*- coding: utf-8 -*-
"""Empregare — public, key-free vacancies API.

Official endpoint:
  GET https://www.empregare.com/api/{culture}/vagas/buscar-novo

The first page reports the total page count. Remaining pages are downloaded
with bounded concurrency so a complete catalogue refresh stays practical while
remaining gentle on the public service.
"""
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from ._common import iso_date, job, split_location, work_model_label
from ._http import get_json

API = "https://www.empregare.com/api/pt-br/vagas/buscar-novo"
PAGE_SIZE = 100


def _url(page):
    query = urllib.parse.urlencode({
        "Pagina": page,
        "ItensPagina": PAGE_SIZE,
        "Ordenacao": 0,
        "DataPublicacao": 0,
    })
    return f"{API}?{query}"


def _page(page):
    payload = get_json(_url(page), timeout=40, retries=3)
    if not payload.get("sucesso"):
        raise RuntimeError(f"Empregare returned sucesso=false on page {page}")
    model = payload.get("model") or {}
    return model, model.get("dados") or []


def _money(value):
    text = str(value or "")
    numbers = re.findall(r"\d[\d.]*,\d{2}|\d+(?:[.,]\d+)?", text)
    parsed = []
    for raw in numbers:
        try:
            if "," in raw:
                parsed.append(float(raw.replace(".", "").replace(",", ".")))
            else:
                parsed.append(float(raw))
        except ValueError:
            continue
    if not parsed:
        return None, None, None
    currency = "BRL" if "R$" in text else None
    return min(parsed), max(parsed) if len(parsed) > 1 else None, currency


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "sim", "yes"}


def _normalize(item):
    locations = [str(x).strip() for x in (item.get("cidades") or []) if str(x).strip()]
    city, state, country = split_location(locations[0] if locations else "")
    # Empregare é um portal brasileiro; a ausência de cidade estruturada não
    # transforma a vaga em oportunidade global.
    market = "BR"

    tags = []
    for entry in item.get("tags") or []:
        if isinstance(entry, dict):
            value = entry.get("tag") or entry.get("nome")
        else:
            value = entry
        if value:
            tags.append(str(value).strip())

    salary_min, salary_max, salary_currency = _money(item.get("salario"))
    vacancy_id = item.get("id")
    raw_model = item.get("trabalhoRemotoTexto") or item.get("trabalhoRemoto") or ""
    return job(
        "empregare",
        vacancy_id,
        title=item.get("titulo", ""),
        company=item.get("empresa", ""),
        url=f"https://www.empregare.com/v{vacancy_id}",
        work_model=work_model_label(raw=raw_model),
        city=" · ".join(locations[:3]) or city,
        state=state,
        country=country,
        market=market,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        published_date=iso_date(item.get("dataCadastro") or item.get("timestamp")),
        expires_date=iso_date(item.get("dataExpiracao")),
        skills=tags[:8],
        description=item.get("chamada", "") or "",
        levels=[item.get("nivel", "")] if item.get("nivel") else [],
        categories=tags,
        pcd=_bool(item.get("pcd")),
        blind_selection=_bool(item.get("recrutamentoCego")),
    )


def fetch():
    first_model, first_rows = _page(1)
    total_pages = max(1, int(float(first_model.get("totalPaginas") or 1)))
    page_cap = int(os.environ.get("EMPREGARE_MAX_PAGES") or total_pages)
    total_pages = min(total_pages, max(1, page_cap))
    workers = min(max(1, int(os.environ.get("EMPREGARE_WORKERS") or 4)), 8)

    pages = {1: first_rows}
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_page, page): page for page in range(2, total_pages + 1)}
            for future in as_completed(futures):
                page = futures[future]
                _, rows = future.result()
                pages[page] = rows

    unique = {}
    for page in range(1, total_pages + 1):
        for item in pages.get(page, []):
            vacancy_id = item.get("id")
            if vacancy_id is not None:
                unique[str(vacancy_id)] = _normalize(item)
    return list(unique.values())
