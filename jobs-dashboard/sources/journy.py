# -*- coding: utf-8 -*-
"""Public Journy careers catalogue.

The careers page is a Next.js/AWS Amplify application. Its public vacancy
records are embedded in the HTML/RSC response, so this adapter does not call
the portal's Supabase project directly.
"""
import html as html_lib
import json
import re
import uuid
from html.parser import HTMLParser
from urllib.parse import urlparse

from ._common import job, strip_html, work_model_label
from ._http import get_text


CAREERS_URL = "https://main.d3mg4gpkl052zo.amplifyapp.com/carreiras"
DETAIL_URL = CAREERS_URL + "/{0}"
SOURCE = "journy"
_RSC_MARKER = '"vagas"'
_SCRIPT_RE = re.compile(
    r'''<script[^>]*type=["']application/json["'][^>]*>(.*?)</script>''',
    re.I | re.S,
)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)


class _DescriptionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self._depth == 0 and attrs.get("data-testid") == "vaga-descricao":
            self._depth = 1
        elif self._depth:
            self._depth += 1

    def handle_startendtag(self, tag, attrs):
        if self._depth and self._depth > 1:
            return

    def handle_endtag(self, tag):
        if self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth:
            self._parts.append(data)


def _description(markup):
    """Extract only the public description container from a detail page."""
    parser = _DescriptionParser()
    parser.feed(markup or "")
    parser.close()
    return strip_html(" ".join(parser._parts))


def _walk_json(value):
    if isinstance(value, dict):
        vacancies = value.get("vagas")
        if isinstance(vacancies, list):
            yield vacancies
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _extract_vacancies(markup):
    """Extract the RSC/JSON vacancy array without depending on private APIs."""
    page = html_lib.unescape(markup or "")
    candidates = [page, page.replace(r"\"", '"')]
    decoder = json.JSONDecoder()

    for candidate in candidates:
        for match in re.finditer(_RSC_MARKER, candidate):
            start = candidate.find("[", match.end())
            if start < 0:
                continue
            try:
                value, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, list):
                return value

    for script in _SCRIPT_RE.findall(page):
        try:
            parsed = json.loads(script)
        except (TypeError, ValueError):
            continue
        for vacancies in _walk_json(parsed):
            return vacancies

    raise RuntimeError("Journy não expôs a lista pública de vagas no HTML/RSC")


def _uuid(value):
    text = str(value or "").strip()
    if not _UUID_RE.fullmatch(text):
        raise RuntimeError(f"Journy expôs id inválido: {text!r}")
    return str(uuid.UUID(text))


def _unique_rows(rows):
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Journy retornou uma lista pública vazia")
    unique = {}
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError("Journy retornou um registro que não é objeto")
        native_id = _uuid(item.get("id"))
        title = str(item.get("title") or "").strip()
        company = str(item.get("contratante_name") or "").strip()
        if not title or not company:
            raise RuntimeError(f"Journy expôs vaga incompleta: {native_id}")
        previous = unique.get(native_id)
        if previous and (
            str(previous.get("title") or "").strip() != title
            or str(previous.get("contratante_name") or "").strip() != company
        ):
            raise RuntimeError(f"Journy expôs dados conflitantes para {native_id}")
        unique[native_id] = {**item, "id": native_id}
    return list(unique.values())


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"Journy expôs salário inválido: {value!r}") from error


def _normalize(item, description=""):
    native_id = _uuid(item.get("id"))
    title = str(item.get("title") or "").strip()
    company = str(item.get("contratante_name") or "").strip()
    if not title or not company:
        raise RuntimeError(f"Journy expôs vaga incompleta: {native_id}")

    location_type = str(item.get("location_type") or "").strip().casefold()
    location_label = str(item.get("location_label") or "").strip()
    remote = location_type == "remote"
    city = "Brasil" if remote else ""
    skills = []
    for key in ("required_skills", "desired_skills"):
        values = item.get(key) or []
        if not isinstance(values, list):
            raise RuntimeError(f"Journy expôs {key} em formato inválido: {native_id}")
        skills.extend(str(value).strip() for value in values if str(value).strip())
    skills = list(dict.fromkeys(skills))

    url = DETAIL_URL.format(native_id)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != urlparse(CAREERS_URL).netloc:
        raise RuntimeError(f"URL pública inválida para Journy: {url}")

    seniority = str(item.get("seniority_label") or "").strip()
    contract = str(item.get("contract_type_label") or "").strip()
    return job(
        SOURCE,
        native_id,
        title=title,
        company=company,
        url=url,
        work_model=work_model_label(remote_flag=remote, raw=location_label),
        city=city,
        country="BR",
        market="BR",
        salary_min=_number(item.get("min_salary")),
        salary_max=_number(item.get("max_salary")),
        salary_currency="BRL" if (item.get("min_salary") or item.get("max_salary")) else None,
        published_date="",
        description=strip_html(description),
        skills=skills[:20],
        levels=[seniority] if seniority else [],
        categories=["Journy"],
        contract_types=[contract] if contract else [],
    )


def _validate_rows(rows):
    if not rows:
        raise RuntimeError("Journy retornou zero vagas")
    seen = set()
    for row in rows:
        native_id = str(row.get("native_id") or "").strip()
        url = str(row.get("url") or "").strip()
        if not _UUID_RE.fullmatch(native_id):
            raise RuntimeError(f"Journy retornou native_id inválido: {native_id!r}")
        if native_id in seen:
            raise RuntimeError(f"Journy retornou native_id duplicado: {native_id}")
        if url != DETAIL_URL.format(native_id):
            raise RuntimeError(f"Journy retornou URL inválida: {url!r}")
        if row.get("source") != SOURCE:
            raise RuntimeError(f"Journy marcou fonte inválida: {row.get('source')!r}")
        seen.add(native_id)
    return rows


def fetch():
    listing = get_text(CAREERS_URL, timeout=45, retries=3)
    raw = _unique_rows(_extract_vacancies(listing))
    rows = []
    for item in raw:
        description = ""
        try:
            description = _description(
                get_text(DETAIL_URL.format(item["id"]), timeout=30, retries=2)
            )
        except Exception as error:
            # Listing metadata remains public and complete even if one detail
            # page has a transient edge failure. Fit extraction will use the
            # published skills and the description when it is available.
            print(f"  Journy: detalhe {item['id']} indisponível ({error})")
        rows.append(_normalize(item, description))
    return _validate_rows(rows)
