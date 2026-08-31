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


class PublicCards(HTMLParser):
    """Parse one Recrutei listing card, including sibling location/model fields."""

    def __init__(self, matcher, base):
        super().__init__(convert_charrefs=True)
        self.matcher = matcher
        self.base = base
        self.card = None
        self.rows = []
        self._div_depth = 0
        self._card_depth = 0
        self._elements = []

    @staticmethod
    def _clean(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _finish_element(self, element):
        if not self.card:
            return
        value = self._clean(" ".join(element["text"]))
        if not value:
            return
        kind = element["kind"]
        if kind == "title":
            self.card["title"] = value
        elif kind == "company":
            self.card["company"] = value
        elif kind == "location":
            self.card["location"] = value
        elif kind == "badge":
            self.card["badges"].append(value)

    def _finish_card(self):
        if not self.card or not self.card.get("url"):
            self.card = None
            return
        self.card["parts"] = [
            self._clean(value) for value in self.card["parts"] if self._clean(value)
        ]
        self.rows.append(self.card)
        self.card = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(str(attributes.get("class") or "").split())
        if tag == "div":
            self._div_depth += 1
            if self.card is None and "list-grid-item" in classes:
                self.card = {
                    "groups": (),
                    "url": "",
                    "parts": [],
                    "title": "",
                    "company": "",
                    "location": "",
                    "badges": [],
                }
                self._card_depth = self._div_depth
        if self.card:
            href = attributes.get("href", "")
            match = self.matcher.search(href)
            if tag == "a" and match and not self.card["url"]:
                self.card["groups"] = match.groups()
                self.card["url"] = urljoin(self.base, href)
            kind = ""
            if tag == "a" and "job-title" in classes:
                kind = "title"
            elif tag == "p" and "text-muted" in classes and "f-14" in classes:
                kind = "company"
            elif (
                tag == "p" and "text-muted" in classes and "mb-1" in classes
                and "small" not in classes
            ):
                kind = "location"
            elif tag == "span" and any("badge" in item for item in classes):
                kind = "badge"
            if kind:
                self._elements.append({"tag": tag, "kind": kind, "text": []})

    def handle_endtag(self, tag):
        for index in range(len(self._elements) - 1, -1, -1):
            if self._elements[index]["tag"] == tag:
                element = self._elements.pop(index)
                self._finish_element(element)
                break
        if tag == "div":
            if self.card and self._div_depth == self._card_depth:
                self._finish_card()
            self._div_depth = max(0, self._div_depth - 1)

    def handle_data(self, data):
        if self.card and data.strip():
            self.card["parts"].append(data.strip())
            for element in self._elements:
                element["text"].append(data.strip())


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


def _public_location(value):
    parts = [part.strip() for part in re.split(r"\s*,\s*", str(value or "")) if part.strip()]
    if not parts or parts[0].casefold() in {"não informado", "nao informado"}:
        return "Brasil", ""
    if parts[-1].casefold() in {"brasil", "brazil"}:
        return parts[0], parts[-2] if len(parts) >= 3 else ""
    return parts[0], parts[1] if len(parts) >= 2 else ""


def _public_model(badges):
    labels = [str(value or "").strip() for value in badges if str(value or "").strip()]
    normalized = {value.casefold() for value in labels}
    if {"presencial ou remoto", "remoto ou presencial"} & normalized:
        return "hybrid"
    for value in labels:
        model = work_model_label(raw=value)
        if model:
            return model
    return ""


def _public_rows():
    """Collect the current public Recrutei feed, including card metadata."""
    parser = PublicCards(PUBLIC_CARD, PUBLIC)
    parser.feed(get_text(PUBLIC, timeout=40, retries=2))
    rows, seen = [], set()
    for card in parser.rows:
        groups = card.get("groups") or ()
        if len(groups) < 2:
            continue
        company_slug, vacancy_id = groups[:2]
        parts = card.get("parts") or []
        title = card.get("title") or (parts[0] if parts else "")
        if not title or title.casefold() in {"candidatar-se", "candidate-se"}:
            continue
        key = f"{company_slug}:{vacancy_id}"
        if key in seen:
            continue
        seen.add(key)
        company = card.get("company") or _company_name(company_slug)
        city, state = _public_location(card.get("location"))
        badges = card.get("badges") or []
        contract = next(
            (part for part in badges
             if not work_model_label(raw=part)
             and part.casefold() not in {"presencial ou remoto", "remoto ou presencial"}),
            "",
        )
        rows.append(job(
            "recrutei", key, title, company, card["url"],
            work_model=_public_model(badges) or work_model_label(raw=" ".join(parts)),
            city=city, state=state, country="BR", market="BR",
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
