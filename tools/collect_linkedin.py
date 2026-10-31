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

# Importações condicionais para permitir que módulos de validação/testes importem
# funções utilitárias (ex: normalize_linkedin_job) mesmo em ambientes de CI leves
# onde pandas e jobspy não estão instalados no catálogo principal.
try:
    import pandas as pd
except ImportError:
    pd = None

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

    # Determina o modelo de trabalho (remote, hybrid, on-site)
    loc_lower = str(location).lower().strip()
    title_lower = str(title).lower().strip()
    desc_lower = str(raw_job.get("description") or "").lower()
    is_remote_flag = bool(raw_job.get("is_remote")) or is_remote_search

    remote_keywords = (
        "remoto", "remote", "home office", "home-office",
        "teletrabalho", "wfh", "anywhere", "100% remoto", "totalmente remoto"
    )
    hybrid_keywords = ("híbrido", "hibrido", "hybrid")

    if any(h in loc_lower or h in title_lower or h in desc_lower for h in hybrid_keywords):
        workplace_type = "hybrid"
    elif (
        is_remote_flag
        or loc_lower in ("brazil", "brasil")
        or any(k in loc_lower or k in title_lower or k in desc_lower for k in remote_keywords)
    ):
        workplace_type = "remote"
    else:
        workplace_type = "on-site"

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
        "publishedAt": date_posted,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "easyApply": True,
        "salaryMin": float(min_amount) if min_amount else None,
        "salaryMax": float(max_amount) if max_amount else None,
        "currency": currency if (min_amount or max_amount) else None,
        "description": clean_value(raw_job.get("description"))[:4000] if raw_job.get("description") else "",
    }


def collect_linkedin(
    terms=None,
    location="Brazil",
    results_limit=100,
    remote_results_limit=50,
    hours_old=720,
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
                df = scrape_jobs(
                    site_name=["linkedin"],
                    search_term=term,
                    location=location,
                    results_wanted=results_limit,
                    hours_old=hours_old,
                    easy_apply=True,
                    description_format="markdown",
                    fetch_description=False,
                    verbose=0,
                )
                if df is not None and not df.empty:
                    records = df.to_dict(orient="records")
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
            df_general = scrape_jobs(
                site_name=["linkedin"],
                search_term=None,
                location=location,
                results_wanted=results_limit,
                hours_old=hours_old,
                easy_apply=True,
                description_format="markdown",
                fetch_description=False,
                verbose=0,
            )
            if df_general is not None and not df_general.empty:
                records = df_general.to_dict(orient="records")
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
                df_remote = scrape_jobs(
                    site_name=["linkedin"],
                    search_term=None,
                    location=location,
                    is_remote=True,
                    results_wanted=remote_results_limit,
                    hours_old=hours_old,
                    easy_apply=True,
                    description_format="markdown",
                    fetch_description=False,
                    verbose=0,
                )
                if df_remote is not None and not df_remote.empty:
                    records = df_remote.to_dict(orient="records")
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
        default=100,
        help="Limite de vagas da varredura geral",
    )
    parser.add_argument(
        "--remote-results-limit",
        type=int,
        default=50,
        help="Limite de vagas da varredura remota dedicada",
    )
    parser.add_argument("--hours-old", type=int, default=720, help="Horas desde a publicação (720 = 30 dias)")
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
