# -*- coding: utf-8 -*-
"""Gupy (Brazil) — public JSON endpoint, no key.

Adapted from the user's fetch_gupy_jobs_lote4.py. The profile/adherence filtering
is intentionally dropped: this project keeps every job and only classifies it.
Endpoint: employability-portal.gupy.io/api/v1/jobs?jobName=&limit=&offset=
"""
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from ._http import get_json
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


def _fetch_term(term):
    q = urllib.parse.quote(term)
    out = []
    for offset in range(0, MAX_OFFSET + 1, PAGE):
        url = f"{API}?jobName={q}&limit={PAGE}&offset={offset}"
        data = get_json(url, headers=HEADERS, timeout=35).get("data", [])
        for j in data:
            jid = j.get("id")
            remote = bool(j.get("isRemoteWork"))
            skills = [s.get("name", "") if isinstance(s, dict) else str(s)
                      for s in (j.get("skills") or [])]
            out.append(job(
                "gupy", jid,
                title=j.get("name", ""),
                company=j.get("careerPageName", ""),
                url=j.get("jobUrl", ""),
                work_model=work_model_label(remote, j.get("workplaceType")),
                city=j.get("city", "") or "",
                state=j.get("state", "") or "",
                country="BR", market="BR",
                published_date=iso_date(j.get("publishedDate")),
                skills=[s for s in skills if s],
                description=strip_html(j.get("description", "")),
            ))
        if len(data) < PAGE:
            break
        time.sleep(0.15)
    return out


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
    return list(unique.values())
