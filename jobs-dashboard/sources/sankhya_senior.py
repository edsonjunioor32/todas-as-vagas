# -*- coding: utf-8 -*-
"""Public career listings requested for Sankhya and Senior Sistemas."""
import re
from urllib.parse import urljoin

from ._common import job, strip_html, work_model_label
from ._http import get_text

SANKHYA = "https://oportunidades.mindsight.com.br/sankhya"
SENIOR = "https://vemprasenior.portaldetalentos.senior.com.br/jobs"


def _cards(page, base, pattern, source, company):
    rows, seen = [], set()
    for href, raw_title in re.findall(pattern, page, re.I):
        url = urljoin(base, href)
        title = strip_html(raw_title)
        key = url.rstrip("/")
        if not title or key in seen:
            continue
        seen.add(key)
        rows.append(job(source, key, title, company, url, country="BR", market="BR",
                        city="Brasil", work_model=work_model_label(raw=title)))
    if not rows:
        raise RuntimeError(f"{company} returned no recognizable public vacancy cards")
    return rows


def fetch_sankhya():
    page = get_text(SANKHYA, timeout=40, retries=2)
    return _cards(page, SANKHYA,
        r'<a[^>]+href=["\']([^"\']*/sankhya/\d+[^"\']*)["\'][^>]*>([\s\S]*?)</a>',
        "sankhya", "Sankhya")


def fetch_senior():
    page = get_text(SENIOR, timeout=40, retries=2)
    return _cards(page, SENIOR,
        r'<a[^>]+href=["\']([^"\']*(?:jobconvo|/jobs/)[^"\']*)["\'][^>]*>([\s\S]*?)</a>',
        "senior", "Senior Sistemas")
