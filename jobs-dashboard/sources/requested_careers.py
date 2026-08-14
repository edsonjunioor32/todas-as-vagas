# -*- coding: utf-8 -*-
"""Company career pages requested for the Brazilian vacancy collection."""
import html
import re
from urllib.parse import urljoin

from ._common import job, strip_html, work_model_label
from ._http import get_text

DOCUSIGN = "https://careers.docusign.com/careers-home/jobs?locations=Sao%20Paulo,S%C3%A3o%20Paulo,Brazil%7C,,Brazil&page={page}"
DBC = "https://vagas.dbccompany.com.br/vagas"
ANCHOR_RE = re.compile(r'<a[^>]+href=["\']([^"\']*(?:/jobs/|/vagas/)[^"\']*)["\'][^>]*>([\s\S]*?)</a>', re.I)


def _links(url):
    page = get_text(url, timeout=35, retries=2)
    seen = set()
    for href, label in ANCHOR_RE.findall(page):
        href = html.unescape(href).strip()
        label = strip_html(html.unescape(label))
        absolute = urljoin(url, href)
        if absolute and label and absolute not in seen:
            seen.add(absolute)
            yield absolute, label


def fetch_docusign():
    rows, seen = [], set()
    # The official search URL is already restricted to Brazil; use two pages
    # to cover the current result set without an unbounded crawl.
    for page in (1, 2):
        for url, title in _links(DOCUSIGN.format(page=page)):
            native_id = url.rstrip("/").split("/")[-1].split("?")[0]
            if native_id in seen:
                continue
            seen.add(native_id)
            rows.append(job(
                "docusign", native_id, title=title, company="DocuSign", url=url,
                work_model=work_model_label(raw=title), city="Brasil",
                country="BR", market="BR", categories=["Carreiras DocuSign"],
            ))
    return rows


def fetch_dbccompany():
    rows = []
    for url, title in _links(DBC):
        native_id = url.rstrip("/").split("/")[-1].split("?")[0]
        rows.append(job(
            "dbccompany", native_id, title=title, company="DBC Company", url=url,
            work_model=work_model_label(raw=title), city="Brasil",
            country="BR", market="BR", categories=["Carreiras DBC"],
        ))
    return rows
