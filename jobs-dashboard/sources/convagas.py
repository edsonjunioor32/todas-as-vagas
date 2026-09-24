# -*- coding: utf-8 -*-
"""Public vacancy boards hosted by Convagas/Convenia.

Convagas boards are Nuxt applications. Their server-rendered
NUXT_DATA payload contains the active positions, while each detail page
contains the full description. This adapter intentionally uses only public
HTML and keeps each tenant as an independent source.
"""
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, urlunsplit

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_text
from ._html import PublicPageParser, job_posting


DETAIL_RE = re.compile(r"/vaga/([A-Za-z0-9_-]{8,})(?:[/?#]|$)", re.I)
LEVEL_RE = re.compile(
    r"\b(j[uú]nior|jr\.?|pleno|mid(?:[- ]level)?|s[eê]nior|sr\.?|"
    r"especialista|lead|gerente|coordenador|supervisor|trainee)\b",
    re.I,
)
PCD_RE = re.compile(r"\bpcd\b|pessoa(?:s)?\s+com\s+defici", re.I)
NUXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>([\\s\\S]*?)</script>',
    re.I,
)


TARGETS = (
    ("syos", "https://syos.convagas.com.br/?depto=CS"),
    ("copytec", "https://copytec.convagas.com.br/"),
    ("sisloc", "https://sisloc.convagas.com.br/"),
    ("dreamexperience", "https://dreamexperience.convagas.com.br/"),
    ("itwheel", "https://itwheel.convagas.com.br/"),
    ("atitude", "https://atitude.convagas.com.br/"),
    ("entera", "https://carreirasentera.convagas.com.br/"),
    ("4redes", "https://4redes.convagas.com.br/"),
)


def _resolve_nuxt(markup):
    """Resolve Nuxt's compact reference-array payload into Python values."""
    match = NUXT_DATA_RE.search(markup or "")
    if not match:
        return None

    try:
        payload = json.loads(html.unescape(match.group(1)))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, list):
        return None

    memo = {}
    visiting = set()
    wrappers = {"Reactive", "ShallowReactive", "Set"}

    def resolve_index(index):
        if not isinstance(index, int) or index < 0 or index >= len(payload):
            return index
        if index in memo:
            return memo[index]
        if index in visiting:
            return None
        visiting.add(index)
        value = resolve(payload[index])
        visiting.remove(index)
        memo[index] = value
        return value

    def resolve(value):
        if isinstance(value, int):
            return resolve_index(value)
        if isinstance(value, list):
            if value and value[0] in wrappers:
                return [resolve(item) for item in value[1:]]
            return [resolve(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value

    return resolve_index(0)


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _payload_positions(markup):
    """Return company name and positions from a Convagas Nuxt payload."""
    root = _resolve_nuxt(markup)
    if root is None:
        return "", {}

    company = ""
    records = {}
    for value in _walk(root):
        if not isinstance(value, dict):
            continue
        positions = value.get("job_positions")
        if not isinstance(positions, list):
            continue
        company = str(value.get("company_name") or company).strip()
        for position in positions:
            if not isinstance(position, dict):
                continue
            native_id = str(position.get("id") or "").strip()
            if native_id:
                records[native_id] = dict(position)

    # On a detail page, the selected position is a second object outside the
    # company list and includes the description field.
    for value in _walk(root):
        if not isinstance(value, dict):
            continue
        native_id = str(value.get("id") or "").strip()
        if native_id and value.get("title") and (
            "description" in value or native_id in records
        ):
            merged = dict(records.get(native_id) or {})
            merged.update(value)
            records[native_id] = merged
    return company, records


def _fallback_records(markup):
    """Use JSON-LD when an upstream board changes its Nuxt payload shape."""
    posting = job_posting(markup or {})
    if not posting:
        return "", {}
    identifier = posting.get("identifier") or {}
    native_id = (
        identifier.get("value")
        if isinstance(identifier, dict)
        else identifier
    )
    native_id = str(native_id or "").strip()
    if not native_id:
        match = DETAIL_RE.search(str(posting.get("url") or ""))
        native_id = match.group(1) if match else ""
    if not native_id:
        return "", {}
    return "", {
        native_id: {
            "id": native_id,
            "title": posting.get("title") or "",
            "description": posting.get("description") or "",
            "initial_date": posting.get("datePosted") or "",
            "city_name": "",
            "state_name": "",
            "modality": "",
            "relationship_name": "",
        }
    }


def _extract_positions(markup):
    company, records = _payload_positions(markup)
    if records:
        return company, records
    return _fallback_records(markup)


def _base_url(list_url):
    parsed = urlsplit(list_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _detail_url(list_url, native_id):
    return f"{_base_url(list_url)}/vaga/{native_id}"


def _title_and_metadata(record):
    title = strip_html(str(record.get("title") or "")).strip()
    description = strip_html(str(record.get("description") or "")).strip()
    raw = f"{title} {description}"
    levels = list(dict.fromkeys(
        match.group(1).title() for match in LEVEL_RE.finditer(raw)
    ))
    department = str(record.get("department_name") or "").strip()
    relationship = str(record.get("relationship_name") or "").strip()
    categories = [value for value in (department, "Convagas") if value]
    contract_types = [relationship] if relationship else []
    return title, description, levels, categories, contract_types


def _to_row(source, list_url, company, record):
    native_id = str(record.get("id") or "").strip()
    title, description, levels, categories, contract_types = _title_and_metadata(record)
    if not native_id or not title:
        return None

    modality = str(record.get("modality") or "").strip()
    city = str(record.get("city_name") or "").strip()
    state = str(record.get("state_name") or "").strip()
    return job(
        source,
        native_id,
        title=title,
        company=company or source.title(),
        url=_detail_url(list_url, native_id),
        work_model=work_model_label(raw=modality),
        city=city,
        state=state,
        country="BR",
        market="BR",
        published_date=iso_date(record.get("initial_date")),
        description=description,
        levels=levels,
        categories=categories,
        contract_types=contract_types,
        pcd=bool(PCD_RE.search(f"{title} {description}")),
    )


def _collect_board(source, list_url):
    markup = get_text(
        list_url,
        headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
        timeout=45,
        retries=3,
    )
    company, records = _extract_positions(markup)
    if not records:
        parser = PublicPageParser()
        parser.feed(markup)
        if not any(DETAIL_RE.search(url) for url, _label in parser.anchors):
            raise RuntimeError(f"Convagas/{source} returned no public vacancy records")

    # Fetch detail pages for descriptions, but retain the list metadata if one
    # detail request is temporarily unavailable.
    detail_markup = {}
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(records)))) as pool:
        futures = {
            pool.submit(
                get_text,
                _detail_url(list_url, native_id),
                headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
                timeout=35,
                retries=2,
            ): native_id
            for native_id in records
        }
        for future in as_completed(futures):
            native_id = futures[future]
            try:
                detail_markup[native_id] = future.result()
            except Exception:
                continue

    rows = []
    for native_id, record in records.items():
        detail = detail_markup.get(native_id)
        if detail:
            detail_company, detail_records = _extract_positions(detail)
            detail_record = detail_records.get(native_id)
            if detail_record:
                merged = dict(record)
                merged.update(detail_record)
                record = merged
            company = detail_company or company
        row = _to_row(source, list_url, company, record)
        if row:
            rows.append(row)

    if not rows:
        raise RuntimeError(f"Convagas/{source} returned no readable vacancies")
    rows.sort(key=lambda row: row["native_id"])
    return rows


def fetch_syos():
    return _collect_board("syos", dict(TARGETS)["syos"])


def fetch_copytec():
    return _collect_board("copytec", dict(TARGETS)["copytec"])


def fetch_sisloc():
    return _collect_board("sisloc", dict(TARGETS)["sisloc"])


def fetch_dreamexperience():
    return _collect_board("dreamexperience", dict(TARGETS)["dreamexperience"])


def fetch_itwheel():
    return _collect_board("itwheel", dict(TARGETS)["itwheel"])


def fetch_atitude():
    return _collect_board("atitude", dict(TARGETS)["atitude"])


def fetch_entera():
    return _collect_board("entera", dict(TARGETS)["entera"])


def fetch_4redes():
    return _collect_board("4redes", dict(TARGETS)["4redes"])


FETCHERS = {
    name: globals()[f"fetch_{name}"] for name, _url in TARGETS
}
