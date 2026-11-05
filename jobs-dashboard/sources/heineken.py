# -*- coding: utf-8 -*-
"""Public Brazilian vacancies from HEINEKEN's server-rendered careers site."""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from ._common import job, work_model_label
from ._http import get_text


BASE_URL = "https://careers.theheinekencompany.com"
LISTING_URL = (
    f"{BASE_URL}/Job-Listing?"
    "field_location_country_code_1%5B0%5D=BR&operatings_company%5B0%5D=289"
)
SOURCE = "heineken"
MAX_PAGES = 100
CARD_CLASS = "job-list-item"
FIELD_CLASSES = {
    "job-title": "title",
    "job-operating-company": "company",
    "job-description": "department",
    "nation": "location",
}
SLUG_RE = re.compile(r"^[^/?#]+$")


def _clean(value):
    return " ".join(str(value or "").split())


class _ListingParser(HTMLParser):
    """Extract cards and the server-provided ``Show more`` link."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.next_href = ""
        # Track only div nesting.  The source markup has unclosed void tags
        # (notably img), so HTMLParser's generic element depth is not reliable
        # for detecting the end of a card.
        self._div_depth = 0
        self._card = None
        self._card_div_depth = None
        self._fields = []
        self._started_fields = set()

    @staticmethod
    def _classes(attrs):
        return set((dict(attrs).get("class") or "").split())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "div":
            self._div_depth += 1

        if tag == "a" and "next" in {
            value.casefold() for value in (attrs.get("rel") or "").split()
        }:
            self.next_href = attrs.get("href") or ""

        if tag == "div" and self._card is None and CARD_CLASS in classes:
            self._card = {
                "href": "",
                "click_id": "",
                "title": [],
                "company": [],
                "department": [],
                "location": [],
            }
            self._card_div_depth = self._div_depth
            self._fields = []

        if self._card is None:
            return

        if tag == "a" and self._in_field("title"):
            href = attrs.get("href") or ""
            if not self._card["href"] and href:
                self._card["href"] = href
            if not self._card["click_id"]:
                self._card["click_id"] = _clean(attrs.get("click-id"))

        field = next((FIELD_CLASSES[name] for name in classes if name in FIELD_CLASSES), None)
        if field:
            if field == "company" and field in self._started_fields:
                return
            self._started_fields.add(field)
            self._fields.append((field, self._div_depth))

    def handle_data(self, data):
        if self._card is None:
            return
        for field, _depth in self._fields:
            self._card[field].append(data)

    def handle_endtag(self, tag):
        if tag != "div":
            return
        if self._card is not None:
            self._fields = [
                item for item in self._fields if item[1] != self._div_depth
            ]
            if self._div_depth == self._card_div_depth:
                self._finish_card()
        self._div_depth = max(0, self._div_depth - 1)

    def _in_field(self, field):
        return any(name == field for name, _depth in self._fields)

    def _finish_card(self):
        self.cards.append(
            {
                "href": self._card["href"],
                "click_id": _clean(self._card["click_id"]),
                "title": _clean(" ".join(self._card["title"])),
                "company": _clean(" ".join(self._card["company"])),
                "department": _clean(" ".join(self._card["department"])),
                "location": _clean(" ".join(self._card["location"])),
            }
        )
        self._card = None
        self._card_div_depth = None
        self._fields = []
        self._started_fields = set()


def _parse(markup):
    parser = _ListingParser()
    parser.feed(markup or "")
    parser.close()
    return parser.cards, parser.next_href


def _job_url(href):
    url = urljoin(BASE_URL, str(href or "").strip())
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != urlsplit(BASE_URL).netloc
        or not parsed.path.lower().startswith("/job/")
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("HEINEKEN retornou uma URL de vaga inválida")
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not slug or not SLUG_RE.fullmatch(slug):
        raise RuntimeError("HEINEKEN retornou uma vaga sem identificador")
    return url, slug


def _next_url(current_url, href):
    if not href:
        return ""
    url = urljoin(current_url, href)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != urlsplit(BASE_URL).netloc
        or parsed.path.rstrip("/").lower() != "/job-listing"
        or parsed.fragment
    ):
        raise RuntimeError("HEINEKEN retornou uma paginação fora do catálogo oficial")
    return url


def _location_parts(raw):
    parts = [part.strip() for part in str(raw or "").split(",") if part.strip()]
    city = parts[0] if parts else ""
    if city.casefold() in {"remote", "remoto", "hybrid", "híbrido", "hibrido"}:
        city = "Brasil"
    return city


def _normalize(card):
    if not isinstance(card, dict):
        raise RuntimeError("HEINEKEN retornou um card inválido")
    title = _clean(card.get("title"))
    company = _clean(card.get("company"))
    department = _clean(card.get("department"))
    location = _clean(card.get("location"))
    if not title or not company or not department or not location:
        raise RuntimeError("HEINEKEN retornou um card sem campos obrigatórios")

    url, slug = _job_url(card.get("href"))
    native_id = _clean(card.get("click_id")) or slug
    if not native_id:
        raise RuntimeError("HEINEKEN retornou uma vaga sem identificador")
    categories = []
    for value in (department, "Heineken"):
        if value and value not in categories:
            categories.append(value)

    return job(
        SOURCE,
        native_id,
        title,
        company,
        url,
        work_model=work_model_label(raw=f"{title} {location}"),
        city=_location_parts(location),
        country="BR",
        market="BR",
        categories=categories,
        published_date="",
    )


def fetch():
    """Fetch all public Brazilian cards, following the official next link."""
    url = LISTING_URL
    visited = set()
    unique = {}
    for _page_number in range(MAX_PAGES):
        if url in visited:
            raise RuntimeError("HEINEKEN repetiu uma página de catálogo")
        visited.add(url)
        markup = get_text(url, headers={"Accept": "text/html"}, timeout=30, retries=3)
        cards, next_href = _parse(markup)
        if not cards:
            raise RuntimeError("HEINEKEN retornou uma página sem cards")
        for card in cards:
            row = _normalize(card)
            unique.setdefault(row["native_id"], row)
        next_url = _next_url(url, next_href)
        if not next_url:
            break
        url = next_url
    else:
        raise RuntimeError("HEINEKEN excedeu o limite defensivo de páginas")

    if not unique:
        raise RuntimeError("HEINEKEN não retornou vagas brasileiras")
    return list(unique.values())
