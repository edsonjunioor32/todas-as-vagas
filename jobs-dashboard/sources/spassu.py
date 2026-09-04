# -*- coding: utf-8 -*-
"""Brazilian public vacancies from Spassu's Zoho Recruit career site."""
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_text
from ._html import PublicPageParser, job_posting
from ._rendered import rendered_links


BASE_URL = "https://spassu.zohorecruit.com"
BOARD_URL = f"{BASE_URL}/jobs/Careers"
DETAIL_RE = re.compile(r"/jobs/careers/(\d+)(?:/[^/?#]*)?", re.I)
ANCHOR_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']*/jobs/Careers/\d+[^"\']*)["\'][^>]*>'
    r"([\s\S]*?)</a>",
    re.I,
)
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
LEVEL_RE = re.compile(
    r"\b(j[uú]nior|jr\.?|pleno|mid(?:[- ]level)?|s[eê]nior|sr\.?|"
    r"especialista|specialist|lead|gerente|coordenador|trainee)\b",
    re.I,
)
PCD_RE = re.compile(r"\bpcd\b|pessoa(?:s)?\s+com\s+defici", re.I)
CONTRACT_RE = re.compile(
    r"\b(?:efetivo(?:\s*[–—-]\s*clt)?|clt|pj|full[- ]?time|"
    r"part[- ]?time|contract(?:or)?|tempor[aá]ri[oa]|est[aá]gio)\b",
    re.I,
)
LOCATION_RE = re.compile(
    r"(?P<city>[^,|;]{2,100}),\s*(?P<state>[^,|;]{2,100}),\s*"
    r"(?P<country>Brazil|Brasil)\b",
    re.I,
)
REMOTE_FIELD_RE = re.compile(
    r'''(?:\\+x22|")Remote_Job(?:\\+x22|")\s*:\s*(true|false)''',
    re.I,
)
ZOHO_FIELD_RE = re.compile(
    r'''(?:\\+x22|")(?P<key>City|State|Country|Job_Type)(?:\\+x22|")\s*:\s*'''
    r'''(?:\\+x22|")(?P<value>.*?)(?:\\+x22|")''',
    re.I,
)


def _text(value):
    if isinstance(value, dict):
        for key in ("name", "label", "value", "text", "description"):
            if value.get(key) not in (None, ""):
                return _text(value[key])
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value if item not in (None, ""))
    return str(value or "").strip()


def _records(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _records(child)


def _location(posting):
    value = posting.get("jobLocation") or posting.get("jobLocations") or {}
    if isinstance(value, list):
        value = value[0] if value else {}
    if isinstance(value, str):
        return value.strip(), "", "BR"
    value = value if isinstance(value, dict) else {}
    address = value.get("address") or value
    address = address if isinstance(address, dict) else {}
    city = _text(address.get("addressLocality") or address.get("city"))
    state = _text(address.get("addressRegion") or address.get("state"))
    country = _text(address.get("addressCountry") or "BR")
    return city, state, country



def _location_from_text(values):
    for value in values:
        text = strip_html(html.unescape(str(value or "")))
        match = LOCATION_RE.search(text)
        if not match:
            continue
        city = re.split(r"\s*(?:\||:|\s+-\s+)\s*", match.group("city"))[-1]
        city = city.strip(" -*–—•")
        state = match.group("state").strip(" -*–—•")
        if city and state:
            return city, state, "BR"
    return "", "", ""


def _remote_flag(markup):
    """Read Zoho's structured Remote_Job boolean from the page payload.

    The career site renders the visible "Trabalho remoto" label client-side,
    while the server response keeps the authoritative boolean in a JSON.parse
    string. Parsing this small field avoids classifying those vacancies as
    unknown when the rendered text is not present in a plain HTTP response.
    """
    match = REMOTE_FIELD_RE.search(html.unescape(markup or ""))
    if not match:
        return None
    return match.group(1).casefold() == "true"


def _zoho_fields(markup):
    """Read location and employment fields from Zoho's careers payload."""
    fields = {}
    source = html.unescape(markup or "")
    for match in ZOHO_FIELD_RE.finditer(source):
        value = re.sub(
            r"\\x([0-9a-f]{2})",
            lambda item: chr(int(item.group(1), 16)),
            match.group("value"),
        )
        value = value.replace(r"\"", '"').replace(r"\/", "/").strip()
        fields.setdefault(match.group("key"), value)
    return fields

def _date(value, raw_text=""):
    normalized = iso_date(value)
    if normalized:
        return normalized
    match = DATE_RE.search(raw_text or "")
    if match:
        day, month, year = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def _canonical_contract(value):
    text = re.sub(r"[_–—-]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    normalized = text.casefold()
    if normalized.startswith("efetivo"):
        return "Efetivo"
    if normalized in {"full time", "fulltime"}:
        return "Full-time"
    if normalized in {"part time", "parttime"}:
        return "Part-time"
    if normalized == "clt":
        return "CLT"
    if normalized == "pj":
        return "PJ"
    if normalized in {"contract", "contractor"}:
        return "Contract"
    if normalized in {"temporario", "temporaria", "temporário", "temporária"}:
        return "Temporário"
    if normalized in {"estagio", "estágio"}:
        return "Estágio"
    return text


def _contract_types(posting, raw_text):
    value = posting.get("employmentType") or posting.get("employment_type") or ""
    values = value if isinstance(value, list) else [value]
    labels = []
    for item in values:
        label = _canonical_contract(_text(item))
        if label and label not in labels:
            labels.append(label)
    for match in CONTRACT_RE.finditer(raw_text or ""):
        label = _canonical_contract(match.group(0))
        if label and label not in labels:
            labels.append(label)
    return labels


def _skills(value):
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        text = _text(item)
        result.extend(part.strip() for part in re.split(r"[,;|]", text) if part.strip())
    return list(dict.fromkeys(result))[:20]


def _fallback_title(label):
    text = strip_html(html.unescape(label or ""))
    text = re.split(r"\s+\|\s+|\s+-\s+(?:Remoto|Remota|Presencial)\b", text, maxsplit=1, flags=re.I)[0]
    return text.strip()


def _page_text(parser, markup):
    """Combine visible and metadata text used by Zoho's job header."""
    values = list(parser.parts) + list(parser.meta.values())
    title_match = re.search(
        r"<title[^>]*>([\s\S]*?)</title>", markup or "", re.I
    )
    if title_match:
        values.append(strip_html(html.unescape(title_match.group(1))))
    visible_markup = re.sub(
        r"<(?:script|style|noscript|template)\b[^>]*>[\s\S]*?</"
        r"(?:script|style|noscript|template)>",
        " ",
        markup or "",
        flags=re.I,
    )
    values.append(strip_html(visible_markup))
    return " ".join(dict.fromkeys(value.strip() for value in values if value.strip()))


def _normalize(url, markup, fallback_title=""):
    match = DETAIL_RE.search(url)
    if not match:
        return None
    parser = PublicPageParser()
    parser.feed(markup or "")
    posting = job_posting(markup or "")
    title = _text(posting.get("title")) or (parser.headings[0] if parser.headings else "")
    title = title.strip() or _fallback_title(fallback_title)
    if not title or title.casefold() in {"more info", "mais informações"}:
        return None

    raw_text = _page_text(parser, markup)
    zoho_fields = _zoho_fields(markup)
    city, state, country = _location(posting)
    if not city:
        city = _text(zoho_fields.get("City"))
    if not state:
        state = _text(zoho_fields.get("State"))
    if not country:
        country = _text(zoho_fields.get("Country"))
    text_city, text_state, text_country = _location_from_text(
        list(parser.parts) + list(parser.meta.values()) + [raw_text]
    )
    if not city and text_city:
        city = text_city
    if not state and text_state:
        state = text_state
    if not country and text_country:
        country = text_country
    remote_flag = _remote_flag(markup)
    location_type = _text(
        posting.get("jobLocationType") or posting.get("job_location_type")
    ).casefold()
    model_raw = " ".join(
        (
            raw_text,
            _text(posting.get("workplaceType")),
            _text(posting.get("workModel")),
        )
    )
    if remote_flag is True:
        work_model = "remote"
    elif remote_flag is False:
        work_model = "on-site" if city else ""
    else:
        work_model = "remote" if location_type in {
            "telecommute", "remote", "remoto", "work from home"
        } else work_model_label(raw=model_raw)
    if remote_flag is True and not city:
        city = "Brasil"
    if not work_model and city:
        work_model = "on-site"
    if not city and re.search(r"\btrabalho\s+remoto\b|\bremot[oa]\b", raw_text, re.I):
        city = "Brasil"

    organization = posting.get("hiringOrganization") or {}
    company = _text(organization.get("name")) if isinstance(organization, dict) else ""
    description = strip_html(_text(posting.get("description")))
    if not description:
        description = strip_html(raw_text)
    categories = []
    for key in ("industry", "occupationalCategory", "department"):
        value = _text(posting.get(key))
        if value and value not in categories:
            categories.append(value)
    if not categories:
        categories = ["Spassu"]
    levels = list(dict.fromkeys(
        found.group(1).title() for found in LEVEL_RE.finditer(f"{title} {description}")
    ))
    return job(
        "spassu",
        match.group(1),
        title=title,
        company=company or "Spassu",
        url=url.split("?", 1)[0],
        work_model=work_model,
        city=city,
        state=state,
        country=country or "BR",
        market="BR",
        published_date=_date(posting.get("datePosted"), raw_text),
        expires_date=_date(posting.get("validThrough")),
        description=description,
        skills=_skills(posting.get("skills")),
        levels=levels,
        categories=categories,
        contract_types=_contract_types(
            posting,
            " ".join((raw_text, zoho_fields.get("Job_Type", ""))),
        ),
        pcd=bool(PCD_RE.search(f"{title} {description}")),
    )


def _catalog_links(markup):
    parser = PublicPageParser()
    parser.feed(markup or "")
    candidates = list(parser.anchors)
    candidates.extend(
        (href, label) for href, label in ANCHOR_RE.findall(markup or "")
    )
    rows, seen = [], set()
    for href, label in candidates:
        absolute = urljoin(BASE_URL, html.unescape(href).strip())
        match = DETAIL_RE.search(absolute)
        label = strip_html(html.unescape(label))
        if not match or not label or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        rows.append((absolute, label))
    return rows


def _fetch_detail(url, label):
    try:
        markup = get_text(url, timeout=35, retries=2)
        return _normalize(url, markup, label)
    except Exception:
        return None


def fetch():
    catalog_error = None
    try:
        markup = get_text(
            BOARD_URL,
            headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "User-Agent": "Mozilla/5.0 (compatible; todas-as-vagas/1.0)",
            },
            timeout=45,
            retries=3,
        )
    except Exception as error:
        markup = ""
        catalog_error = error
    links = _catalog_links(markup)
    if not links:
        links = [
            (href, strip_html(label))
            for href, label in rendered_links(
                BOARD_URL,
                r"/jobs/Careers/\d+(?:/|$)",
                timeout=60,
            )
            if DETAIL_RE.search(href)
        ]
    if not links:
        detail = f": {catalog_error}" if catalog_error else ""
        raise RuntimeError(
            f"Zoho Recruit/Spassu returned no public vacancy links{detail}"
        )

    rows = []
    with ThreadPoolExecutor(max_workers=min(8, len(links))) as pool:
        futures = {
            pool.submit(_fetch_detail, url, label): (url, label)
            for url, label in links
        }
        for future in as_completed(futures):
            row = future.result()
            if row:
                rows.append(row)
    if not rows:
        raise RuntimeError("Spassu public catalogue contained no readable vacancies")
    rows.sort(
        key=lambda row: (row.get("published_date") or "", row["native_id"]),
        reverse=True,
    )
    return rows
# -*- coding: utf-8 -*-
"""Brazilian public vacancies from Spassu's Zoho Recruit career site."""
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_text
from ._html import PublicPageParser, job_posting
from ._rendered import rendered_links


BASE_URL = "https://spassu.zohorecruit.com"
BOARD_URL = f"{BASE_URL}/jobs/Careers"
DETAIL_RE = re.compile(r"/jobs/careers/(\d+)(?:/[^/?#]*)?", re.I)
ANCHOR_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']*/jobs/Careers/\d+[^"\']*)["\'][^>]*>'
    r"([\s\S]*?)</a>",
    re.I,
)
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
LEVEL_RE = re.compile(
    r"\b(j[uú]nior|jr\.?|pleno|mid(?:[- ]level)?|s[eê]nior|sr\.?|"
    r"especialista|specialist|lead|gerente|coordenador|trainee)\b",
    re.I,
)
PCD_RE = re.compile(r"\bpcd\b|pessoa(?:s)?\s+com\s+defici", re.I)
CONTRACT_RE = re.compile(
    r"\b(?:efetivo(?:\s*[–—-]\s*clt)?|clt|pj|full[- ]?time|"
    r"part[- ]?time|contract(?:or)?|tempor[aá]ri[oa]|est[aá]gio)\b",
    re.I,
)
LOCATION_RE = re.compile(
    r"(?P<city>[^,|;]{2,100}),\s*(?P<state>[^,|;]{2,100}),\s*"
    r"(?P<country>Brazil|Brasil)\b",
    re.I,
)
REMOTE_FIELD_RE = re.compile(
    r'''(?:\\+x22|")Remote_Job(?:\\+x22|")\s*:\s*(true|false)''',
    re.I,
)


def _text(value):
    if isinstance(value, dict):
        for key in ("name", "label", "value", "text", "description"):
            if value.get(key) not in (None, ""):
                return _text(value[key])
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value if item not in (None, ""))
    return str(value or "").strip()


def _records(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _records(child)


def _location(posting):
    value = posting.get("jobLocation") or posting.get("jobLocations") or {}
    if isinstance(value, list):
        value = value[0] if value else {}
    if isinstance(value, str):
        return value.strip(), "", "BR"
    value = value if isinstance(value, dict) else {}
    address = value.get("address") or value
    address = address if isinstance(address, dict) else {}
    city = _text(address.get("addressLocality") or address.get("city"))
    state = _text(address.get("addressRegion") or address.get("state"))
    country = _text(address.get("addressCountry") or "BR")
    return city, state, country



def _location_from_text(values):
    for value in values:
        text = strip_html(html.unescape(str(value or "")))
        match = LOCATION_RE.search(text)
        if not match:
            continue
        city = re.split(r"\s*(?:\||:|\s+-\s+)\s*", match.group("city"))[-1]
        city = city.strip(" -*–—•")
        state = match.group("state").strip(" -*–—•")
        if city and state:
            return city, state, "BR"
    return "", "", ""


def _remote_flag(markup):
    """Read Zoho's structured Remote_Job boolean from the page payload.

    The career site renders the visible "Trabalho remoto" label client-side,
    while the server response keeps the authoritative boolean in a JSON.parse
    string. Parsing this small field avoids classifying those vacancies as
    unknown when the rendered text is not present in a plain HTTP response.
    """
    match = REMOTE_FIELD_RE.search(html.unescape(markup or ""))
    if not match:
        return None
    return match.group(1).casefold() == "true"

def _date(value, raw_text=""):
    normalized = iso_date(value)
    if normalized:
        return normalized
    match = DATE_RE.search(raw_text or "")
    if match:
        day, month, year = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def _canonical_contract(value):
    text = re.sub(r"[_–—-]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    normalized = text.casefold()
    if normalized.startswith("efetivo"):
        return "Efetivo"
    if normalized in {"full time", "fulltime"}:
        return "Full-time"
    if normalized in {"part time", "parttime"}:
        return "Part-time"
    if normalized == "clt":
        return "CLT"
    if normalized == "pj":
        return "PJ"
    if normalized in {"contract", "contractor"}:
        return "Contract"
    if normalized in {"temporario", "temporaria", "temporário", "temporária"}:
        return "Temporário"
    if normalized in {"estagio", "estágio"}:
        return "Estágio"
    return text


def _contract_types(posting, raw_text):
    value = posting.get("employmentType") or posting.get("employment_type") or ""
    values = value if isinstance(value, list) else [value]
    labels = []
    for item in values:
        label = _canonical_contract(_text(item))
        if label and label not in labels:
            labels.append(label)
    for match in CONTRACT_RE.finditer(raw_text or ""):
        label = _canonical_contract(match.group(0))
        if label and label not in labels:
            labels.append(label)
    return labels


def _skills(value):
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        text = _text(item)
        result.extend(part.strip() for part in re.split(r"[,;|]", text) if part.strip())
    return list(dict.fromkeys(result))[:20]


def _fallback_title(label):
    text = strip_html(html.unescape(label or ""))
    text = re.split(r"\s+\|\s+|\s+-\s+(?:Remoto|Remota|Presencial)\b", text, maxsplit=1, flags=re.I)[0]
    return text.strip()


def _page_text(parser, markup):
    """Combine visible and metadata text used by Zoho's job header."""
    values = list(parser.parts) + list(parser.meta.values())
    title_match = re.search(
        r"<title[^>]*>([\s\S]*?)</title>", markup or "", re.I
    )
    if title_match:
        values.append(strip_html(html.unescape(title_match.group(1))))
    visible_markup = re.sub(
        r"<(?:script|style|noscript|template)\b[^>]*>[\s\S]*?</"
        r"(?:script|style|noscript|template)>",
        " ",
        markup or "",
        flags=re.I,
    )
    values.append(strip_html(visible_markup))
    return " ".join(dict.fromkeys(value.strip() for value in values if value.strip()))


def _normalize(url, markup, fallback_title=""):
    match = DETAIL_RE.search(url)
    if not match:
        return None
    parser = PublicPageParser()
    parser.feed(markup or "")
    posting = job_posting(markup or "")
    title = _text(posting.get("title")) or (parser.headings[0] if parser.headings else "")
    title = title.strip() or _fallback_title(fallback_title)
    if not title or title.casefold() in {"more info", "mais informações"}:
        return None

    raw_text = _page_text(parser, markup)
    city, state, country = _location(posting)
    text_city, text_state, text_country = _location_from_text(
        list(parser.parts) + list(parser.meta.values()) + [raw_text]
    )
    if not city and text_city:
        city = text_city
    if not state and text_state:
        state = text_state
    if not country and text_country:
        country = text_country
    remote_flag = _remote_flag(markup)
    location_type = _text(
        posting.get("jobLocationType") or posting.get("job_location_type")
    ).casefold()
    model_raw = " ".join(
        (
            raw_text,
            _text(posting.get("workplaceType")),
            _text(posting.get("workModel")),
        )
    )
    if remote_flag is True:
        work_model = "remote"
    elif remote_flag is False:
        work_model = "on-site" if city else ""
    else:
        work_model = "remote" if location_type in {
            "telecommute", "remote", "remoto", "work from home"
        } else work_model_label(raw=model_raw)
    if remote_flag is True and not city:
        city = "Brasil"
    if not work_model and city:
        work_model = "on-site"
    if not city and re.search(r"\btrabalho\s+remoto\b|\bremot[oa]\b", raw_text, re.I):
        city = "Brasil"

    organization = posting.get("hiringOrganization") or {}
    company = _text(organization.get("name")) if isinstance(organization, dict) else ""
    description = strip_html(_text(posting.get("description")))
    if not description:
        description = strip_html(raw_text)
    categories = []
    for key in ("industry", "occupationalCategory", "department"):
        value = _text(posting.get(key))
        if value and value not in categories:
            categories.append(value)
    if not categories:
        categories = ["Spassu"]
    levels = list(dict.fromkeys(
        found.group(1).title() for found in LEVEL_RE.finditer(f"{title} {description}")
    ))
    return job(
        "spassu",
        match.group(1),
        title=title,
        company=company or "Spassu",
        url=url.split("?", 1)[0],
        work_model=work_model,
        city=city,
        state=state,
        country=country or "BR",
        market="BR",
        published_date=_date(posting.get("datePosted"), raw_text),
        expires_date=_date(posting.get("validThrough")),
        description=description,
        skills=_skills(posting.get("skills")),
        levels=levels,
        categories=categories,
        contract_types=_contract_types(posting, raw_text),
        pcd=bool(PCD_RE.search(f"{title} {description}")),
    )


def _catalog_links(markup):
    parser = PublicPageParser()
    parser.feed(markup or "")
    candidates = list(parser.anchors)
    candidates.extend(
        (href, label) for href, label in ANCHOR_RE.findall(markup or "")
    )
    rows, seen = [], set()
    for href, label in candidates:
        absolute = urljoin(BASE_URL, html.unescape(href).strip())
        match = DETAIL_RE.search(absolute)
        label = strip_html(html.unescape(label))
        if not match or not label or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        rows.append((absolute, label))
    return rows


def _fetch_detail(url, label):
    try:
        markup = get_text(url, timeout=35, retries=2)
        return _normalize(url, markup, label)
    except Exception:
        return None


def fetch():
    catalog_error = None
    try:
        markup = get_text(
            BOARD_URL,
            headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "User-Agent": "Mozilla/5.0 (compatible; todas-as-vagas/1.0)",
            },
            timeout=45,
            retries=3,
        )
    except Exception as error:
        markup = ""
        catalog_error = error
    links = _catalog_links(markup)
    if not links:
        links = [
            (href, strip_html(label))
            for href, label in rendered_links(
                BOARD_URL,
                r"/jobs/Careers/\d+(?:/|$)",
                timeout=60,
            )
            if DETAIL_RE.search(href)
        ]
    if not links:
        detail = f": {catalog_error}" if catalog_error else ""
        raise RuntimeError(
            f"Zoho Recruit/Spassu returned no public vacancy links{detail}"
        )

    rows = []
    with ThreadPoolExecutor(max_workers=min(8, len(links))) as pool:
        futures = {
            pool.submit(_fetch_detail, url, label): (url, label)
            for url, label in links
        }
        for future in as_completed(futures):
            row = future.result()
            if row:
                rows.append(row)
    if not rows:
        raise RuntimeError("Spassu public catalogue contained no readable vacancies")
    rows.sort(
        key=lambda row: (row.get("published_date") or "", row["native_id"]),
        reverse=True,
    )
    return rows
