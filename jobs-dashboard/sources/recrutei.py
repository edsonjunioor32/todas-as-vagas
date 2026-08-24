# -*- coding: utf-8 -*-
"""Configured public Recrutei career pages."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from ._common import job, work_model_label
from ._http import get_text

PAGES = {
    "full-sales-system": "Full Sales System",
    "singularis-rh": "Singularis RH",
    "singularis-rh/contratacaoacelerada": "Singularis RH",
    "rehva-tech": "Rehva Tech",
    "ataway-do-brasil": "Ataway do Brasil",
    "bm-vagas": "BM Vagas",
    "thera-consulting": "Thera Consulting",
    "fourhands-brasil": "Fourhands Brasil",
    "emiteai-solucoes-em-tecnologia": "Emiteai Soluções em Tecnologia",
    "grupo-regazzo": "Grupo Regazzo",
    "meirelespessoaseeducacao": "Meireles Pessoas e Educação",
    "luzcon-digital-ltda": "Luzcon Digital",
    "alpha-estagio": "Alpha Estágio",
    "3am-it-services-2": "3AM IT Services",
}
HOST = "https://jobs.recrutei.com.br"
PUBLIC = "https://empregos.recrutei.com.br/vagas"
CARD = re.compile(r"/([^/]+)/vacancy/(\d+)-", re.I)
PUBLIC_CARD = re.compile(r"/vaga/([^/]+)/(\d+)(?:-[^/?#]+)?", re.I)
CONTRACT = re.compile(r"^(?:CLT|PJ|CLT ou PJ|Estágio|Temporário|Pessoa Jurídica)$", re.I)


class Cards(HTMLParser):
    def __init__(self, matcher, base):
        super().__init__(convert_charrefs=True)
        self.matcher = matcher
        self.base = base
        self.card = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href", "")
        match = self.matcher.search(href)
        if tag == "a" and self.card is None and match:
            self.card = {"groups": match.groups(), "url": urljoin(self.base, href), "parts": []}

    def handle_endtag(self, tag):
        if tag == "a" and self.card:
            if self.card["parts"]:
                self.rows.append(self.card)
            self.card = None

    def handle_data(self, data):
        if self.card and data.strip():
            self.card["parts"].append(data.strip())


def _company_name(slug):
    return {"digisystem": "Digisystem", "bm-vagas": "BM Vagas"}.get(
        slug, slug.replace("-", " ").title()
    )


def _public_rows():
    """Collect the current public Recrutei feed, including Digisystem."""
    parser = Cards(PUBLIC_CARD, PUBLIC)
    parser.feed(get_text(PUBLIC, timeout=40, retries=2))
    rows, seen = [], set()
    for card in parser.rows:
        company_slug, vacancy_id = card["groups"][:2]
        parts = card["parts"]
        title = parts[0]
        if not title or title.casefold() in {"candidatar-se", "candidate-se"}:
            continue
        key = f"{company_slug}:{vacancy_id}"
        if key in seen:
            continue
        seen.add(key)
        company = _company_name(company_slug)
        contract = next((part for part in parts[1:] if CONTRACT.match(part)), "")
        location = next(
            (part for part in parts[1:] if part not in {contract, company}
             and not part.casefold().startswith("publicada")),
            "Brasil",
        )
        rows.append(job(
            "recrutei", key, title, company, card["url"],
            work_model=work_model_label(raw=" ".join(parts)),
            city=location, country="BR", market="BR",
            contract_types=re.split(r"\s+ou\s+", contract, flags=re.I) if contract else [],
        ))
    return rows


def fetch():
    # Recrutei migrated active listings to empregos.recrutei.com.br. Keep the
    # configured legacy tenant pages as a compatibility fallback.
    out = {row["native_id"]: row for row in _public_rows()}
    for path, company in PAGES.items():
        parser = Cards(CARD, HOST)
        parser.feed(get_text(f"{HOST}/{path}", timeout=40, retries=2))
        for card in parser.rows:
            vacancy_id = card["groups"][1]
            parts = card["parts"]
            contract = next((part for part in parts[1:] if CONTRACT.match(part)), "")
            location = next((part for part in reversed(parts[1:]) if part != contract), "")
            key = f"{path}:{vacancy_id}"
            out[key] = job(
                "recrutei", key, parts[0], company, card["url"],
                work_model=work_model_label(raw=location), city=location,
                country="BR", market="BR",
                contract_types=re.split(r"\s+ou\s+", contract, flags=re.I) if contract else [],
            )
    if not out:
        raise RuntimeError("Recrutei returned no recognizable public vacancy cards")
    return list(out.values())
