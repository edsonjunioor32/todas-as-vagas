# -*- coding: utf-8 -*-
"""Public, browser-rendered job board for Valorei."""
from datetime import date
import re
from urllib.parse import urlsplit

from ._common import is_brazil_location, job, strip_html, work_model_label
from .ats_boards import PER_COMPANY


JOBS_URL = "https://vagas.valorei.tech/jobs"
ORIGIN = "https://vagas.valorei.tech"
TIMEOUT_SECONDS = 25
JOB_PATH_RE = re.compile(r"^/jobs/([^/]+)/?$")
PUBLISHED_DATE_RE = re.compile(
    r"\b(?:publicad[ao]|posted)(?:\s+(?:em|on))?\s+(\d{1,2})/(\d{1,2})/(\d{4})\b",
    re.I,
)
SALARY_RE = re.compile(
    r"(?P<cap>at[eé]\s+)?R\$\s*(?P<first>[\d.]+(?:,\d{1,2})?)"
    r"(?:\s*[–—-]\s*R\$\s*(?P<second>[\d.]+(?:,\d{1,2})?))?",
    re.I,
)
STATE_CODES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT",
    "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO",
    "RR", "SC", "SP", "SE", "TO",
}
STATE_NAMES = {
    "acre", "alagoas", "amapá", "amazonas", "bahia", "ceará",
    "distrito federal", "espírito santo", "goiás", "maranhão",
    "mato grosso", "mato grosso do sul", "minas gerais", "pará",
    "paraíba", "paraná", "pernambuco", "piauí", "rio de janeiro",
    "rio grande do norte", "rio grande do sul", "rondônia", "roraima",
    "santa catarina", "são paulo", "sergipe", "tocantins",
}
CATEGORY_LABELS = {
    "comercial": "Comercial",
    "dados & ia": "Dados & IA",
    "dados e ia": "Dados & IA",
    "design": "Design",
    "operações": "Operações",
    "operacoes": "Operações",
    "redes": "Redes",
    "rh & pessoas": "RH & Pessoas",
    "rh e pessoas": "RH & Pessoas",
    "suporte": "Suporte",
    "tecnologia": "Tecnologia",
}
CONTRACT_PATTERNS = (
    ("CLT", r"\bCLT\b"),
    ("PJ", r"\bPJ\b"),
    ("Estágio", r"\b(?:est[aá]gio|estagi[aá]rio)\b"),
    ("Temporário", r"\btempor[aá]rio\b"),
    ("Jovem Aprendiz", r"\bjovem\s+aprendiz\b"),
    ("Associado", r"\b(?:associate|associado)\b"),
    ("Freelancer", r"\bfreelancer\b"),
)
LEVEL_PATTERNS = (
    ("Junior", r"\b(?:junior|j[uú]nior|entry.level)\b"),
    ("Mid-level", r"\b(?:mid.level|pleno)\b"),
    ("Senior", r"\b(?:senior|s[eê]nior|principal|staff)\b"),
    ("Leadership", r"\b(?:lead|lideran[cç]a|coordenador|gerente|head)\b"),
)


def _new_driver():
    """Start headless Chrome; Selenium is already used by the job pipeline."""
    try:
        from selenium import webdriver
    except ImportError as error:
        raise RuntimeError("Selenium is required to collect Valorei vacancies") from error

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


def _wait_for_element(driver, selector, timeout=TIMEOUT_SECONDS):
    """Wait for a public listing/detail element rendered in the page."""
    try:
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as error:
        raise RuntimeError("Selenium is required to collect Valorei vacancies") from error

    WebDriverWait(driver, timeout).until(
        lambda current: bool(current.execute_script(
            "return Boolean(document.querySelector(arguments[0]))",
            selector,
        ))
    )


def _cards_script():
    """Read active job links and visible card text from the public listing."""
    return r"""
      const selector = 'a[href*="/jobs/"]';
      const rows = [];
      const seen = new Set();
      for (const link of document.querySelectorAll(selector)) {
        let url;
        try { url = new URL(link.href); } catch (_) { continue; }
        const parts = url.pathname.split("/").filter(Boolean);
        if (parts.length !== 2 || parts[0].toLowerCase() !== "jobs") continue;
        const id = parts[1];
        if (!id || seen.has(id)) continue;
        seen.add(id);

        let card = link;
        let cardText = (link.innerText || "").trim();
        let titleNode = link.querySelector("h1,h2,h3,h4,h5,h6,[class*='title']");
        for (let node = link.parentElement, depth = 0;
             node && depth < 10; node = node.parentElement, depth++) {
          const anchors = node.querySelectorAll(selector);
          if (anchors.length > 1) break;
          const text = (node.innerText || "").trim();
          if (text && text.length <= 9000) {
            card = node;
            cardText = text;
            titleNode = titleNode || node.querySelector(
              "h1,h2,h3,h4,h5,h6,[class*='title']"
            );
          }
        }
        rows.push({
          id,
          url: url.href,
          title: (titleNode?.innerText || "").trim(),
          text: cardText || (card.innerText || "").trim()
        });
      }
      return rows;
    """


def _detail_script():
    """Read visible job details, including the published description."""
    return r"""
      const main = document.querySelector("main,[role='main']") || document.body;
      return {
        title: (main.querySelector("h1")?.innerText ||
                document.querySelector("h1")?.innerText || "").trim(),
        text: (main.innerText || document.body?.innerText || "").trim(),
        description: (main.innerText || document.body?.innerText || "").trim()
      };
    """


def _lines(value):
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in str(value or "").splitlines()
        if line.strip()
    ]


def _card_base(card):
    """Accept only a unique detail link from Valorei's public job board."""
    if not isinstance(card, dict):
        return None
    parsed = urlsplit(str(card.get("url") or "").strip())
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() not in { "vagas.valorei.tech", "www.vagas.valorei.tech" }
    ):
        return None
    match = JOB_PATH_RE.fullmatch(parsed.path)
    if not match:
        return None
    native_id = match.group(1).strip()
    text = str(card.get("text") or "").strip()
    if not native_id or not text:
        return None
    return {
        "native_id": native_id,
        "url": f"{ORIGIN}/jobs/{native_id}",
        "title": str(card.get("title") or "").strip(),
        "text": text,
    }


def _infer_title(text):
    ignored = {
        *CATEGORY_LABELS,
        "clt", "pj", "associate", "associado", "remoto", "remote",
        "híbrido", "hibrido", "presencial", "ver vaga", "candidatar-se",
    }
    for line in _lines(text):
        folded = line.casefold().strip(":")
        if (
            folded in ignored
            or re.match(r"^(?:até\s+)?R\$", line, re.I)
            or re.match(r"^(?:há|ha)\s+\d+", line, re.I)
            or PUBLISHED_DATE_RE.search(line)
        ):
            continue
        if len(line) > 2:
            return line
    return ""


def _published_date(text):
    match = PUBLISHED_DATE_RE.search(str(text or ""))
    if not match:
        return ""
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _amount(value):
    normalized = str(value or "").replace(".", "").replace(",", ".")
    try:
        amount = float(normalized)
    except ValueError:
        return None
    return int(amount) if amount.is_integer() else amount


def _salary(text):
    match = SALARY_RE.search(str(text or ""))
    if not match:
        return None, None, None
    first = _amount(match.group("first"))
    second = _amount(match.group("second"))
    if match.group("cap") and second is None:
        return None, first, "BRL"
    if second is not None:
        return first, second, "BRL"
    return first, first, "BRL"


def _contract_types(text):
    header = "\n".join(_lines(text)[:6])
    return [
        label
        for label, pattern in CONTRACT_PATTERNS
        if re.search(pattern, header, re.I)
    ]


def _categories(text):
    for line in _lines(text)[:6]:
        category = CATEGORY_LABELS.get(line.casefold().strip())
        if category:
            return [category]
    return []


def _location(text, title):
    """Extract a Brazilian city/state from the card, not from narrative text."""
    lines = _lines(text)
    for line in lines:
        if line.casefold() == str(title or "").casefold():
            continue
        if re.search(r"R\$|\bver\s+vaga\b|\bpublicad[ao]\b", line, re.I):
            continue
        model = work_model_label(raw=line)
        if model == "remote":
            continue
        candidate = re.split(
            r"\s*[·•]\s*(?:h[ií]brido|presencial|on.site|in.office)\b",
            line,
            maxsplit=1,
            flags=re.I,
        )[0].strip(" ,·•")
        if not candidate or candidate.casefold() in CATEGORY_LABELS:
            continue
        state_match = re.search(
            r"(?:,\s*|\s)(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|"
            r"RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b",
            candidate,
            re.I,
        )
        known_location = is_brazil_location(candidate) or bool(state_match)
        if not known_location:
            continue
        parts = [part.strip() for part in candidate.split(",") if part.strip()]
        if state_match:
            city_parts = [
                part for part in parts
                if part.casefold() not in STATE_NAMES and part.upper() not in STATE_CODES
            ]
            city = city_parts[-1] if city_parts else ""
            return city, state_match.group(1).upper()
        if len(parts) >= 2 and parts[-1].casefold() in STATE_NAMES:
            return parts[-2], parts[-1]
        return parts[0] if parts else candidate, ""
    return "", ""


def _normalize_card(card, detail=None):
    """Map one public Valorei card and optional detail page to the shared schema."""
    base = _card_base(card)
    if not base:
        return None
    detail = detail if isinstance(detail, dict) else {}
    detail_text = str(detail.get("text") or "")
    card_text = base["text"]
    title = str(detail.get("title") or base["title"] or "").strip()
    title = title or _infer_title(card_text)
    if not title:
        return None

    full_text = "\n".join(part for part in (card_text, detail_text) if part)
    work_model = work_model_label(raw=card_text)
    if not work_model:
        work_model = work_model_label(raw=detail_text)
    city, state = _location(card_text, title)
    salary_min, salary_max, salary_currency = _salary(card_text)
    description = str(detail.get("description") or detail_text or card_text)
    levels = [
        label
        for label, pattern in LEVEL_PATTERNS
        if re.search(pattern, f"{title}\n{card_text}", re.I)
    ]
    return job(
        "valorei",
        base["native_id"],
        title=title,
        company="Valorei",
        url=base["url"],
        work_model=work_model,
        city=city,
        state=state,
        country="BR",
        market="BR",
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        published_date=_published_date(full_text),
        description=strip_html(description, limit=6000),
        levels=levels,
        categories=_categories(card_text),
        contract_types=_contract_types(card_text),
    )


def fetch(today=None):
    """Collect vacancies currently exposed on Valorei's public jobs listing.

    Selenium reads only the public listing and detail pages. Closed/unlisted jobs
    are excluded; an unavailable detail page never discards a visible listing.
    """
    del today  # The board already exposes its currently open vacancies.
    driver = _new_driver()
    try:
        driver.set_page_load_timeout(TIMEOUT_SECONDS)
        driver.get(JOBS_URL)
        _wait_for_element(driver, 'a[href*="/jobs/"]')
        cards = driver.execute_script(_cards_script())
        if not isinstance(cards, list) or not cards:
            raise RuntimeError("Valorei public page returned no public vacancies")

        rows = []
        seen = set()
        for card in cards[:PER_COMPANY]:
            base = _card_base(card)
            if not base or base["native_id"] in seen:
                continue
            seen.add(base["native_id"])
            detail = {}
            try:
                driver.get(base["url"])
                _wait_for_element(driver, "h1")
                payload = driver.execute_script(_detail_script())
                if isinstance(payload, dict):
                    detail = payload
            except Exception:
                # The listing is authoritative for active roles; keep its card
                # if the detail page is briefly unavailable.
                detail = {}
            row = _normalize_card(card, detail)
            if row:
                rows.append(row)
    finally:
        driver.quit()

    if not rows:
        raise RuntimeError("Valorei public page returned no valid vacancies")
    return rows
