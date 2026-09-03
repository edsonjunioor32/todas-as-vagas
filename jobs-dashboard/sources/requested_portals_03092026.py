# -*- coding: utf-8 -*-
"""Company-level career feeds requested on 2026-09-03.

Individual Quickin job and application URLs identify the tenant that owns the
posting.  We register each tenant once and collect its complete public board,
so a single example URL never limits the company to one vacancy.
"""
import html
import re
import time
from datetime import date
from functools import partial
from urllib.parse import urljoin

from . import quickin as quickin_source
from . import requested_portals_27082026
from ._common import iso_date, job, strip_html, work_model_label


PANDAPE_URL = "https://minsaitbrasil.pandape.infojobs.com.br/"
PANDAPE_DETAIL_RE = re.compile(r"/Detail/(\d+)(?:[/?#]|$)", re.I)
PANDAPE_LOCATION_RE = re.compile(r"^(.+?)\s+-\s*([A-Z]{2})$", re.I)
PANDAPE_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
    "ene": 1, "feb": 2, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
PANDAPE_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+([a-z]{3,4})\b", re.I
)


def _new_pandape_driver():
    try:
        from selenium import webdriver
    except ImportError as error:
        raise RuntimeError("Selenium is required for the Minsait Pandapé feed") from error
    options = webdriver.ChromeOptions()
    for argument in (
        "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--disable-gpu", "--disable-extensions", "--window-size=1440,3000",
        "--lang=pt-BR",
    ):
        options.add_argument(argument)
    options.page_load_strategy = "eager"
    return webdriver.Chrome(options=options)


def _pandape_card_rows(driver):
    return driver.execute_script(
        """
        return [...document.querySelectorAll('a[href*="/Detail/"]')].map(anchor => {
          const heading = anchor.querySelector("h1,h2,h3,h4,h5,h6");
          return {
            href: anchor.href,
            title: (heading && (heading.innerText || heading.textContent) || "").trim(),
            text: (anchor.innerText || anchor.textContent || "").trim()
          };
        });
        """
    )


def _pandape_total(driver):
    text = driver.execute_script("return document.body ? document.body.innerText : '';") or ""
    match = re.search(r"\b(\d+)\s+(?:vagas?(?:\s+de\s+emprego)?|jobs?)\b", text, re.I)
    return int(match.group(1)) if match else 0


def _pandape_click_consent(driver):
    for button in driver.find_elements("tag name", "button"):
        label = re.sub(r"\s+", " ", button.text or "").strip()
        if re.fullmatch(r"(?:aceitar|agree and close)", label, re.I):
            try:
                driver.execute_script("arguments[0].click();", button)
            except Exception:
                pass
            return


def _pandape_more_button(driver):
    for button in driver.find_elements("tag name", "button"):
        label = re.sub(r"\s+", " ", button.text or "").strip()
        if re.search(r"(?:mostrar|show).*?(?:vagas?|jobs?)", label, re.I):
            return button
    return None


def _pandape_rendered_cards():
    driver = _new_pandape_driver()
    try:
        try:
            driver.set_page_load_timeout(65)
            driver.get(PANDAPE_URL)
        except Exception:
            # An eager page-load timeout can still leave a usable rendered DOM.
            pass
        deadline = time.monotonic() + 90
        previous_count = 0
        for _ in range(40):
            if time.monotonic() >= deadline:
                break
            _pandape_click_consent(driver)
            cards = _pandape_card_rows(driver)
            total = _pandape_total(driver)
            if not cards:
                time.sleep(1)
                continue
            if total and len(cards) >= total:
                break
            button = _pandape_more_button(driver)
            if button is None:
                break
            before = len(cards)
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", button
                )
                driver.execute_script("arguments[0].click();", button)
            except Exception:
                break
            for _ in range(20):
                time.sleep(0.5)
                if len(_pandape_card_rows(driver)) > before:
                    break
            current_count = len(_pandape_card_rows(driver))
            if current_count <= before or current_count == previous_count:
                break
            previous_count = current_count
        cards = _pandape_card_rows(driver)
        total = _pandape_total(driver)
        if not cards:
            raise RuntimeError("Pandapé/Minsait rendered no public vacancy cards")
        if total and len(cards) < total:
            raise RuntimeError(
                f"Pandapé/Minsait exposed only {len(cards)} of {total} public vacancies"
            )
        return cards
    finally:
        driver.quit()


def _pandape_date(text):
    match = PANDAPE_DATE_RE.search(text or "")
    if not match:
        return ""
    month = PANDAPE_MONTHS.get(match.group(2).casefold())
    if not month:
        return ""
    today = date.today()
    try:
        value = date(today.year, month, int(match.group(1)))
    except ValueError:
        return ""
    if value > today:
        value = value.replace(year=today.year - 1)
    return iso_date(value.isoformat())


def _pandape_contracts(text):
    values = []
    for label, pattern in (
        ("CLT", r"\b(?:efetivo\s*[–-]\s*)?clt\b"),
        ("Jovem Aprendiz", r"\bjovem aprendiz\b"),
        ("Temporário", r"\btempor[aá]ri[oa]\b"),
        ("Estágio", r"\best[aá]gio\b"),
    ):
        if re.search(pattern, text or "", re.I):
            values.append(label)
    return values


def _pandape_row(raw):
    url = html.unescape(str(raw.get("href") or "")).strip()
    match = PANDAPE_DETAIL_RE.search(url)
    if not match:
        return None
    text = str(raw.get("text") or "")
    title = strip_html(str(raw.get("title") or "")).strip()
    lines = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"[\r\n]+", text)
        if re.sub(r"\s+", " ", part).strip()
    ]
    if not title:
        title = lines[0] if lines else ""
    if not title or title.casefold() in {"exibir vaga", "view job"}:
        return None
    city, state = "", ""
    for line in lines[1:]:
        location = PANDAPE_LOCATION_RE.match(line)
        if location:
            city, state = location.group(1).strip(), location.group(2).upper()
            break
    return job(
        "minsait",
        match.group(1),
        title=title,
        company="Minsait Brasil",
        url=urljoin(PANDAPE_URL, url),
        work_model=work_model_label(raw=text),
        city=city or "Brasil",
        state=state,
        country="BR",
        market="BR",
        published_date=_pandape_date(text),
        description="",
        levels=list(dict.fromkeys(
            value.group(1).title()
            for value in re.finditer(
                r"\b(j[uú]nior|jr\.?|pleno|s[eê]nior|sr\.?|lead|especialista|"
                r"coordenador|gerente|trainee)\b",
                title,
                re.I,
            )
        )),
        categories=["Minsait Brasil"],
        contract_types=_pandape_contracts(text),
        pcd=bool(re.search(r"\bpcd\b|pessoa com deficiência", f"{title} {text}", re.I)),
    )


def fetch_minsait():
    rows = []
    seen = set()
    for raw in _pandape_rendered_cards():
        row = _pandape_row(raw)
        if row and row["native_id"] not in seen:
            seen.add(row["native_id"])
            rows.append(row)
    if not rows:
        raise RuntimeError("Pandapé/Minsait returned no public vacancies")
    return rows


def fetch_emphasys():
    return requested_portals_27082026._compleo_rows(
        "emphasys", "emphasys", "Emphasys IT Services"
    )


COMPANY_LABELS = {
    "acegaming": "Apostou",
    "addvisor": "Addvisor",
    "afonsofranca": "Afonso França",
    "ag3solutions": "AG3 Solutions",
    "agenciaf2f": "Agência F2F",
    "airessoares": "Aires Soares",
    "alifenino": "Alife Nino",
    "alyconsultoria": "ALY Consultoria",
    "am53": "AM53",
    "anerd": "A Nerd",
    "avanttibr": "Avantti",
    "bemcriar": "Bem Criar",
    "beyondhr": "Beyond HR",
    "brsupply": "BR Supply",
    "brwgroup": "BRW Group",
    "cdludi": "CD Ludi",
    "cgtech": "CG Tech",
    "ci": "CI",
    "conexgp": "CONEX",
    "cprocco": "Cprocco",
    "crhconsultoria": "CRH Consultoria",
    "crp": "CRP",
    "domvsit": "Domvs IT",
    "drhairfranchising": "Dr. Hair Franchising",
    "drhservicos": "DRH Serviços",
    "ehdesenvolvimentohumano": "EH Desenvolvimento Humano",
    "elaw": "eLaw",
    "escolacamb": "Escola Camba",
    "evertecinc": "Evertec Brasil",
    "evtit": "EVT",
    "extrafruti": "ExtraFruti",
    "felexrh": "Felex RH",
    "fitoag": "Fito Ag",
    "flynowdigital": "Flynow Digital",
    "fpdhconsultoria": "FPDH Consultoria",
    "futurach": "Futura Capital Humano",
    "gbase": "Gbase",
    "genica": "Genica",
    "gestaoinovada": "Gestão Inovada",
    "globalti": "Global TI",
    "graficamalires": "Gráfica Malires",
    "grupoepa": "Grupo EPA",
    "grupofenix": "Grupo Fênix",
    "grupolivemed": "Grupo Livemed",
    "grupowish": "Grupo Wish",
    "h2club": "H2 Club",
    "healthbit": "HealthBit",
    "hrin": "HRin",
    "humtech": "Humtech",
    "hyper": "Hyper",
    "iebtinovacao": "IEBT Inovação",
    "igma": "Igma",
    "imaginebeyond": "Imagine Beyond",
    "indiq": "Indiq",
    "infox": "Infox",
    "inoveben": "InoveBen",
    "iob": "IOB",
    "ipm": "IPM",
    "ittwoyou": "IT Two You",
    "jobi-hub": "Jobí Hub",
    "jobterceirizacao": "Job Terceirização",
    "klubi": "Klubi",
    "koria": "Koria",
    "lagoazuldistribuicao": "Lago Azul Distribuição",
    "lenarge": "Lenarge",
    "lifentechpeopleinnovation": "Life n Tech People Innovation",
    "lmveterinaria": "LM Veterinária",
    "ludwigpoloni": "Ludwig Poloni",
    "m2consult": "M2 Consult",
    "matec": "Matec",
    "matrizrh": "Matriz RH",
    "megabrasilrh": "Mega Brasil RH",
    "metododeconversao": "Método de Conversão",
    "metrisdho": "Metris DHO",
    "meutudo": "meutudo",
    "modaxo": "Modaxo",
    "mollicait": "Mollica IT",
    "moovgenteegestao": "Moov Gente e Gestão",
    "mperfetto": "M Perfetto",
    "nacaodigital": "Nação Digital",
    "nansen": "Nansen",
    "nddtech": "NDD Tech",
    "npwdigital": "NPW Digital",
    "peoplecapitalhumano": "People Capital Humano",
    "peoplemeet": "People Meet",
    "pipastudios": "Pipa Studios",
    "po2hc": "PO2HC",
    "prefeituramunicipaldexaxim": "Prefeitura Municipal de Xaxim",
    "prestorh": "Presto RH",
    "principiaskin": "Principia Skin",
    "prologapp": "Prolog App",
    "prosperi": "Prosperi",
    "r2ventures": "R2 Ventures",
    "rcstecnologia": "RCS Tecnologia",
    "recrutify": "Recrutify",
    "relourh": "Relou RH",
    "reply": "Reply",
    "reponto": "Reponto",
    "resfriar": "Resfriar",
    "rhgrandestalentos": "RH Grandes Talentos",
    "rhshopping": "RH Shopping",
    "rhville": "RH Ville",
    "rodriguesassessoria": "Rodrigues Assessoria",
    "sacavalcante": "Sá Cavalcante",
    "salesimpact": "Sales Impact",
    "salesleadersgroup": "Sales Leaders Group",
    "sapiens": "Sapiens",
    "saulopedrosocoach": "Saulo Pedroso Coach",
    "seidor": "SEIDOR",
    "selbetti": "Selbetti",
    "sinqia": "Sinqia",
    "sioux": "Sioux",
    "snd": "SND",
    "sougrupodj": "Sou Grupo DJ",
    "soulemure": "Soulemure",
    "stetsom": "Stetsom",
    "supergirodistribuidora": "Super Giro Distribuidora",
    "tagna": "Tagna",
    "talentworksrh": "Talent Works RH",
    "tatianalisehumana": "Tatiana Lise Humana",
    "tec2cloud": "Tec2Cloud",
    "tecadi": "Tecadi",
    "tecnocomp": "Tecnocomp",
    "telesilengenharia": "Telesil Engenharia",
    "thesgp": "The SGP",
    "topmed": "TopMed",
    "topmind": "TopMind",
    "toptalent": "Top Talent",
    "trivenhraasconsultoriagestaoestrategica": "Triven HR AAS Consultoria e Gestão Estratégica",
    "uniflexgroup": "Uniflex Group",
    "vagasautomotivas": "Vagas Automotivas",
    "vagasconsultoria": "Vagas Consultoria",
    "verity": "Verity",
    "verus": "Verus",
    "viabilizenegocios": "Viabilize Negócios",
    "vitaedesenvolvimento": "Vitae Desenvolvimento",
    "voerh": "VOE RH",
    "weemais": "WeeMais",
    "workrequest": "Work Request",
    "yukaline": "Yuka Line"
}

QUICKIN_TENANTS = [
    "meutudo",
    "igma",
    "verity",
    "jobi-hub",
    "relourh",
    "futurach",
    "healthbit",
    "salesleadersgroup",
    "verus",
    "avanttibr",
    "flynowdigital",
    "evtit",
    "agenciaf2f",
    "addvisor",
    "acegaming",
    "rhgrandestalentos",
    "topmind",
    "domvsit",
    "hrin",
    "conexgp",
    "tagna",
    "tecnocomp",
    "salesimpact",
    "iob",
    "infox",
    "seidor",
    "sioux",
    "megabrasilrh",
    "rhshopping",
    "sinqia",
    "recrutify",
    "beltis",
    "conscer",
    "nddtech",
    "grupofenix",
    "r2ventures",
    "drhairfranchising",
    "trivenhraasconsultoriagestaoestrategica",
    "evertecinc",
    "assefaz",
    "metrisdho",
    "grupoepa",
    "koria",
    "prologapp",
    "ipm",
    "modaxo",
    "brwgroup",
    "iebtinovacao",
    "weemais",
    "tec2cloud",
    "grupolivemed",
    "talentworksrh",
    "sacavalcante",
    "beyondhr",
    "h2club",
    "reply",
    "peoplemeet",
    "imaginebeyond",
    "elaw",
    "bymomagroup",
    "ehdesenvolvimentohumano",
    "npwdigital",
    "matec",
    "nansen",
    "divinavaga",
    "felexrh",
    "fpdhconsultoria",
    "anerd",
    "supergirodistribuidora",
    "cadmus",
    "inoveben",
    "matrizrh",
    "lmveterinaria",
    "connectforpeople",
    "fitoag",
    "principiaskin",
    "ci",
    "hyper",
    "graficamalires",
    "alifenino",
    "grupowish",
    "airessoares",
    "klubi",
    "humtech",
    "am53",
    "selbetti",
    "tecadi",
    "prosperi",
    "diskpan",
    "peoplecapitalhumano",
    "arauz",
    "escolacamb",
    "metododeconversao",
    "yukaline",
    "cprocco",
    "rodriguesassessoria",
    "rhville",
    "po2hc",
    "viabilizenegocios",
    "prefeituramunicipaldexaxim",
    "carone",
    "globalti",
    "soulemure",
    "lifentechpeopleinnovation",
    "workrequest",
    "pipastudios",
    "brsupply",
    "gbase",
    "afonsofranca",
    "tatianalisehumana",
    "moovgenteegestao",
    "rcstecnologia",
    "lenarge",
    "crhconsultoria",
    "lagoazuldistribuicao",
    "stetsom",
    "saulopedrosocoach",
    "bemcriar",
    "cgtech",
    "reponto",
    "snd",
    "mollicait",
    "topmed",
    "evangelizar",
    "indiq",
    "vagasconsultoria",
    "telesilengenharia",
    "toptalent",
    "drhservicos",
    "m2consult",
    "crp",
    "ittwoyou",
    "uniflexgroup",
    "ludwigpoloni",
    "cdludi",
    "voerh",
    "sapiens",
    "mperfetto",
    "extrafruti",
    "alyconsultoria",
    "vagasautomotivas",
    "jobterceirizacao",
    "resfriar",
    "sougrupodj",
    "thesgp",
    "nacaodigital",
    "vitaedesenvolvimento",
    "ag3solutions",
    "prestorh",
    "genica",
    "gestaoinovada"
]


def _company_label(tenant):
    return COMPANY_LABELS.get(
        tenant,
        re.sub(r"[-_]+", " ", tenant).strip().title(),
    )


def _fetch_quickin_company(tenant, company):
    return quickin_source.fetch_company(
        tenant,
        source=tenant,
        company=company,
    )


QUICKIN_TARGETS = tuple(
    (
        tenant,
        partial(_fetch_quickin_company, tenant, _company_label(tenant)),
    )
    for tenant in QUICKIN_TENANTS
)


TARGETS = (
    ("minsait", fetch_minsait),
    ("emphasys", fetch_emphasys),
) + QUICKIN_TARGETS
