# -*- coding: utf-8 -*-
"""Recent public home-office vacancies from InfoJobs Brasil.

InfoJobs protects its public result pages with a JavaScript WAF challenge, so
plain ``urllib``/``requests`` calls receive HTTP 403.  This adapter uses the
Chrome installation already available on GitHub-hosted runners, waits for the
public result cards and reads only the metadata shown in those cards.  It does
not log in, apply for vacancies or collect candidate data.
"""
import os
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from ._common import job


SOURCE = "infojobs"
LIST_URL = (
    "https://www.infojobs.com.br/empregos-trabalho-home-office.aspx"
    "?campo=griddate&orden=desc"
)
LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")

MONTHS = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}
DATE_RE = re.compile(
    r"^(?:hoje|ontem|h[aá]\s+(\d+)\s+dias?|"
    r"(\d{1,2})\s+(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)"
    r"(?:\s+(\d{4}))?)$",
    re.I,
)
LOCATION_RE = re.compile(
    r"^(.+?)\s+-\s+([A-Z]{2}),\s*\d+(?:[,.]\d+)?\s*Km de você\.?$",
    re.I,
)
JOB_ID_RE = re.compile(r"__(\d+)\.aspx(?:$|[?#])", re.I)
REMOTE_RE = re.compile(r"\b(?:home\s*-?\s*office|remot[oa])\b", re.I)
RATING_RE = re.compile(r"^\d(?:[,.]\d)?$")
SALARY_RE = re.compile(r"^(?:R\$|A combinar\b)", re.I)


def _integer_env(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _lines(value):
    return [
        re.sub(r"\s+", " ", part).strip()
        for part in str(value or "").splitlines()
        if re.sub(r"\s+", " ", part).strip()
    ]


def _published_date(value, today=None):
    """Convert InfoJobs' Portuguese relative/card date to ISO format."""
    today = today or date.today()
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    if text == "hoje":
        return today.isoformat()
    if text == "ontem":
        return (today - timedelta(days=1)).isoformat()

    match = DATE_RE.match(text)
    if not match:
        return ""
    relative_days, day_value, month_key, year_value = match.groups()
    if relative_days:
        return (today - timedelta(days=int(relative_days))).isoformat()

    year = int(year_value) if year_value else today.year
    try:
        parsed = date(year, MONTHS[month_key.casefold()], int(day_value))
    except (KeyError, TypeError, ValueError):
        return ""
    if not year_value and parsed > today + timedelta(days=1):
        parsed = parsed.replace(year=year - 1)
    return parsed.isoformat()


def _date_from_lines(lines, today):
    for index, line in enumerate(lines[:16]):
        if DATE_RE.match(line.casefold()):
            return _published_date(line, today=today), index
    return "", -1


def _location_from_lines(lines, date_index):
    start = date_index + 1 if date_index >= 0 else 0
    for line in lines[start:]:
        if line.casefold() in {"todo brasil", "brasil"}:
            return "Brasil", ""
        match = LOCATION_RE.match(line)
        if match:
            city = match.group(1).strip(" ,.-")
            state = match.group(2).upper()
            if city and city.casefold() not in {"home office", "remoto"}:
                return city, state
    return "Brasil", ""


def _company_from_lines(lines, date_index):
    start = date_index + 1 if date_index >= 0 else 0
    ignored = {
        "nova",
        "contratação urgente",
        "home office",
        "remoto",
        "vagas semelhantes",
        "candidatar-me",
        "candidatura enviada",
    }
    for line in lines[start:start + 8]:
        folded = line.casefold()
        if folded in ignored or RATING_RE.match(line) or SALARY_RE.match(line):
            continue
        if LOCATION_RE.match(line) or folded in {"todo brasil", "brasil"}:
            continue
        if DATE_RE.match(folded):
            continue
        if len(line) <= 140:
            return line
    return "Empresa confidencial"


def _contract_types(text):
    folded = text.casefold()
    values = []
    patterns = (
        ("CLT", r"\bclt\b|efetivo\s*[–-]\s*clt"),
        ("PJ", r"\bpj\b|prestador(?:a)? de servi[cç]os"),
        ("Cooperado", r"\bcooperad[oa]\b"),
        ("Estágio", r"\best[aá]gio\b"),
        ("Jovem Aprendiz", r"\bjovem aprendiz\b"),
        ("Temporário", r"\btempor[aá]ri[oa]\b"),
        ("Autônomo", r"\baut[oô]nom[oa]\b"),
    )
    for label, pattern in patterns:
        if re.search(pattern, folded):
            values.append(label)
    return values


def _description_from_lines(lines):
    remote_index = next(
        (index for index, line in enumerate(lines) if REMOTE_RE.fullmatch(line)),
        -1,
    )
    candidates = lines[remote_index + 1:] if remote_index >= 0 else lines
    excluded = {
        "vagas semelhantes",
        "candidatar-me",
        "candidatura enviada",
    }
    parts = [line for line in candidates if line.casefold() not in excluded]
    return " ".join(parts)[:3000]


def _canonical_url(value):
    parsed = urlsplit(str(value or ""))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _title_from_lines(title_lines, card_lines):
    ignored = {"nova", "contratação urgente", "home office", "remoto"}
    for line in title_lines + card_lines[:12]:
        folded = line.casefold()
        if folded in ignored or DATE_RE.match(folded) or RATING_RE.match(line):
            continue
        if SALARY_RE.match(line) or LOCATION_RE.match(line):
            continue
        return line
    return ""


def _normalize(raw, today):
    url = _canonical_url(raw.get("href"))
    identifier = JOB_ID_RE.search(url)
    title_lines = _lines(raw.get("title"))
    card_lines = _lines(raw.get("text"))
    title = _title_from_lines(title_lines, card_lines)
    has_remote_modality = any(REMOTE_RE.fullmatch(line) for line in card_lines)
    if not identifier or not title or not has_remote_modality:
        return None

    published_date, date_index = _date_from_lines(card_lines, today)
    company = _company_from_lines(card_lines, date_index)
    city, state = _location_from_lines(card_lines, date_index)
    description = _description_from_lines(card_lines)
    return job(
        SOURCE,
        identifier.group(1),
        title=title,
        company=company,
        url=url,
        work_model="remote",
        city=city,
        state=state,
        country="BR",
        market="BR",
        published_date=published_date,
        description=description,
        contract_types=_contract_types(" ".join(card_lines)),
        blind_selection="confidencial" in company.casefold(),
    )


def _new_driver():
    try:
        from selenium import webdriver
    except ImportError as error:
        raise RuntimeError("Selenium is required to collect InfoJobs") from error

    options = webdriver.ChromeOptions()
    for argument in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-notifications",
        "--window-size=1440,3000",
        "--lang=pt-BR",
    ):
        options.add_argument(argument)
    options.page_load_strategy = "eager"
    return webdriver.Chrome(options=options)


def _job_count(driver):
    return int(driver.execute_script(
        "return new Set(Array.from(document.querySelectorAll("
        "'a[href*=\"/vaga-de-\"]')).map(a => "
        "(a.href.match(/__(\\d+)\\.aspx/i)||[])[1]).filter(Boolean)).size;"
    ))


def _wait_for_results(driver, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _job_count(driver):
            return
        time.sleep(1)
    title = str(driver.title or "").strip()
    raise RuntimeError(
        "InfoJobs did not expose public vacancy cards after rendering"
        + (f" (page title: {title})" if title else "")
    )


def _load_more(driver, max_jobs, max_scrolls):
    stable_rounds = 0
    previous = _job_count(driver)
    for _ in range(max_scrolls):
        if previous >= max_jobs:
            break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)
        current = _job_count(driver)
        stable_rounds = stable_rounds + 1 if current == previous else 0
        previous = current
        if stable_rounds >= 3:
            break


def _raw_cards(driver):
    return driver.execute_script(
        r"""
        const seen = new Set();
        const rows = [];
        for (const anchor of document.querySelectorAll('a[href*="/vaga-de-"]')) {
          const match = anchor.href.match(/__(\d+)\.aspx/i);
          if (!match || seen.has(match[1])) continue;
          let card = anchor.closest('div[data-id]') ||
                     anchor.closest('article') ||
                     anchor.closest('li') ||
                     anchor.closest('.card');
          if (!card) {
            let node = anchor;
            for (let level = 0; level < 7 && node; level++, node = node.parentElement) {
              if (/home\s*-?\s*office|remot[oa]/i.test(node.innerText || '')) {
                card = node;
                break;
              }
            }
          }
          const titleNode = (card && card.querySelector('h2, h3')) ||
                            anchor.querySelector('h2, h3') || anchor;
          seen.add(match[1]);
          rows.push({
            href: anchor.href,
            title: (titleNode.innerText || anchor.innerText || '').trim(),
            text: ((card || anchor).innerText || '').trim(),
          });
        }
        return rows;
        """
    )


def fetch():
    max_jobs = _integer_env("INFOJOBS_MAX_JOBS", 200, 20, 500)
    max_scrolls = _integer_env("INFOJOBS_MAX_SCROLLS", 20, 0, 50)
    timeout = _integer_env("INFOJOBS_RENDER_TIMEOUT", 50, 15, 90)
    driver = _new_driver()
    try:
        driver.set_page_load_timeout(timeout)
        try:
            driver.get(LIST_URL)
        except Exception as error:
            if error.__class__.__name__ != "TimeoutException":
                raise
        _wait_for_results(driver, timeout)
        _load_more(driver, max_jobs=max_jobs, max_scrolls=max_scrolls)
        raw_rows = _raw_cards(driver)[:max_jobs]
    finally:
        driver.quit()

    today = datetime.now(LOCAL_TIMEZONE).date()
    rows, seen = [], set()
    for raw in raw_rows:
        row = _normalize(raw, today=today)
        if row and row["native_id"] not in seen:
            seen.add(row["native_id"])
            rows.append(row)
    if not rows:
        raise RuntimeError("InfoJobs rendered the page but returned no home-office vacancies")
    return rows
