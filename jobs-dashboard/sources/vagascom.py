# -*- coding: utf-8 -*-
"""Public Brazilian vacancies indexed by the Vagas.com search page."""
from datetime import date, timedelta
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from ._common import job, strip_html, work_model_label
from ._http import get_text


ORIGIN = "https://www.vagas.com.br"
# /vagas/ currently redirects to Vagas.com's own corporate careers site. The
# general public job index is /vagas-de-buscar and links to /vagas/v<ID>/... .
JOBS_URL = f"{ORIGIN}/vagas-de-buscar?ordenar_por=mais_recentes"
PAGE_SIZE = 40
MAX_PAGES = 100
TIMEOUT_SECONDS = 30
RETRIES = 2
PAGE_CONTENT_ATTEMPTS = 2

DETAIL_RE = re.compile(r"^/vagas/v(\d+)(?:/[^/?#]*)?/?$", re.I)
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
STATE_CODES = frozenset({
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "RR", "SC", "SP", "SE", "TO",
})


class _ListingParser(HTMLParser):
    """Extract one normalized card at a time from the server-rendered listing."""

    VOID_TAGS = frozenset({
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    })
    TARGETS = {
        "emprVaga": "company",
        "nivelVaga": "seniority",
        "detalhes": "description",
        "vaga-local": "location",
        "data-publicacao": "published",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.total_pages = None
        self.next_url = ""
        self.current = None
        self.depth = 0
        self.ignored_depth = None
        self.captures = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())

        if self.current is None:
            if tag == "a" and attrs.get("id") == "maisVagas":
                self.next_url = attrs.get("data-url") or ""
                try:
                    self.total_pages = int(attrs.get("data-total") or "")
                except (TypeError, ValueError):
                    self.total_pages = None
            if tag != "li" or "vaga" not in classes:
                return
            self.current = {
                "native_id": "", "href": "", "title": "", "company": "",
                "seniority": "", "description": "", "location": "",
                "published": "",
            }
            self.depth = 0
            self.ignored_depth = None
            self.captures = []

        if tag not in self.VOID_TAGS:
            self.depth += 1
        if tag == "a" and "link-detalhes-vaga" in classes:
            self.current["href"] = attrs.get("href") or ""
            self.current["title"] = attrs.get("title") or ""
            native_id = attrs.get("data-id-vaga") or ""
            if native_id.isdigit():
                self.current["native_id"] = native_id
        if "tooltip-place" in classes:
            self.ignored_depth = self.depth
        if self.ignored_depth is None:
            for class_name, field in self.TARGETS.items():
                if class_name in classes:
                    self.captures.append((field, self.depth, []))

    def handle_data(self, data):
        if self.current is None or self.ignored_depth is not None:
            return
        for _field, _depth, parts in self.captures:
            parts.append(data)

    def handle_endtag(self, tag):
        if self.current is None or tag in self.VOID_TAGS:
            return
        if tag == "li" and self.depth == 1:
            self._finish_card()
            return
        if self.ignored_depth == self.depth:
            self.ignored_depth = None
        remaining = []
        for field, depth, parts in self.captures:
            if depth == self.depth:
                value = " ".join("".join(parts).split())
                if value and not self.current[field]:
                    self.current[field] = value
            else:
                remaining.append((field, depth, parts))
        self.captures = remaining
        self.depth -= 1

    def _finish_card(self):
        if self.current.get("href"):
            self.cards.append(self.current)
        self.current = None
        self.depth = 0
        self.ignored_depth = None
        self.captures = []


def _parse_listing(markup):
    parser = _ListingParser()
    parser.feed(markup or "")
    return parser.cards, parser.total_pages, parser.next_url


def _canonical_detail(card):
    href = str(card.get("href") or "").strip()
    absolute = urljoin(ORIGIN, href)
    parsed = urlsplit(absolute)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in {
        "www.vagas.com.br", "vagas.com.br",
    }:
        return None
    match = DETAIL_RE.fullmatch(parsed.path or "")
    if not match:
        return None
    native_id = match.group(1)
    return native_id, f"{ORIGIN}/vagas/v{native_id}{parsed.path.split('/v' + native_id, 1)[-1]}"


def _collection_window():
    """Use the catalog's exact local two-month publication cutoff."""
    from storage import local_today, publication_cutoff

    today = local_today()
    return today, publication_cutoff(today, max_age_months=2)


def _published_date(value, today=None):
    today = today or _collection_window()[0]
    raw = str(value or "").strip()
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", raw.casefold())
        if not unicodedata.combining(char)
    )
    if normalized == "hoje":
        return today.isoformat()
    if normalized == "ontem":
        return (today - timedelta(days=1)).isoformat()
    relative = re.search(r"\bha\s+(\d+)\s+(hora|horas|dia|dias|semana|semanas)\b", normalized)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        days = 0 if unit in {"hora", "horas"} else amount
        if unit in {"semana", "semanas"}:
            days *= 7
        return (today - timedelta(days=days)).isoformat()

    match = DATE_RE.search(raw)
    if not match:
        return ""
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _location(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    work_model = work_model_label(raw=text)
    text = re.sub(r"\b(?:remoto|remota|remote|home\s*office|h[ií]brido|h[ií]brida|hybrid|presencial|on[- ]?site)\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" ,-/")
    match = re.fullmatch(r"(.+?)\s*(?:/|,)\s*([A-Z]{2})", text)
    if match and match.group(2).upper() in STATE_CODES:
        return match.group(1).strip(), match.group(2).upper(), "BR", work_model or "on-site"
    if text.casefold() in {"brasil", "brazil"}:
        return "Brasil", "", "BR", work_model or "remote"
    if work_model == "remote" and not text:
        return "Brasil", "", "BR", work_model
    return text, "", "BR", work_model or ("on-site" if text else "")


def _levels(title, seniority):
    value = f"{title} {seniority}".casefold()
    result = []
    patterns = (
        ("Junior", r"\b(?:j[uú]nior|jr\.?|trainee|estagi[aá]ri[oa])\b"),
        ("Mid-level", r"\b(?:pleno|mid[- ]?level)\b"),
        ("Senior", r"\b(?:s[eê]nior|sr\.?|staff|principal)\b"),
        ("Leadership", r"\b(?:gerente|coordenador|coordenadora|head|diretor|diretora|lead)\b"),
    )
    for label, pattern in patterns:
        if re.search(pattern, value, re.I):
            result.append(label)
    return result


def _contract_types(text):
    value = str(text or "")
    patterns = (
        ("CLT", r"\bCLT\b"),
        ("PJ", r"\bPJ\b|pessoa jur[ií]dica"),
        ("Estágio", r"\best[aá]gio\b|estagi[aá]ri[oa]"),
        ("Temporário", r"\btempor[aá]ri[oa]\b"),
    )
    return [label for label, pattern in patterns if re.search(pattern, value, re.I)]


def _normalize_card(card, today=None):
    canonical = _canonical_detail(card)
    title = str(card.get("title") or "").strip()
    if not canonical or not title:
        return None
    native_id, url = canonical
    description = strip_html(card.get("description") or "")
    description = re.sub(r"^Descri[cç][aã]o\s*:\s*", "", description, flags=re.I).strip()
    city, state, country, work_model = _location(card.get("location"))
    company = str(card.get("company") or "").strip() or "Confidencial"
    contract_types = _contract_types(f"{title} {description}")
    return job(
        "vagascom", native_id, title, company, url,
        work_model=work_model,
        city=city,
        state=state,
        country=country,
        market="BR",
        published_date=_published_date(card.get("published"), today=today),
        description=description,
        levels=_levels(title, card.get("seniority")),
        contract_types=contract_types,
        pcd=bool(re.search(r"\bPCD\b|pessoa com defici[eê]ncia", f"{title} {description}", re.I)),
    )


def _page_url(next_url, page):
    parsed = urlsplit(urljoin(ORIGIN, next_url))
    query = parse_qsl(parsed.query, keep_blank_values=True)
    replaced = False
    normalized = []
    for key, value in query:
        # The site's "load more" URL injects q=buscar, which is a search
        # keyword and narrows later pages instead of continuing the full list.
        if key == "q":
            continue
        if key == "pagina":
            if not replaced:
                normalized.append((key, str(page)))
                replaced = True
        else:
            normalized.append((key, value))
    if not replaced:
        normalized.append(("pagina", str(page)))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(normalized), ""))


def _validated_page(url, page_number, page_limit=None):
    """Retry short intermediate responses instead of accepting a partial page."""
    last_count = 0
    for _attempt in range(PAGE_CONTENT_ATTEMPTS):
        markup = get_text(url, timeout=TIMEOUT_SECONDS, retries=RETRIES)
        cards, reported_limit, next_url = _parse_listing(markup)
        last_count = len(cards)
        effective_limit = page_limit or reported_limit
        intermediate = effective_limit is not None and page_number < effective_limit
        if not cards:
            if page_limit is None and not intermediate:
                return [], effective_limit, next_url
            continue
        if intermediate and len(cards) != PAGE_SIZE:
            continue
        if next_url and len(cards) < PAGE_SIZE:
            continue
        return cards, effective_limit, next_url
    raise RuntimeError(
        f"Vagas.com retornou página incompleta ({page_number}: {last_count} cartões)"
    )


def _normalize_page(cards, today, cutoff, previous_date):
    dates = [_published_date(card.get("published"), today=today) for card in cards]
    if not dates or any(not value for value in dates):
        raise RuntimeError("Vagas.com retornou cartão sem data de publicação reconhecível")
    if any(dates[index] < dates[index + 1] for index in range(len(dates) - 1)):
        raise RuntimeError("Vagas.com não manteve a ordenação por data mais recente")
    if previous_date and dates[0] > previous_date:
        raise RuntimeError("a paginação do Vagas.com voltou para datas mais recentes")

    rows = []
    for card, published in zip(cards, dates):
        if published < cutoff:
            return rows, dates[-1], True
        row = _normalize_card(card, today=today)
        if not row:
            raise RuntimeError("Vagas.com retornou cartão sem link ou título válidos")
        rows.append(row)
    return rows, dates[-1], False


def fetch():
    """Collect newest postings only, stopping at the catalog's two-month cutoff."""
    today, cutoff = _collection_window()
    first_cards, page_limit, next_url = _validated_page(JOBS_URL, 1)
    if not first_cards:
        raise RuntimeError("Vagas.com não retornou cartões públicos reconhecíveis")
    if page_limit is not None and (page_limit < 1 or page_limit > MAX_PAGES):
        raise RuntimeError(f"quantidade de páginas inesperada no Vagas.com: {page_limit}")

    rows = {}
    previous_date = ""
    page_number = 1
    cards = first_cards
    pagination_template = next_url
    while True:
        page_rows, previous_date, reached_cutoff = _normalize_page(
            cards, today, cutoff, previous_date
        )
        for row in page_rows:
            rows[row["native_id"]] = row
        if reached_cutoff:
            break
        if page_limit is not None and page_number >= page_limit:
            break
        if not pagination_template:
            break
        if page_number >= MAX_PAGES:
            raise RuntimeError(
                f"Vagas.com não alcançou o corte de publicação após {MAX_PAGES} páginas"
            )

        page_number += 1
        cards, _reported_limit, _reported_next = _validated_page(
            _page_url(pagination_template, page_number), page_number, page_limit
        )
        if not cards:
            if page_limit is not None and page_number < page_limit:
                raise RuntimeError(
                    f"Vagas.com retornou página vazia antes do fim ({page_number})"
                )
            break

    if not rows:
        raise RuntimeError("Vagas.com não retornou vagas dentro da janela de publicação")
    return list(rows.values())
