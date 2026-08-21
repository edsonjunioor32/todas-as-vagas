# -*- coding: utf-8 -*-
"""Recent public vacancies from InfoJobs Brasil.

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
LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")

# InfoJobs' public national page is geo-personalized by the visitor's IP and
# exposes only one result page.  These public state and city result pages give
# broad, repeatable coverage without following the unrelated "Próximas"
# distance-sorting link that appears on the national page.
LOCATION_SLUGS = (
    "sao-paulo", "rio-de-janeiro", "minas-gerais", "bahia", "parana",
    "rio-grande-do-sul", "pernambuco", "ceara", "santa-catarina", "goias",
    "distrito-federal", "para", "espirito-santo", "mato-grosso", "mato-grosso-do-sul",
    "amazonas", "maranhao", "paraiba", "rio-grande-do-norte", "alagoas", "piaui",
    "sergipe", "rondonia", "tocantins", "acre", "amapa", "roraima",
    "sao-paulo,-sp", "guarulhos,-sp", "osasco,-sp", "barueri,-sp",
    "santo-andre,-sp", "sao-bernardo-do-campo,-sp", "sao-caetano-do-sul,-sp",
    "campinas,-sp", "sorocaba,-sp", "jundiai,-sp", "santos,-sp",
    "ribeirao-preto,-sp", "sao-jose-dos-campos,-sp", "mogi-das-cruzes,-sp",
    "cotia,-sp", "cajamar,-sp", "taboao-da-serra,-sp", "diadema,-sp",
    "rio-de-janeiro,-rj", "niteroi,-rj", "duque-de-caxias,-rj",
    "belo-horizonte,-mg", "contagem,-mg", "betim,-mg", "uberlandia,-mg",
    "curitiba,-pr", "londrina,-pr", "sao-jose-dos-pinhais,-pr",
    "porto-alegre,-rs", "caxias-do-sul,-rs", "canoas,-rs",
    "florianopolis,-sc", "joinville,-sc", "blumenau,-sc",
    "salvador,-ba", "feira-de-santana,-ba", "recife,-pe", "jaboatao-dos-guararapes,-pe",
    "fortaleza,-ce", "goiania,-go", "brasilia,-df", "belem,-pa", "manaus,-am",
    "joao-pessoa,-pb", "natal,-rn", "maceio,-al", "aracaju,-se", "teresina,-pi",
    "sao-jose-do-rio-preto,-sp", "piracicaba,-sp", "bauru,-sp", "franca,-sp",
    "aracatuba,-sp", "presidente-prudente,-sp", "marilia,-sp", "sao-carlos,-sp",
    "araraquara,-sp", "indaiatuba,-sp", "itu,-sp", "sumare,-sp", "americana,-sp",
    "hortolandia,-sp", "sao-vicente,-sp", "praia-grande,-sp", "maua,-sp",
    "nova-iguacu,-rj", "campos-dos-goytacazes,-rj", "sao-goncalo,-rj",
    "vitoria,-es", "serra,-es", "vila-velha,-es", "cuiaba,-mt", "campo-grande,-ms",
    "uberaba,-mg", "juiz-de-fora,-mg", "governador-valadares,-mg",
    "maringa,-pr", "ponta-grossa,-pr", "cascavel,-pr",
    "pelotas,-rs", "santa-maria,-rs", "caruaru,-pe", "olinda,-pe", "camacari,-ba",
    "juazeiro-do-norte,-ce", "maracanau,-ce", "santarem,-pa", "ananindeua,-pa",
)

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
SIMPLE_LOCATION_RE = re.compile(r"^(.+?)\s+-\s+([A-Z]{2})$", re.I)
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
            # A nationwide search result is not evidence that the role is remote.
            return "", ""
        match = LOCATION_RE.match(line) or SIMPLE_LOCATION_RE.match(line)
        if match:
            city = match.group(1).strip(" ,.-")
            state = match.group(2).upper()
            if city and city.casefold() not in {
                "home office", "remoto", "remota", "híbrido", "hibrido", "presencial",
            }:
                return city, state
    return "", ""


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
        if (LOCATION_RE.match(line) or SIMPLE_LOCATION_RE.match(line)
                or folded in {"todo brasil", "brasil"}):
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
    excluded = {
        "vagas semelhantes",
        "candidatar-me",
        "candidatura enviada",
    }
    parts = [line for line in lines if line.casefold() not in excluded]
    return " ".join(parts)[:3000]


def _canonical_url(value):
    parsed = urlsplit(str(value or ""))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _title_from_lines(title_lines, card_lines):
    ignored = {
        "nova", "contratação urgente", "home office", "remoto", "remota",
        "híbrido", "hibrido", "presencial",
    }
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
    if not identifier or not title:
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
        work_model=_work_model_from_lines(card_lines),
        city=city,
        state=state,
        country="BR",
        market="BR",
        published_date=published_date,
        description=description,
        contract_types=_contract_types(" ".join(card_lines)),
        blind_selection="confidencial" in company.casefold(),
    )


def _work_model_from_lines(lines):
    text = " ".join(lines)
    if REMOTE_RE.search(text):
        return "remote"
    if re.search(r"\bh[ií]brid[oa]\b", text, re.I):
        return "hybrid"
    if re.search(r"\b(?:presencial|on[ -]?site)\b", text, re.I):
        return "on-site"
    return ""


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


def _job_identifier(row):
    match = JOB_ID_RE.search(_canonical_url(row.get("href")))
    return match.group(1) if match else ""


def _job_identifiers(rows):
    return {identifier for identifier in map(_job_identifier, rows) if identifier}


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
              if ((node.innerText || '').trim().length > 40) {
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
    max_jobs = _integer_env("INFOJOBS_MAX_JOBS", 500, 20, 500)
    # Public regional pages render their full card set immediately. Avoiding
    # speculative scrolling keeps the multi-location collection fast.
    max_scrolls = _integer_env("INFOJOBS_MAX_SCROLLS", 0, 0, 20)
    timeout = _integer_env("INFOJOBS_RENDER_TIMEOUT", 50, 15, 90)
    driver = _new_driver()
    try:
        driver.set_page_load_timeout(timeout)
        raw_rows, known_ids = [], set()
        for location in LOCATION_SLUGS:
            url = (
                "https://www.infojobs.com.br/empregos-em-"
                f"{location}.aspx?campo=griddate&orden=desc"
            )
            try:
                driver.get(url)
                _wait_for_results(driver, timeout)
            except Exception:
                # A single unavailable regional page must not discard the
                # results already collected from other public pages.
                continue
            if urlsplit(driver.current_url).path.casefold() != urlsplit(url).path.casefold():
                # Invalid city slugs redirect to another city's page. Ignore
                # them instead of silently re-reading unrelated vacancies.
                continue
            _load_more(driver, max_jobs=max_jobs, max_scrolls=max_scrolls)
            current_rows = _raw_cards(driver)
            current_ids = _job_identifiers(current_rows)
            raw_rows.extend(
                row for row in current_rows
                if _job_identifier(row) not in known_ids
            )
            known_ids.update(current_ids)
            if len(known_ids) >= max_jobs:
                break
        raw_rows = raw_rows[:max_jobs]
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
        raise RuntimeError("InfoJobs rendered the page but returned no public vacancies")
    return rows
