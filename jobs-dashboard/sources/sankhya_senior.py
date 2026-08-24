# -*- coding: utf-8 -*-
"""Public career listings requested for Sankhya and Senior Sistemas."""
import re
from urllib.parse import urlsplit

from ._common import job, work_model_label
from ._rendered import rendered_links

SANKHYA = "https://oportunidades.mindsight.com.br/sankhya"
SENIOR = "https://vemprasenior.portaldetalentos.senior.com.br/jobs"


def _rows(url, pattern, source, company):
    rows, seen = [], set()
    for href, raw_title in rendered_links(url, pattern):
        parsed = urlsplit(href)
        key = parsed.path.rstrip("/")
        title = re.sub(r"\s+", " ", raw_title).strip()[:240]
        if not key or not title or key in seen:
            continue
        seen.add(key)
        rows.append(job(
            source, key, title, company, href, country="BR", market="BR",
            city="Brasil", work_model=work_model_label(raw=title),
        ))
    if not rows:
        raise RuntimeError(f"{company} returned no recognizable public vacancy cards")
    return rows


def fetch_sankhya():
    # Mindsight renders its vacancy cards client-side.
    return _rows(SANKHYA, r"/sankhya/\\d+(?:[/?#]|$)", "sankhya", "Sankhya")


def fetch_senior():
    # Senior's current portal can link directly to the JobConvo application.
    return _rows(SENIOR, r"(?:jobconvo|/jobs?/)", "senior", "Senior Sistemas")
