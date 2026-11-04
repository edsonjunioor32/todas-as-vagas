# -*- coding: utf-8 -*-
"""
Coleta isolada de vagas públicas do LinkedIn, sem filtro por tipo de candidatura.
Projetado para rodar localmente ou via GitHub Actions para o projeto 'Todas as Vagas'.
Estratégia aberta e não-restritiva: coleta ampla em todo o Brasil (presencial, híbrida
e remota) sem depender de listas fixas de palavras-chave.
"""

import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit


# Limites operacionais da coleta aberta. JobSpy aceita offset para continuar
# a busca; usamos lotes controlados para ultrapassar o primeiro resultado sem
# criar uma consulta ilimitada ou concentrar todas as requisições em uma única chamada.
DEFAULT_RESULTS_LIMIT = 1000
DEFAULT_REMOTE_RESULTS_LIMIT = 1200
JOBSPY_MAX_RESULTS_PER_QUERY = 1000
MAX_UNIQUE_RESULTS_PER_RUN = 1200
# Verified against LinkedIn screenshots supplied on 2026-11-03.
VERIFIED_WORKPLACE_OVERRIDES = {
    "4486898930": "remote",
    "4478138443": "on-site",
    "4479109326": "remote",
}
VERIFIED_APPLICATION_OVERRIDES = {
    # User screenshot on 2026-11-03 shows "Candidatura simplificada".
    "4479109326": ("easy_apply", True, "user_screenshot_2026-11-03"),
}
CAPTURED_LINKEDIN_WORKPLACE = {}
CAPTURED_LINKEDIN_APPLICATION = {}
DEFAULT_HOURS_OLD = 1440
JOBSPY_BATCH_SIZE = 100

# Importações condicionais para permitir que módulos de validação/testes importem
# funções utilitárias (ex: normalize_linkedin_job) mesmo em ambientes de CI leves
# onde pandas e jobspy não estão instalados no catálogo principal.
try:
    import pandas as pd
except ImportError:
    pd = None

def _workplace_type_from_text(value):
    """Converte o selo de modalidade da página do LinkedIn para o modelo interno."""
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    if not text:
        return ""
    if re.search(r"\b(remote|remoto|home office|work from home|wfh|teletrabalho)\b", text):
        return "remote"
    if re.search(r"\b(hybrid|híbrido|hibrido)\b", text):
        return "hybrid"
    if re.search(r"\b(on[\s-]?site|onsite|presencial|in office|no escritório|no escritorio)\b", text):
        return "on-site"
    return ""


class _WorkplaceInsightParser(HTMLParser):
    """Extrai texto apenas dos elementos de insight/modalidade do cartão da vaga."""
    _MARKERS = ("job-insight", "workplace", "work-from-home")
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._active_depth = 0
        self._buffer = []
        self.insights = []

    def handle_starttag(self, tag, attrs):
        attributes = {
            str(name).casefold(): str(value or "")
            for name, value in attrs
        }
        marker_text = " ".join(
            attributes.get(name, "")
            for name in ("class", "data-test-id", "data-testid", "aria-label")
        ).casefold()
        is_container = (
            any(marker in marker_text for marker in self._MARKERS)
            or bool(_workplace_type_from_text(attributes.get("aria-label")))
        )
        if str(tag).casefold() in self._VOID_TAGS:
            return
        if self._active_depth:
            self._active_depth += 1
        elif is_container:
            self._active_depth = 1
            self._buffer = []

    def handle_data(self, data):
        if self._active_depth:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if str(tag).casefold() in self._VOID_TAGS:
            return
        if not self._active_depth:
            return
        self._active_depth -= 1
        if self._active_depth == 0:
            text = " ".join(self._buffer)
            if text.strip():
                self.insights.append(text)
            self._buffer = []


def _extract_workplace_type_from_html(html):
    """Lê Remote/Hybrid/On-site no cartão público da vaga, sem usar a descrição."""
    if not html:
        return ""
    parser = _WorkplaceInsightParser()
    try:
        parser.feed(str(html))
        parser.close()
    except Exception:
        return ""
    for insight in parser.insights:
        workplace_type = _workplace_type_from_text(insight)
        if workplace_type:
            return workplace_type
    return ""


_APPLICATION_EASY_APPLY_RE = re.compile(
    r"\b(?:easy\s*apply|inapply|candidatura\s+simplificada|"
    r"aplicacao\s+simplificada|candidature\s+simplifiee|solicitud\s+sencilla)\b"
)
_APPLICATION_CTA_RE = re.compile(
    r"\b(?:apply|application|candidat\w*|candidate|inscrev\w*|submit)\b"
)
_APPLICATION_EXTERNAL_MARKERS = (
    r"\b(?:external\s+application|apply\s+externally|"
    r"apply\s+outside\s+(?:linkedin|the\s+platform))\b",
    r"\bapply\s+(?:on|via|through)\s+(?:the\s+)?"
    r"(?:company|employer)(?:'s)?\s+(?:website|site|portal)\b",
    r"\b(?:candidatura\s+externa|candidatar\s+se\s+externamente|"
    r"candidate\s+se\s+externamente)\b",
    r"\b(?:candidatar\s+se|candidate\s+se|inscreva\s+se|inscrever\s+se)\s+"
    r"(?:no|na|pelo|pela|atraves\s+(?:do|da))\s+"
    r"(?:site|portal)\s+(?:da|do)\s+empresa\b",
    r"\b(?:inscreva\s+se|candidate\s+se|candidatar\s+se)\s+diretamente\s+"
    r"(?:no|na)\s+(?:site|portal)\s+(?:da|do)\s+empresa\b",
)
_APPLICATION_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


def _normalize_application_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


class _ApplicationCTAParser(HTMLParser):
    """Captures text/attributes from apply controls, never from job prose."""

    _CONTROL_TAGS = {"a", "button"}
    _CONTROL_MARKERS = ("apply", "application", "candidate")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._elements = []
        self._active_controls = []
        self.controls = []

    def handle_starttag(self, tag, attrs):
        tag_name = str(tag).casefold()
        attributes = {
            str(name).casefold(): str(value or "")
            for name, value in attrs
        }
        markers = " ".join(
            attributes.get(name, "")
            for name in (
                "class", "data-control-name", "data-test-id", "data-testid",
                "aria-label", "title", "role",
            )
        ).casefold()
        is_control = (
            tag_name in self._CONTROL_TAGS
            or attributes.get("role", "").casefold() == "button"
            or any(marker in markers for marker in self._CONTROL_MARKERS)
        )
        control = {
            "tag": tag_name,
            "attributes": attributes,
            "text": [],
        } if is_control else None
        if control:
            self._active_controls.append(control)
        if tag_name not in _APPLICATION_VOID_TAGS:
            self._elements.append({"tag": tag_name, "control": control})
        elif control:
            self._finish_control(control)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if str(tag).casefold() not in _APPLICATION_VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data):
        for control in self._active_controls:
            control["text"].append(data)

    def handle_endtag(self, tag):
        tag_name = str(tag).casefold()
        for index in range(len(self._elements) - 1, -1, -1):
            if self._elements[index]["tag"] != tag_name:
                continue
            closing = self._elements[index:]
            del self._elements[index:]
            for element in reversed(closing):
                control = element["control"]
                if control:
                    self._finish_control(control)
            return

    def _finish_control(self, control):
        for index in range(len(self._active_controls) - 1, -1, -1):
            if self._active_controls[index] is control:
                del self._active_controls[index]
                break
        self.controls.append(control)


def _is_verified_external_apply_url(value):
    try:
        url = str(value or "").strip()
        parsed = urlsplit("https:" + url if url.startswith("//") else url)
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme.casefold() not in {"http", "https"} or not host:
        return False
    # LinkedIn short links are not proof of the final employer destination.
    linkedin_hosts = ("linkedin.com", "linkedin.cn", "lnkd.in")
    if any(host == domain or host.endswith("." + domain) for domain in linkedin_hosts):
        return False
    return True


def _extract_application_evidence_from_html(html):
    """Classify a job only from explicit application controls in its detail HTML."""
    unknown = ("unknown", False, "no_public_evidence")
    if not html:
        return unknown

    parser = _ApplicationCTAParser()
    try:
        parser.feed(str(html))
        parser.close()
    except Exception:
        return unknown

    signals = set()
    evidence = set()
    for control in parser.controls:
        attributes = control["attributes"]
        label = _normalize_application_text(
            " ".join(
                control["text"]
                + [
                    attributes.get(name, "")
                    for name in (
                        "aria-label", "title", "data-control-name",
                        "data-test-id", "data-testid", "class",
                    )
                ]
            )
        )
        if _APPLICATION_EASY_APPLY_RE.search(label):
            signals.add("easy_apply")
            evidence.add("easy_apply_badge")

        explicit_external = any(
            re.search(pattern, label) for pattern in _APPLICATION_EXTERNAL_MARKERS
        )
        external_link = (
            bool(_APPLICATION_CTA_RE.search(label))
            and _is_verified_external_apply_url(attributes.get("href"))
        )
        if explicit_external:
            signals.add("external")
            evidence.add("external_apply_marker")
        elif external_link:
            signals.add("external")
            evidence.add("external_apply_link")

    if len(signals) > 1:
        return ("unknown", False, "conflicting_signals")
    if signals == {"easy_apply"}:
        return ("easy_apply", True, "easy_apply_badge")
    if signals == {"external"}:
        evidence_type = (
            "external_apply_marker"
            if "external_apply_marker" in evidence
            else "external_apply_link"
        )
        return ("external", True, evidence_type)
    return unknown


_EXPLICIT_WORKPLACE_PATTERNS = {
    "remote": (
        r"\b100\s*%\s*(?:remot[oa]|home[\s-]?office)\b",
        r"\bfully[\s-]+remote\b",
        r"\b(?:regime|modalidade|modelo)(?:\s+de\s+trabalho)?\s*[:\-]?\s*(?:remot[oa]|home[\s-]?office)\b",
        r"\bworkplace type\s*[:\-]\s*remote\b",
    ),
    "hybrid": (
        r"\b(?:regime|modalidade|modelo)(?:\s+de\s+trabalho)?\s*[:\-]?\s*h[ií]brid[oa]\b",
        r"\bworkplace type\s*[:\-]\s*hybrid\b",
    ),
    "on-site": (
        r"\b100\s*%\s*presencial\b",
        r"\b(?:regime|modalidade|modelo)(?:\s+de\s+trabalho)?\s*[:\-]?\s*presencial\b",
        r"\bworkplace type\s*[:\-]\s*on[\s-]?site\b",
        r"\bon[\s-]?site\s+(?:role|position|work|workplace|model)\b",
    ),
}


def _explicit_workplace_type_from_description(description):
    """Classifica somente declarações textuais explícitas e não ambíguas."""
    text = re.sub(r"\s+", " ", str(description or "")).strip().casefold()
    if not text:
        return ""

    mentioned = set()
    if re.search(r"\b(?:remot[oa]|home[\s-]?office|fully[\s-]+remote)\b", text):
        mentioned.add("remote")
    if re.search(r"\b(?:h[ií]brid[oa]|hybrid)\b", text):
        mentioned.add("hybrid")
    if re.search(r"\b(?:presencial|on[\s-]?site|onsite)\b", text):
        mentioned.add("on-site")
    if len(mentioned) > 1:
        return ""

    matches = [
        workplace_type
        for workplace_type, patterns in _EXPLICIT_WORKPLACE_PATTERNS.items()
        if any(re.search(pattern, text) for pattern in patterns)
    ]
    return matches[0] if len(matches) == 1 else ""


def _is_linkedin_job_detail_url(url, job_id):
    """Recognize a LinkedIn job-detail URL regardless of query or trailing slash."""
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return False

    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme.casefold() not in {"http", "https"} or not hostname:
        return False
    if hostname != "linkedin.com" and not hostname.endswith(".linkedin.com"):
        return False

    match = re.fullmatch(r"/jobs/view/(\d+)/?", parsed.path, re.IGNORECASE)
    return bool(match and match.group(1) == str(job_id))


def _fetch_details_with_workplace_capture(session, job_id, fetch_details):
    """Capture and parse the detail response used by JobSpy itself."""
    captured = {}
    job_key = str(job_id or "").strip()
    if job_key:
        CAPTURED_LINKEDIN_WORKPLACE.pop(job_key, None)
        CAPTURED_LINKEDIN_APPLICATION.pop(job_key, None)
    original_get = session.get

    def _capture_get(url, *args, **kwargs):
        response = original_get(url, *args, **kwargs)
        response_url = getattr(response, "url", "")
        if response_url and _is_linkedin_job_detail_url(response_url, job_id):
            captured["html"] = getattr(response, "text", "")
        return response

    session.get = _capture_get
    try:
        details = fetch_details() or {}
    finally:
        session.get = original_get

    html = captured.get("html", "")
    workplace_type = _extract_workplace_type_from_html(html)
    if job_key and workplace_type:
        CAPTURED_LINKEDIN_WORKPLACE[job_key] = workplace_type
    if job_key:
        CAPTURED_LINKEDIN_APPLICATION[job_key] = (
            _extract_application_evidence_from_html(html)
        )
    return details


try:
    from jobspy import scrape_jobs
    from jobspy.linkedin import LinkedIn
    import jobspy.linkedin as jl

    # Patch JobSpy's LinkedIn scraper to support remote workplace filtering (f_WT=2)
    # Permite busca remota dedicada sem cookies, login ou serviços pagos
    _orig_linkedin_search_params = LinkedIn._search_params

    def _patched_linkedin_search_params(self):
        params = _orig_linkedin_search_params(self)
        if getattr(self.scraper_input, "is_remote", False):
            params["f_WT"] = "2"
        return params

    LinkedIn._search_params = _patched_linkedin_search_params

    # Configura atraso adaptativo entre páginas (2.5s a 3.0s) para evitar 429
    LinkedIn.delay = (2.5, 3.0)


    # O JobSpy já abre a página de detalhes quando fetch_description=True.
    # Capturamos o HTML dessa mesma requisição para ler o selo de modalidade,
    # evitando uma segunda chamada à vaga e sem depender de login/cookies.
    _orig_linkedin_fetch_details = LinkedIn._fetch_details

    def _patched_linkedin_fetch_details(self, job_id):
        return _fetch_details_with_workplace_capture(
            self.session,
            job_id,
            lambda: _orig_linkedin_fetch_details(self, job_id),
        )

    LinkedIn._fetch_details = _patched_linkedin_fetch_details

    # Interceptador resiliente para tratar HTTP 429 com backoff exponencial e Retry-After
    if hasattr(jl, "create_session"):
        _orig_create_session = jl.create_session

        def _resilient_create_session(session, scraper_input, headers=None):
            sess = _orig_create_session(session, scraper_input, headers)
            orig_get = sess.get

            def _resilient_get(url, *args, **kwargs):
                max_retries = 3
                for attempt in range(max_retries):
                    resp = orig_get(url, *args, **kwargs)
                    if resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after and retry_after.strip().isdigit():
                            wait_time = float(retry_after.strip())
                        else:
                            wait_time = float(min(45.0, 5.0 * (2 ** attempt)))
                        print(
                            f"  [LinkedIn Throttling] HTTP 429 detectado no start={kwargs.get('params', {}).get('start', '?')}. "
                            f"Aplicando backoff de {wait_time:.1f}s (tentativa {attempt + 1}/{max_retries})..."
                        )
                        time.sleep(wait_time)
                        continue
                    return resp
                return resp

            sess.get = _resilient_get
            return sess

        jl.create_session = _resilient_create_session
except ImportError:
    scrape_jobs = None
    LinkedIn = None


def clean_value(val):
    """Limpa nulos e tipos não serializáveis."""
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return ""
    if pd is not None and pd.isna(val):
        return ""
    if str(val) in ("NaT", "nan", "NaN"):
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def normalize_linkedin_job(raw_job, is_remote_search=False):
    """
    Converte o registro bruto do JobSpy para a estrutura padronizada
    do projeto 'Todas as Vagas'.
    """
    raw_url = clean_value(raw_job.get("job_url")) or ""
    native_id = clean_value(raw_job.get("id")) or ""
    job_id = None
    if "view/" in raw_url:
        job_id = raw_url.split("view/")[1].split("/")[0].split("?")[0]
    elif native_id:
        job_id = str(native_id).replace("li-", "")

    if job_id:
        url = f"https://www.linkedin.com/jobs/view/{job_id}"
        native_id = f"li-{job_id}"
    else:
        url = raw_url

    title = clean_value(raw_job.get("title")) or "Vaga sem título"
    company = clean_value(raw_job.get("company")) or "Empresa não informada"
    location = clean_value(raw_job.get("location")) or "Brazil"

    # Só aceitamos o selo capturado na página individual, um caso manual
    # documentado ou uma declaração explícita e inequívoca na descrição.
    workplace_type = CAPTURED_LINKEDIN_WORKPLACE.get(str(job_id or ""))
    workplace_evidence = "linkedin_badge" if workplace_type else ""
    if not workplace_type:
        workplace_type = VERIFIED_WORKPLACE_OVERRIDES.get(str(job_id or ""))
        if workplace_type:
            workplace_evidence = "manual_override"
    if not workplace_type:
        workplace_type = _explicit_workplace_type_from_description(
            raw_job.get("description")
        )
        if workplace_type:
            workplace_evidence = "description_explicit"

    application_type, application_verified, application_evidence = (
        CAPTURED_LINKEDIN_APPLICATION.get(
            str(job_id or ""), ("unknown", False, "no_public_evidence")
        )
    )
    if str(job_id or "") in VERIFIED_APPLICATION_OVERRIDES:
        application_type, application_verified, application_evidence = (
            VERIFIED_APPLICATION_OVERRIDES[str(job_id)]
        )

    # Data de publicação
    date_posted = clean_value(raw_job.get("date_posted")) or ""
    if date_posted and "T" not in str(date_posted):
        date_posted = f"{date_posted}T00:00:00Z"

    # Salário
    min_amount = clean_value(raw_job.get("min_amount"))
    max_amount = clean_value(raw_job.get("max_amount"))
    currency = clean_value(raw_job.get("currency")) or "BRL"

    return {
        "source": "linkedin",
        "sourceLabel": "LinkedIn",
        "native_id": str(native_id),
        "title": str(title).strip(),
        "company": str(company).strip(),
        "url": url,
        "location": location,
        "workplaceType": workplace_type,
        "workplaceVerified": bool(workplace_type),
        "workplaceEvidence": workplace_evidence,
        "applicationType": application_type,
        "applicationVerified": application_verified,
        "applicationEvidence": application_evidence,
        "publishedAt": date_posted,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "salaryMin": float(min_amount) if min_amount else None,
        "salaryMax": float(max_amount) if max_amount else None,
        "currency": currency if (min_amount or max_amount) else None,
        # A descrição não é publicada neste snapshot; é usada apenas para enriquecer o JobSpy.
        "description": "",
    }



def _raw_linkedin_job_key(raw):
    """Build a tracking-independent key for one LinkedIn ad."""
    native_id = str(clean_value(raw.get("id")) or "").strip()
    if native_id:
        return f"id:{native_id.casefold().removeprefix('li-')}"

    raw_url = str(clean_value(raw.get("job_url")) or "").strip()
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        parsed = None
    if parsed:
        match = re.fullmatch(r"/jobs/view/(\d+)/?", parsed.path, re.IGNORECASE)
        if match:
            return f"id:{match.group(1)}"
        if parsed.hostname:
            return (
                f"url:{parsed.hostname.casefold().rstrip('.')}:{parsed.path.rstrip('/')}"
            )

    title = str(clean_value(raw.get("title")) or "").strip().casefold()
    company = str(clean_value(raw.get("company")) or "").strip().casefold()
    location = str(clean_value(raw.get("location")) or "").strip().casefold()
    return f"fallback:{title}::{company}::{location}"


def _scrape_jobs_in_pages(
    *, results_limit, max_results=JOBSPY_MAX_RESULTS_PER_QUERY, coverage=None, **kwargs
):
    """Paginate within one query budget; enforce the unique-run cap after deduplication."""
    requested_target = max(0, int(results_limit))
    pass_budget = max(0, int(max_results))
    query_target = min(requested_target, JOBSPY_MAX_RESULTS_PER_QUERY)
    target = min(query_target, pass_budget)
    clamped_by_query_limit = requested_target > JOBSPY_MAX_RESULTS_PER_QUERY
    clamped_by_pass_budget = query_target > pass_budget

    if target == 0:
        if coverage is not None:
            coverage.update({
                "requested_limit": requested_target,
                "effective_limit": 0,
                "pass_budget": pass_budget,
                "clamped_by_query_limit": clamped_by_query_limit,
                "clamped_by_pass_budget": clamped_by_pass_budget,
                "returned": 0,
                "pages": 0,
                "source_exhausted": True,
                "stopped_without_progress": False,
                "limit_reached": False,
            })
        return []

    batch_size = min(JOBSPY_BATCH_SIZE, target)
    max_pages = math.ceil(target / batch_size)
    records = []
    seen_keys = set()
    page_count = 0
    source_exhausted = False
    stopped_without_progress = False

    for page_number in range(max_pages):
        offset = page_number * batch_size
        page_kwargs = dict(kwargs)
        page_kwargs["results_wanted"] = min(batch_size, target - offset)
        page_kwargs["offset"] = offset
        print(
            f"  -> Lote {page_number + 1}/{max_pages} "
            f"(offset={offset}, limite={page_kwargs['results_wanted']})"
        )
        df = scrape_jobs(**page_kwargs)
        page_count += 1
        if df is None or df.empty:
            source_exhausted = True
            break

        batch = df.to_dict(orient="records")
        if not batch:
            source_exhausted = True
            break

        new_records = 0
        for raw in batch:
            key = _raw_linkedin_job_key(raw)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            records.append(raw)
            new_records += 1

        print(
            f"     Página retornou {len(batch)} vagas brutas; "
            f"{new_records} novas; total único acumulado={len(records)}."
        )

        if len(batch) < page_kwargs["results_wanted"]:
            source_exhausted = True
            break
        if new_records == 0:
            stopped_without_progress = True
            break
        if page_number < max_pages - 1:
            time.sleep(2)

    collected = records[:target]
    # Atingir todas as páginas da janela pedida é um limite mesmo se
    # deduplicação reduzir a quantidade única abaixo do alvo.
    limit_reached = (
        page_count >= max_pages
        and not source_exhausted
        and not stopped_without_progress
    )
    if coverage is not None:
        coverage.update({
            "requested_limit": requested_target,
            "effective_limit": target,
            "pass_budget": pass_budget,
            "clamped_by_query_limit": clamped_by_query_limit,
            "clamped_by_pass_budget": clamped_by_pass_budget,
            "returned": len(collected),
            "pages": page_count,
            "source_exhausted": source_exhausted,
            "stopped_without_progress": stopped_without_progress,
            "limit_reached": limit_reached,
        })
    return collected


def collect_linkedin(
    terms=None,
    location="Brazil",
    results_limit=DEFAULT_RESULTS_LIMIT,
    remote_results_limit=DEFAULT_REMOTE_RESULTS_LIMIT,
    hours_old=DEFAULT_HOURS_OLD,
    out_path="docs/data/linkedin_vagas.json",
    include_remote_pass=True,
):
    if scrape_jobs is None:
        raise RuntimeError("A biblioteca 'python-jobspy' é necessária para executar collect_linkedin")

    requested_general_limit = max(0, int(results_limit))
    requested_remote_limit = max(0, int(remote_results_limit))
    CAPTURED_LINKEDIN_WORKPLACE.clear()
    CAPTURED_LINKEDIN_APPLICATION.clear()
    print("=== [LinkedIn Jobs Collector] Iniciando coleta pública aberta ===")
    print(
        f"Critérios: Localização='{location}', Horas={hours_old} "
        f"(~{hours_old//24} dias), sem filtro por candidatura."
    )
    print(
        f"[Limites] Geral solicitado={requested_general_limit}; "
        f"remota complementar solicitada={requested_remote_limit if include_remote_pass else 0}; "
        f"máximo por consulta={JOBSPY_MAX_RESULTS_PER_QUERY}; "
        f"teto agregado={MAX_UNIQUE_RESULTS_PER_RUN} vagas únicas."
    )

    all_jobs_dict = {}
    collection_errors = []
    pass_coverage = []

    def scrape_pass(name, limit, **kwargs):
        coverage = {}
        remaining_unique_before_pass = (
            MAX_UNIQUE_RESULTS_PER_RUN - len(all_jobs_dict)
        )
        records = _scrape_jobs_in_pages(
            results_limit=limit,
            max_results=JOBSPY_MAX_RESULTS_PER_QUERY,
            coverage=coverage,
            **kwargs,
        )
        coverage["name"] = name
        coverage["remaining_unique_before_pass"] = remaining_unique_before_pass
        pass_coverage.append(coverage)

        if coverage["effective_limit"] < coverage["requested_limit"]:
            reasons = []
            if coverage["clamped_by_query_limit"]:
                reasons.append(
                    f"limite por consulta ({JOBSPY_MAX_RESULTS_PER_QUERY})"
                )
            if coverage["clamped_by_pass_budget"]:
                reasons.append(
                    f"orçamento da busca ({coverage['pass_budget']})"
                )
            print(
                f"  [Aviso] Busca '{name}': solicitado="
                f"{coverage['requested_limit']}, efetivo="
                f"{coverage['effective_limit']} ({' e '.join(reasons)})."
            )
        if coverage.get("limit_reached"):
            print(
                f"  [Aviso] A busca '{name}' atingiu seu limite efetivo de "
                f"{coverage['effective_limit']} resultados; podem existir "
                f"vagas fora do lote consultado."
            )
        if coverage.get("stopped_without_progress"):
            print(
                f"  [Aviso] A busca '{name}' parou sem novos IDs; cobertura potencialmente incompleta."
            )
        return records

    def add_records(records, *, is_remote_search, pass_name):
        added = 0
        duplicates = 0
        skipped_after_unique_cap = 0
        for index, raw in enumerate(records):
            if len(all_jobs_dict) >= MAX_UNIQUE_RESULTS_PER_RUN:
                skipped_after_unique_cap = len(records) - index
                break
            normalized = normalize_linkedin_job(
                raw, is_remote_search=is_remote_search
            )
            job_key = (
                normalized["native_id"]
                or normalized["url"]
                or f"{normalized['title']}::{normalized['company']}::{normalized['location']}"
            ).casefold()
            if job_key in all_jobs_dict:
                duplicates += 1
                continue
            all_jobs_dict[job_key] = normalized
            added += 1
        coverage = pass_coverage[-1] if pass_coverage else None
        if coverage is not None:
            coverage.update({
                "added_unique": added,
                "duplicates": duplicates,
                "skipped_after_unique_cap": skipped_after_unique_cap,
                "unique_count_after": len(all_jobs_dict),
                "unique_cap_reached": len(all_jobs_dict) >= MAX_UNIQUE_RESULTS_PER_RUN,
            })
        print(
            f"  -> Busca '{pass_name}': {added} novos anúncios únicos; "
            f"{duplicates} duplicatas; total agregado={len(all_jobs_dict)}."
        )

    if terms:
        print(f"[Modo Direcionado] Consultando termos específicos ({len(terms)}): {terms}")
        for i, term in enumerate(terms, 1):
            if len(all_jobs_dict) >= MAX_UNIQUE_RESULTS_PER_RUN:
                print(
                    f"  [Aviso] Teto agregado de {MAX_UNIQUE_RESULTS_PER_RUN} "
                    "vagas únicas atingido; termos restantes não consultados."
                )
                break
            print(f"\n[{i}/{len(terms)}] Consultando LinkedIn para: '{term}'...")
            try:
                records = scrape_pass(
                    f"termo:{term}",
                    requested_general_limit,
                    site_name=["linkedin"],
                    search_term=term,
                    location=location,
                    hours_old=hours_old,
                    description_format="markdown",
                    fetch_description=True,
                    verbose=0,
                )
                if records:
                    add_records(
                        records, is_remote_search=False, pass_name=f"termo:{term}"
                    )
                else:
                    print(f"  -> Nenhuma vaga encontrada para '{term}'.")
            except Exception as error:
                print(f"  [Aviso] Falha ao consultar '{term}': {error}")
                collection_errors.append(f"termo '{term}': {error}")
            if i < len(terms) and len(all_jobs_dict) < MAX_UNIQUE_RESULTS_PER_RUN:
                time.sleep(2)
    else:
        print(
            "\n[Fase 1/2] Executando Varredura Aberta Geral "
            "(todo o Brasil, sem filtro de palavras-chave)..."
        )
        try:
            records = scrape_pass(
                "general",
                requested_general_limit,
                site_name=["linkedin"],
                search_term=None,
                location=location,
                hours_old=hours_old,
                description_format="markdown",
                fetch_description=True,
                verbose=0,
            )
            if records:
                add_records(
                    records, is_remote_search=False, pass_name="general"
                )
            else:
                print("  -> Nenhuma vaga encontrada na varredura geral.")
        except Exception as error:
            print(f"  [Aviso] Falha na varredura geral: {error}")
            collection_errors.append(f"busca geral: {error}")

        if include_remote_pass and requested_remote_limit > 0:
            time.sleep(2)

        if (
            include_remote_pass
            and requested_remote_limit > 0
            and len(all_jobs_dict) < MAX_UNIQUE_RESULTS_PER_RUN
        ):
            print(
                "\n[Fase 2/2] Executando Varredura Aberta Remota "
                "(f_WT=2, Brasil; filtro usado apenas para descoberta)..."
            )
            try:
                records = scrape_pass(
                    "remote",
                    requested_remote_limit,
                    site_name=["linkedin"],
                    search_term=None,
                    location=location,
                    is_remote=True,
                    hours_old=hours_old,
                    description_format="markdown",
                    fetch_description=True,
                    verbose=0,
                )
                if records:
                    add_records(
                        records, is_remote_search=True, pass_name="remote"
                    )
                else:
                    print("  -> Nenhuma vaga encontrada na varredura remota.")
            except Exception as error:
                print(f"  [Aviso] Falha na varredura remota: {error}")
                collection_errors.append(f"busca remota: {error}")
        elif include_remote_pass and requested_remote_limit > 0:
            print(
                f"  [Aviso] Busca remota não executada: teto agregado de "
                f"{MAX_UNIQUE_RESULTS_PER_RUN} vagas únicas já atingido."
            )

    if collection_errors:
        details = "; ".join(collection_errors)
        raise RuntimeError(
            "Coleta LinkedIn incompleta; o snapshot anterior foi preservado: "
            + details
        )

    collected_list = list(all_jobs_dict.values())
    if not collected_list:
        raise RuntimeError("Nenhuma vaga pública do LinkedIn foi coletada")
    if len(collected_list) > MAX_UNIQUE_RESULTS_PER_RUN:
        raise RuntimeError("Teto agregado de vagas únicas excedido")

    if len(collected_list) >= MAX_UNIQUE_RESULTS_PER_RUN:
        print(
            f"[Aviso] Teto agregado de {MAX_UNIQUE_RESULTS_PER_RUN} "
            "vagas únicas atingido; podem existir anúncios não coletados."
        )

    remotes_count = sum(1 for job in collected_list if job.get("workplaceType") == "remote")
    hybrids_count = sum(1 for job in collected_list if job.get("workplaceType") == "hybrid")
    onsites_count = sum(1 for job in collected_list if job.get("workplaceType") == "on-site")
    application_counts = {
        application_type: sum(
            1 for job in collected_list
            if job.get("applicationType") == application_type
        )
        for application_type in ("easy_apply", "external", "unknown")
    }

    print("\n==========================================")
    print(f"[Sucesso] Total de vagas únicas coletadas: {len(collected_list)}")
    print(
        f"[Modalidade] Remotas: {remotes_count} | "
        f"Híbridas: {hybrids_count} | Presenciais: {onsites_count}"
    )
    print(
        "[Candidatura] Easy Apply: "
        f"{application_counts['easy_apply']} | Externa: "
        f"{application_counts['external']} | Desconhecida: "
        f"{application_counts['unknown']}"
    )
    print("==========================================")

    collected_list.sort(key=lambda job: job.get("publishedAt") or "", reverse=True)

    payload = {
        "schema_version": 1,
        "source": "linkedin",
        "filter": "public_brazil",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(collected_list),
        "limits": {
            "max_results_per_query": JOBSPY_MAX_RESULTS_PER_QUERY,
            "max_unique_per_run": MAX_UNIQUE_RESULTS_PER_RUN,
            "requested_general": requested_general_limit,
            "requested_remote": requested_remote_limit if include_remote_pass else 0,
        },
        "coverage": pass_coverage,
        "jobs": collected_list,
    }

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as snapshot_file:
        json.dump(payload, snapshot_file, ensure_ascii=False, indent=2)

    print(f"[Arquivo] Snapshot salvo em: {out_path}")

    github_step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if github_step_summary and os.path.exists(github_step_summary):
        with open(github_step_summary, "a", encoding="utf-8") as summary:
            summary.write("### 🚀 Coleta Aberta de Vagas LinkedIn (Vagas Públicas)\n\n")
            summary.write(
                f"- **Data/Hora:** "
                f"{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}\n"
            )
            summary.write(
                f"- **Vagas únicas coletadas:** {len(collected_list)} "
                f"(máximo agregado: {MAX_UNIQUE_RESULTS_PER_RUN})\n"
            )
            summary.write(
                f"- **Modalidade verificada:** Remotas {remotes_count}, "
                f"híbridas {hybrids_count}, presenciais {onsites_count}.\n"
            )
            summary.write(
                f"- **Tipo de candidatura:** Easy Apply "
                f"{application_counts['easy_apply']}, externa "
                f"{application_counts['external']}, desconhecida "
                f"{application_counts['unknown']}. Itens desconhecidos "
                "permanecem no snapshot.\n"
            )
            summary.write(
                f"- **Limites informados:** geral solicitado "
                f"{requested_general_limit}, remoto solicitado "
                f"{requested_remote_limit if include_remote_pass else 0}; "
                f"máximo por consulta {JOBSPY_MAX_RESULTS_PER_QUERY}; "
                f"teto de únicos {MAX_UNIQUE_RESULTS_PER_RUN}.\n\n"
            )
            summary.write(
                f"- **Filtros:** Brasil, últimas {hours_old//24} dias, "
                "sem filtro por tipo de candidatura.\n\n"
            )
            for item in pass_coverage:
                statuses = []
                if item.get("clamped_by_query_limit"):
                    statuses.append(
                        f"corte por consulta em {JOBSPY_MAX_RESULTS_PER_QUERY}"
                    )
                if item.get("clamped_by_pass_budget"):
                    statuses.append(
                        f"corte pelo teto agregado {MAX_UNIQUE_RESULTS_PER_RUN}"
                    )
                if item.get("source_exhausted"):
                    statuses.append("fonte encerrou antes do limite")
                elif item.get("stopped_without_progress"):
                    statuses.append("paginação sem novos IDs; cobertura incerta")
                elif item.get("limit_reached"):
                    statuses.append("limite efetivo atingido; podem existir mais vagas")
                else:
                    statuses.append("consulta concluída")
                summary.write(
                    f"- Busca {item['name']}: solicitado "
                    f"{item['requested_limit']}, efetivo "
                    f"{item['effective_limit']}, retornado "
                    f"{item['returned']} em {item['pages']} páginas — "
                    f"{'; '.join(statuses)}.\n"
                )
            summary.write("\n")
            summary.write("| # | Vaga | Empresa | Local / Modelo | Data |\n")
            summary.write("|---|---|---|---|---|\n")
            for index, job in enumerate(collected_list[:25], 1):
                title = f"[{job['title']}]({job['url']})" if job["url"] else job["title"]
                date_str = job["publishedAt"].split("T")[0] if job["publishedAt"] else "Recente"
                summary.write(
                    f"| {index} | {title} | {job['company']} | "
                    f"{job['location']} ({job['workplaceType']}) | {date_str} |\n"
                )
            if len(collected_list) > 25:
                summary.write(
                    f"\n*... e mais {len(collected_list) - 25} vagas registradas no snapshot.*\n"
                )

    return collected_list



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coletor isolado de vagas do LinkedIn")
    parser.add_argument("--terms", nargs="*", default=None, help="Termos específicos opcionais (padrão: busca aberta ampla)")
    parser.add_argument("--location", type=str, default="Brazil", help="País ou localização")
    parser.add_argument(
        "--results-limit",
        "--results-wanted",
        "--results-per-term",
        dest="results_limit",
        type=int,
        default=DEFAULT_RESULTS_LIMIT,
        help="Limite solicitado; no máximo 1.000 por consulta e 1.200 únicos por execução",
    )
    parser.add_argument(
        "--remote-results-limit",
        type=int,
        default=DEFAULT_REMOTE_RESULTS_LIMIT,
        help="Limite solicitado; máximo 1.000 por consulta e 1.200 únicos por execução",
    )
    parser.add_argument("--hours-old", type=int, default=DEFAULT_HOURS_OLD, help="Horas desde a publicação (1440 = 60 dias)")
    parser.add_argument("--output", type=str, default="docs/data/linkedin_vagas.json", help="Caminho do arquivo de saída")
    parser.add_argument("--skip-remote-pass", action="store_true", help="Pular a etapa dedicada de busca remota")
    args = parser.parse_args()

    collect_linkedin(
        terms=args.terms,
        location=args.location,
        results_limit=args.results_limit,
        remote_results_limit=args.remote_results_limit,
        hours_old=args.hours_old,
        out_path=args.output,
        include_remote_pass=not args.skip_remote_pass,
    )
