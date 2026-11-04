# -*- coding: utf-8 -*-
"""
Coleta isolada de vagas do LinkedIn com Candidatura Simplificada (Easy Apply).
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
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit


# Limites operacionais da coleta aberta. JobSpy aceita offset para continuar
# a busca; usamos lotes controlados para ultrapassar o primeiro resultado sem
# criar uma consulta ilimitada ou concentrar todas as requisições em uma única chamada.
DEFAULT_RESULTS_LIMIT = 600
DEFAULT_REMOTE_RESULTS_LIMIT = 300
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

    workplace_type = _extract_workplace_type_from_html(captured.get("html", ""))
    if workplace_type:
        details = dict(details)
        details["work_from_home_type"] = workplace_type
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

    # Só o selo da página individual confirma a modalidade. Localização,
    # título e filtro de busca não são evidência suficiente para classificar.
    verified_model = _workplace_type_from_text(raw_job.get("work_from_home_type"))
    workplace_type = verified_model

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
        "workplaceVerified": bool(verified_model),
        "publishedAt": date_posted,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "easyApply": True,
        "salaryMin": float(min_amount) if min_amount else None,
        "salaryMax": float(max_amount) if max_amount else None,
        "currency": currency if (min_amount or max_amount) else None,
        # A descrição não é publicada neste snapshot; é usada apenas para enriquecer o JobSpy.
        "description": "",
    }



def _scrape_jobs_in_pages(*, results_limit, **kwargs):
    """Coleta um número limitado de resultados usando lotes e o offset público do JobSpy."""
    target = max(0, int(results_limit))
    if target == 0:
        return []

    batch_size = min(JOBSPY_BATCH_SIZE, target)
    max_pages = math.ceil(target / batch_size)
    records = []
    seen_keys = set()

    for page_number in range(max_pages):
        offset = page_number * batch_size
        page_kwargs = dict(kwargs)
        page_kwargs["results_wanted"] = batch_size
        page_kwargs["offset"] = offset
        print(
            f"  -> Lote {page_number + 1}/{max_pages} "
            f"(offset={offset}, limite={batch_size})"
        )
        df = scrape_jobs(**page_kwargs)
        if df is None or df.empty:
            break

        batch = df.to_dict(orient="records")
        if not batch:
            break

        new_records = 0
        for raw in batch:
            key = (
                clean_value(raw.get("job_url"))
                or clean_value(raw.get("id"))
                or f"{clean_value(raw.get('title'))}::{clean_value(raw.get('company'))}"
            )
            key = str(key).strip()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            records.append(raw)
            new_records += 1

        # Menos registros que o lote solicitado sinaliza o fim da busca. Se o
        # offset não for respeitado ou a página repetir os mesmos registros,
        # interrompemos para evitar um loop sem progresso.
        if len(batch) < batch_size or new_records == 0:
            break
        if page_number < max_pages - 1:
            time.sleep(2)

    return records[:target]

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

    print(f"=== [LinkedIn Jobs Collector] Iniciando Coleta Aberta ===")
    print(
        f"Critérios: Localização='{location}', Horas={hours_old} (~{hours_old//24} dias), "
        f"EasyApply=True, Limite Geral={results_limit}, Limite Remoto={remote_results_limit if include_remote_pass else 0}"
    )

    all_jobs_dict = {}

    # Modo A: Se termos específicos forem passados (modo direcionado / testes manuais)
    if terms:
        print(f"[Modo Direcionado] Consultando termos específicos ({len(terms)}): {terms}")
        for i, term in enumerate(terms, 1):
            print(f"\n[{i}/{len(terms)}] Consultando LinkedIn para: '{term}'...")
            try:
                records = _scrape_jobs_in_pages(
                    results_limit=results_limit,
                    site_name=["linkedin"],
                    search_term=term,
                    location=location,
                    hours_old=hours_old,
                    easy_apply=True,
                    description_format="markdown",
                    fetch_description=True,
                    verbose=0,
                )
                if records:
                    print(f"  -> Encontradas {len(records)} vagas para '{term}'.")
                    for raw in records:
                        norm = normalize_linkedin_job(raw, is_remote_search=False)
                        job_key = norm["url"] or f"{norm['title']}::{norm['company']}"
                        if job_key not in all_jobs_dict:
                            all_jobs_dict[job_key] = norm
            except Exception as e:
                print(f"  [Aviso] Falha ao consultar '{term}': {e}")
            time.sleep(2)

    # Modo B: Padrão aberto e não-restritivo para o portal Todas as Vagas
    else:
        # 1. Varredura Aberta Geral (Presencial, Híbrida e Remota em todo o Brasil)
        print(f"\n[Fase 1/2] Executando Varredura Aberta Geral (todo o Brasil, sem filtro de palavras-chave)...")
        try:
            records = _scrape_jobs_in_pages(
                results_limit=results_limit,
                site_name=["linkedin"],
                search_term=None,
                location=location,
                hours_old=hours_old,
                easy_apply=True,
                description_format="markdown",
                fetch_description=True,
                verbose=0,
            )
            if records:
                print(f"  -> Encontradas {len(records)} vagas na varredura geral.")
                for raw in records:
                    norm = normalize_linkedin_job(raw, is_remote_search=False)
                    job_key = norm["url"] or f"{norm['title']}::{norm['company']}"
                    if job_key not in all_jobs_dict:
                        all_jobs_dict[job_key] = norm
            else:
                print("  -> Nenhuma vaga encontrada na varredura geral.")
        except Exception as e:
            print(f"  [Aviso] Falha na varredura geral: {e}")

        time.sleep(2)

        # 2. Varredura Aberta Remota Dedicada (f_WT=2)
        if include_remote_pass and remote_results_limit > 0:
            print(f"\n[Fase 2/2] Executando Varredura Aberta Remota Dedicada (f_WT=2, 100% Brasil)...")
            try:
                records = _scrape_jobs_in_pages(
                    results_limit=remote_results_limit,
                    site_name=["linkedin"],
                    search_term=None,
                    location=location,
                    is_remote=True,
                    hours_old=hours_old,
                    easy_apply=True,
                    description_format="markdown",
                    fetch_description=True,
                    verbose=0,
                )
                if records:
                    print(f"  -> Encontradas {len(records)} vagas remotas Easy Apply.")
                    for raw in records:
                        norm = normalize_linkedin_job(raw, is_remote_search=True)
                        job_key = norm["url"] or f"{norm['title']}::{norm['company']}"
                        if job_key not in all_jobs_dict:
                            all_jobs_dict[job_key] = norm
                else:
                    print("  -> Nenhuma vaga encontrada na varredura remota.")
            except Exception as e:
                print(f"  [Aviso] Falha na varredura remota: {e}")

    collected_list = list(all_jobs_dict.values())
    if not collected_list:
        raise RuntimeError("Nenhuma vaga pública de candidatura simplificada foi coletada")

    remotes_count = sum(1 for j in collected_list if j.get("workplaceType") == "remote")
    hybrids_count = sum(1 for j in collected_list if j.get("workplaceType") == "hybrid")
    onsites_count = sum(1 for j in collected_list if j.get("workplaceType") == "on-site")

    print(f"\n==========================================")
    print(f"[Sucesso] Total de vagas únicas coletadas: {len(collected_list)}")
    print(f"[Distribuição] Remotas: {remotes_count} | Híbridas: {hybrids_count} | Presenciais: {onsites_count}")
    print(f"==========================================")

    # Ordena pelas mais recentes
    collected_list.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)

    payload = {
        "schema_version": 1,
        "source": "linkedin",
        "filter": "easy_apply",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(collected_list),
        "jobs": collected_list,
    }

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[Arquivo] Snapshot salvo em: {out_path}")

    # Se estiver rodando dentro do GitHub Actions, gera o resumo visual na página do run
    github_step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if github_step_summary and os.path.exists(github_step_summary):
        with open(github_step_summary, "a", encoding="utf-8") as g:
            g.write(f"### 🚀 Coleta Aberta de Vagas LinkedIn (Candidatura Simplificada)\n\n")
            g.write(f"- **Data/Hora:** `{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}`\n")
            g.write(
                f"- **Vagas Únicas Coletadas:** `{len(collected_list)}` "
                f"(Remotas: `{remotes_count}`, Híbridas: `{hybrids_count}`, Presenciais: `{onsites_count}`)\n"
            )
            g.write(f"- **Filtros:** Brasil, últimas {hours_old//24} dias, Easy Apply ativo (Busca Aberta).\n\n")
            g.write("| # | Vaga | Empresa | Local / Modelo | Data |\n")
            g.write("|---|---|---|---|---|\n")
            for idx, j in enumerate(collected_list[:25], 1):
                title = f"[{j['title']}]({j['url']})" if j['url'] else j['title']
                date_str = j['publishedAt'].split('T')[0] if j['publishedAt'] else 'Recente'
                g.write(f"| {idx} | {title} | {j['company']} | {j['location']} ({j['workplaceType']}) | {date_str} |\n")
            if len(collected_list) > 25:
                g.write(f"\n*... e mais {len(collected_list) - 25} vagas registradas no snapshot.*\n")

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
        help="Limite total da varredura geral (em lotes de até 100)",
    )
    parser.add_argument(
        "--remote-results-limit",
        type=int,
        default=DEFAULT_REMOTE_RESULTS_LIMIT,
        help="Limite total da varredura remota dedicada (em lotes de até 100)",
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
