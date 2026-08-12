# -*- coding: utf-8 -*-
"""Digisystem careers hosted on the public Recrutei listing."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from ._common import job, work_model_label
from ._http import get_text

BASE = "https://jobs.recrutei.com.br/digisystem"
VACANCY_RE = re.compile(r"/digisystem/vacancy/(\d+)-", re.I)
CONTRACT_RE = re.compile(r"^(?:CLT|PJ|CLT ou PJ|Estágio|Temporário)$", re.I)


class _VacancyParser(HTMLParser):
    """Read vacancy cards rendered in the public Recrutei HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag != "a" or self.current is not None:
            return
        href = dict(attrs).get("href") or ""
        match = VACANCY_RE.search(href)
        if match:
            self.current = {"native_id": match.group(1), "url": urljoin(BASE, href), "parts": []}

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            parts = [part.strip() for part in self.current["parts"] if part.strip()]
            if parts:
                self.current["parts"] = parts
                self.rows.append(self.current)
            self.current = None

    def handle_data(self, data):
        if self.current is not None and data.strip():
            self.current["parts"].append(data)


def _contracts(value):
    return [part.strip() for part in re.split(r"\s+ou\s+", value, flags=re.I) if part.strip()]


def _normalize(card):
    parts = card["parts"]
    title = parts[0]
    contract = next((part for part in parts[1:] if CONTRACT_RE.match(part)), "")
    location = next((part for part in reversed(parts[1:]) if part != contract), "")
    return job(
        "digisystem",
        card["native_id"],
        title=title,
        company="Digisystem",
        url=card["url"],
        work_model=work_model_label(raw=location),
        city=location,
        country="BR",
        market="BR",
        contract_types=_contracts(contract),
    )


def fetch():
    parser = _VacancyParser()
    parser.feed(get_text(BASE, timeout=40, retries=3))
    parser.close()

    unique = {}
    for card in parser.rows:
        row = _normalize(card)
        unique[row["native_id"]] = row
    return list(unique.values())
