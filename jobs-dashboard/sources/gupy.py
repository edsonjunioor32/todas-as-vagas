# -*- coding: utf-8 -*-
"""Gupy (Brazil) — public JSON endpoint, no key.

Adapted from the user's fetch_gupy_jobs_lote4.py. The profile/adherence filtering
is intentionally dropped: this project keeps every job and only classifies it.
Endpoint: employability-portal.gupy.io/api/v1/jobs?jobName=&limit=&offset=
"""
import json
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from ._http import get_json, get_text
from ._common import strip_html, iso_date, work_model_label, job

API = "https://employability-portal.gupy.io/api/v1/jobs"
HEADERS = {"Origin": "https://portal.gupy.io", "Referer": "https://portal.gupy.io/"}

# A broad sweep of the Brazilian market — not tuned to any single profile.
TERMS = [
    "analista de dados", "engenheiro de dados", "analista de bi", "business intelligence",
    "data analyst", "data engineer", "data science", "cientista de dados",
    "desenvolvedor", "engenheiro de software", "programador", "backend", "frontend",
    "product manager", "produto", "designer", "ux",
    "marketing", "growth", "vendas", "comercial", "sdr",
    "financeiro", "contábil", "controladoria", "rh", "recursos humanos",
    "customer success", "suporte", "atendimento", "operações", "logística",
    "estágio", "jovem aprendiz", "analista", "coordenador", "gerente",
]

PAGE = 100                       # the endpoint accepts up to 100/page
MAX_OFFSET = 400                 # offset genuinely advances → 5 pages of 100 per term
MONITORED_CAREER_PAGES = (
    "https://voxtecnologia.gupy.io/",
)
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.I | re.S,
)


def _api_row(item):
    jid = item.get("id")
    remote = bool(item.get("isRemoteWork"))
    skills = [
        value.get("name", "") if isinstance(value, dict) else str(value)
        for value in (item.get("skills") or [])
    ]
    return job(
        "gupy", jid,
        title=item.get("name", ""),
        company=item.get("careerPageName", ""),
        url=item.get("jobUrl", ""),
        work_model=work_model_label(remote, item.get("workplaceType")),
        city=item.get("city", "") or "",
        state=item.get("state", "") or "",
        country="BR", market="BR",
        published_date=iso_date(item.get("publishedDate")),
        expires_date=iso_date(item.get("applicationDeadline")),
        skills=[value for value in skills if value],
        description=strip_html(item.get("description", "")),
    )


def _fetch_term(term):
    q = urllib.parse.quote(term)
    out = []
    for offset in range(0, MAX_OFFSET + 1, PAGE):
        url = f"{API}?jobName={q}&limit={PAGE}&offset={offset}"
        data = get_json(url, headers=HEADERS, timeout=35).get("data", [])
        out.extend(_api_row(item) for item in data)
        if len(data) < PAGE:
            break
        time.sleep(0.15)
    return out


def _career_page_rows(page_url):
    """Read the small active-job catalog embedded in a monitored Gupy page."""
    html = get_text(page_url, timeout=30)
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError(f"Gupy career page without __NEXT_DATA__: {page_url}")
    props = json.loads(match.group(1)).get("props", {}).get("pageProps", {})
    company = str((props.get("careerPage") or {}).get("name") or "").strip()
    base_url = page_url.rstrip("/")
    rows = []
    for item in props.get("jobs") or []:
        jid = item.get("id")
        if not jid:
            continue
        workplace = item.get("workplace") or {}
        address = workplace.get("address") or {}
        rows.append(job(
            "gupy", jid,
            title=item.get("title", ""),
            company=company,
            url=f"{base_url}/jobs/{jid}?jobBoardSource=gupy_public_page",
            work_model=work_model_label(None, workplace.get("workplaceType")),
            city=address.get("city", "") or "",
            state=address.get("state", "") or "",
            country="BR", market="BR",
            categories=[str(item.get("department") or "").strip()],
        ))
    return rows


def _fetch_exact_job(row):
    """Enrich a monitored job without paging through the 80k-job catalog."""
    title = urllib.parse.quote(row.get("title") or "")
    url = f"{API}?jobName={title}&limit={PAGE}&offset=0"
    data = get_json(url, headers=HEADERS, timeout=35).get("data", [])
    native_id = str(row.get("native_id") or "")
    for item in data:
        if str(item.get("id") or "") == native_id:
            return _api_row(item)
    return row


def _monitored_pages():
    configured = os.environ.get("GUPY_MONITORED_PAGES")
    if configured is None:
        return MONITORED_CAREER_PAGES
    return tuple(value.strip() for value in configured.split(",") if value.strip())


def fetch():
    # Bounded concurrency cuts the broad sweep time without flooding the API.
    limit = int(os.environ.get("GUPY_MAX_TERMS") or len(TERMS))
    workers = min(max(1, int(os.environ.get("GUPY_WORKERS") or 4)), 6)
    unique = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_fetch_term, term): term for term in TERMS[:limit]}
        for future in as_completed(futures):
            for row in future.result():
                unique[str(row.get("native_id") or row.get("url"))] = row

    # A monitored career page costs one lightweight request and exposes old jobs
    # that remain active but fall outside the global search's first 500 matches.
    for page_url in _monitored_pages():
        try:
            page_rows = _career_page_rows(page_url)
        except Exception as error:
            print(f"    [gupy monitor] {page_url} indisponível: {str(error)[:100]}")
            continue
        for row in page_rows:
            key = str(row.get("native_id") or row.get("url"))
            if key in unique:
                continue
            try:
                row = _fetch_exact_job(row)
            except Exception as error:
                print(f"    [gupy monitor] vaga {key} sem enriquecimento: {str(error)[:100]}")
            unique[key] = row
    return list(unique.values())
