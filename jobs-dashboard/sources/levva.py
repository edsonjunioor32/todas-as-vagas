# -*- coding: utf-8 -*-
"""Public Levva vacancies from the JavaScript-rendered IziRH board."""
import hashlib
import re
import time

from ._common import job, work_model_label


LIST_URL = "https://levva.izirh.io/explorar-vagas"
COMPANY = "Levva"
DETAIL_RE = re.compile(r"/visualizar-vaga/([0-9a-f-]{20,})", re.I)
_GENERIC_LOCATIONS = {"", "não informado", "nao informado", "brasil", "brazil"}
_CARD_SCRIPT = r"""
return Array.from(document.querySelectorAll("h6")).map((heading, index) => {
  let card = heading;
  for (let level = 0; level < 8 && card; level += 1) {
    if (card.querySelector('[aria-label="Cidade"],[aria-label="Tipo de trabalho"]')) break;
    card = card.parentElement;
  }
  if (!card) return null;
  const field = (label) => {
    const node = card.querySelector('[aria-label="' + label + '"]');
    return node ? (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim() : "";
  };
  return {
    index,
    title: (heading.innerText || heading.textContent || "").replace(/\s+/g, " ").trim(),
    city: field("Cidade"),
    model: field("Tipo de trabalho")
  };
}).filter(item => item && item.title);
"""


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _location(value):
    text = _clean(value)
    if text.casefold() in _GENERIC_LOCATIONS:
        return "Brasil", ""
    match = re.match(r"^(?P<state>[A-Za-z]{2})\s*-\s*(?P<city>.+)$", text)
    if match:
        return match.group("city").strip(), match.group("state").upper()
    return text, ""


def _model(value):
    normalized = _clean(value).casefold()
    if normalized in {"presencial ou remoto", "remoto ou presencial"}:
        return "hybrid"
    if normalized in {"híbrido", "hibrido", "hybrid"}:
        return "hybrid"
    if normalized in {"presencial", "on-site", "onsite"}:
        return "on-site"
    if normalized in {"remoto", "remote", "home office"}:
        return "remote"
    return work_model_label(raw=value)


def _stable_native_id(title, city, state, model):
    value = "|".join((_clean(title), _clean(city), _clean(state), _clean(model)))
    return "card-" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


def _rows_from_cards(cards):
    rows = []
    for item in cards or []:
        title = _clean(item.get("title"))
        if not title:
            continue
        city, state = _location(item.get("city"))
        model = _model(item.get("model"))
        if not model and city.casefold() not in {"brasil", "brazil"}:
            model = "on-site"
        native_id = str(item.get("native_id") or "").strip()
        if not native_id:
            native_id = _stable_native_id(title, city, state, model)
        url = _clean(item.get("url")) or LIST_URL
        rows.append(job(
            "levva",
            native_id,
            title,
            COMPANY,
            url,
            work_model=model,
            city=city,
            state=state,
            country="BR",
            market="BR",
        ))
    return rows


def _driver():
    try:
        from selenium import webdriver
    except ImportError as error:
        raise RuntimeError("Selenium is required for the Levva rendered careers page") from error

    options = webdriver.ChromeOptions()
    for argument in (
        "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--disable-gpu", "--disable-extensions", "--window-size=1440,3000",
        "--lang=pt-BR",
    ):
        options.add_argument(argument)
    options.page_load_strategy = "eager"
    return webdriver.Chrome(options=options)


def _card_rows(driver, timeout=60, previous_first=""):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = driver.execute_script(_CARD_SCRIPT)
        if rows and (not previous_first or rows[0].get("title") != previous_first):
            return rows
        time.sleep(1)
    raise RuntimeError("Levva did not render public vacancy cards")


def _page_number(driver, page):
    script = """
    const desired = String(arguments[0]);
    const buttons = Array.from(document.querySelectorAll("button"));
    const button = buttons.find(item => {
      const aria = (item.getAttribute("aria-label") || "").toLowerCase();
      return aria === "página " + desired ||
             aria === "ir para a página " + desired;
    });
    if (!button) return false;
    button.click();
    return true;
    """
    return bool(driver.execute_script(script, int(page)))


def _page_count(driver):
    return int(driver.execute_script(r"""
      return Math.max(1, ...Array.from(document.querySelectorAll("button"))
        .map(button => (button.getAttribute("aria-label") || "")
          .match(/p[aá]gina\s+(\d+)/i))
        .filter(Boolean)
        .map(match => Number(match[1])));
    """))


def _collect_detail_urls(driver, cards, page, first_title):
    result = []
    for index, card in enumerate(cards):
        title = _clean(card.get("title"))
        try:
            headings = driver.find_elements("css selector", "h6")
            if index >= len(headings):
                raise RuntimeError("card heading disappeared")
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
                headings[index],
            )
            deadline = time.monotonic() + 30
            detail_url = ""
            while time.monotonic() < deadline:
                candidate = str(driver.current_url or "")
                if DETAIL_RE.search(candidate):
                    detail_url = candidate
                    break
                time.sleep(0.5)
            if not detail_url:
                raise RuntimeError("detail route did not open")
            result.append({
                **card,
                "url": detail_url,
                "native_id": DETAIL_RE.search(detail_url).group(1),
            })
        except Exception as error:
            raise RuntimeError(
                f"Levva detail unavailable for {title or index}: {error}"
            ) from error
        finally:
            driver.get(LIST_URL)
            visible = _card_rows(driver)
            if page > 1:
                if not _page_number(driver, page):
                    raise RuntimeError(f"Levva page {page} button was not found")
                visible = _card_rows(driver, previous_first=visible[0].get("title", ""))
            if not visible or visible[0].get("title") != first_title:
                raise RuntimeError(
                    f"Levva returned to an unexpected page after {title or index}"
                )
    return result


def fetch():
    driver = _driver()
    rows = []
    try:
        driver.set_page_load_timeout(60)
        driver.get(LIST_URL)
        page = 1
        all_cards = []
        while True:
            cards = _card_rows(driver)
            first_title = cards[0].get("title", "")
            all_cards.extend(_collect_detail_urls(driver, cards, page, first_title))
            total_pages = _page_count(driver)
            if page >= total_pages:
                break
            if not _page_number(driver, page + 1):
                next_button = driver.find_element(
                    "css selector", 'button[aria-label="Ir para a próxima página"]'
                )
                if next_button.get_attribute("disabled"):
                    break
                next_button.click()
            _card_rows(driver, previous_first=first_title)
            page += 1
        rows = _rows_from_cards(all_cards)
    finally:
        driver.quit()
    if not rows:
        raise RuntimeError("Levva returned no recognizable public vacancy cards")
    return rows
