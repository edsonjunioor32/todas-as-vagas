# -*- coding: utf-8 -*-
"""Public vacancies from South System's Jobii careers portal."""
import re
import time
from urllib.parse import urlsplit

from ._common import job, strip_html, work_model_label
from ._rendered import _close_driver, _webdriver, rendered_paginated_links


LISTING_URL = "https://vagas.jobii.com.br/vagas?page=0"
ORIGIN = "https://vagas.jobii.com.br"
COMPANY = "South System"
TIMEOUT_SECONDS = 30
MAX_PAGES = 20
MAX_VACANCIES = 1000
DETAIL_PATH_RE = re.compile(r"^/vagas/(\d+)/?$")
DETAIL_LINK_PATTERN = r"vagas\.jobii\.com\.br/vagas/\d+(?:[/?#]|$)"
DESCRIPTION_HEADING_RE = re.compile(r"descri[cç][aã]o\s+da\s+vaga", re.I)
LEVELS = (
    ("Júnior", re.compile(r"\bj[uú]nior\b", re.I)),
    ("Pleno", re.compile(r"\bpleno\b", re.I)),
    ("Sênior", re.compile(r"\bs[eê]nior\b", re.I)),
    ("Especialista", re.compile(r"\bespecialista\b", re.I)),
    ("Liderança", re.compile(r"\b(?:lead|lideran[cç]a|coordenador|gerente|head)\b", re.I)),
)
CONTRACTS = (
    ("CLT", re.compile(r"\bCLT\b", re.I)),
    ("PJ", re.compile(r"\bPJ\b", re.I)),
    ("Estágio", re.compile(r"\best[aá]gio\b", re.I)),
    ("Temporário", re.compile(r"\btempor[aá]rio\b", re.I)),
)

DETAIL_SCRIPT = r"""
  const main = document.querySelector('main,[role="main"]') || document.body;
  const title = main.querySelector('h1') || document.querySelector('h1');
  return {
    title: (title?.innerText || title?.textContent || '').trim(),
    text: (main.innerText || main.textContent || '').trim()
  };
"""


def _canonical_detail_url(url):
    parsed = urlsplit(str(url or "").strip())
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() not in {"vagas.jobii.com.br", "www.vagas.jobii.com.br"}
    ):
        return None
    match = DETAIL_PATH_RE.fullmatch(parsed.path)
    if not match:
        return None
    native_id = match.group(1)
    return native_id, f"{ORIGIN}/vagas/{native_id}"


def _lines(value):
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in str(value or "").replace("\xa0", " ").splitlines()
        if line.strip()
    ]


def _field(lines, label, stop_labels=()):
    stops = "|".join(re.escape(item) for item in stop_labels)
    for line in lines[:18]:
        match = re.search(rf"\b{re.escape(label)}\s*:\s*(.*)$", line, re.I)
        if not match:
            continue
        value = match.group(1).strip()
        if stops:
            value = re.split(rf"\s+(?:{stops})\s*:", value, maxsplit=1, flags=re.I)[0]
        return value.strip(" \t:-")
    return ""


def _description(text):
    value = str(text or "").replace("\xa0", " ").strip()
    match = DESCRIPTION_HEADING_RE.search(value)
    if not match:
        return ""
    return strip_html(value[match.end():].strip(), limit=60000)


def _location(value, work_model):
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,.-")
    if not text or work_model == "remote" or text.casefold() in {"remoto", "remota", "brasil", "brazil"}:
        return ("Brasil" if work_model == "remote" else ""), "", "BR"
    match = re.search(r"(?:,|\s[-/]\s)([A-Z]{2})$", text, re.I)
    if match:
        return text[:match.start()].strip(" ,.-"), match.group(1).upper(), "BR"
    return text, "", "BR"


def _normalize(native_id, url, payload, fallback_title=""):
    if not isinstance(payload, dict):
        payload = {}
    title = re.sub(r"^Detalhes\s+da\s+vaga\s+de\s+", "", fallback_title, flags=re.I).strip()
    title = str(payload.get("title") or title).strip()
    if not native_id or not title:
        return None

    raw_text = str(payload.get("text") or "")
    lines = _lines(raw_text)
    summary = "\n".join(lines[:18])
    modality = _field(lines, "Modalidade", ("Nível", "Local"))
    work_model = work_model_label(raw=modality or summary)
    local = _field(lines, "Local", ("Nível", "Modalidade"))
    if not work_model:
        work_model = work_model_label(raw=local)
    city, state, country = _location(local, work_model)
    if not local and work_model == "remote":
        city = "Brasil"

    level_value = _field(lines, "Nível", ("Modalidade", "Local"))
    levels = [label for label, pattern in LEVELS if pattern.search(level_value or title)]
    contract_types = [label for label, pattern in CONTRACTS if pattern.search(summary)]

    return job(
        "jobii",
        native_id,
        title=title,
        company=COMPANY,
        url=url,
        work_model=work_model,
        city=city,
        state=state,
        country=country,
        market="BR",
        description=_description(raw_text),
        levels=levels,
        contract_types=contract_types,
    )


def _read_detail(driver, url):
    driver.get(url)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        payload = driver.execute_script(DETAIL_SCRIPT)
        if isinstance(payload, dict) and payload.get("title"):
            return payload
        time.sleep(0.25)
    raise RuntimeError("Jobii did not render a vacancy title")


def fetch():
    """Collect every active vacancy shown by Jobii's paginated public board."""
    links = rendered_paginated_links(
        LISTING_URL,
        DETAIL_LINK_PATTERN,
        timeout=TIMEOUT_SECONDS * 4,
        max_pages=MAX_PAGES,
    )
    if len(links) > MAX_VACANCIES:
        raise RuntimeError(
            f"Jobii exceeded the safety limit of {MAX_VACANCIES} vacancies"
        )

    driver = _webdriver()
    rows = {}
    failures = 0
    try:
        driver.set_page_load_timeout(TIMEOUT_SECONDS)
        for href, label in links:
            identity = _canonical_detail_url(href)
            if not identity:
                continue
            native_id, canonical_url = identity
            if native_id in rows:
                continue
            try:
                payload = _read_detail(driver, canonical_url)
            except Exception:
                payload = {}
                failures += 1
            row = _normalize(native_id, canonical_url, payload, label)
            if row:
                rows[native_id] = row
    finally:
        _close_driver(driver)

    if not rows:
        raise RuntimeError("Jobii public catalogue returned no readable vacancies")
    if failures:
        print(f"    [jobii] {failures} detail pages unavailable; listing entries retained")
    return list(rows.values())
