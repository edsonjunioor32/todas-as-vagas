# -*- coding: utf-8 -*-
"""
Coleta isolada de vagas do LinkedIn com Candidatura Simplificada (Easy Apply).
Projetado para rodar localmente ou via GitHub Actions para o projeto 'Todas as Vagas'.
"""

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
import pandas as pd
from jobspy import scrape_jobs

# Patch JobSpy's LinkedIn scraper to support remote workplace filtering (f_WT=2)
# Permite busca remota dedicada sem cookies, login ou serviços pagos
try:
    from jobspy.linkedin import LinkedIn

    _orig_linkedin_search_params = LinkedIn._search_params

    def _patched_linkedin_search_params(self):
        params = _orig_linkedin_search_params(self)
        if getattr(self.scraper_input, "is_remote", False):
            params["f_WT"] = "2"
        return params

    LinkedIn._search_params = _patched_linkedin_search_params
except Exception as err:
    print(f"[Aviso] Não foi possível aplicar patch de busca remota no JobSpy: {err}")

# Termos prioritários de busca no LinkedIn
DEFAULT_SEARCH_TERMS = [
    "Analista de Suporte",
    "Suporte Técnico",
    "Suporte N2",
    "Tecnologia da Informação",
    "Desenvolvedor",
    "Analista de Atendimento",
    "Operations Assistant",
    "Assistente de Operações",
    "Suporte de Aplicação",
    "Help Desk",
]

# Termos prioritários para a varredura remota dedicada (f_WT=2)
DEFAULT_REMOTE_TERMS = [
    "Suporte",
    "Desenvolvedor",
    "Tecnologia",
    "Atendimento",
    "Operations",
    "Analista",
]

def clean_value(val):
    """Limpa nulos e tipos não serializáveis."""
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return ""
    if pd.isna(val):
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
    remote_terms=None,
    location="Brazil",
    results_per_term=25,
    hours_old=720,
    out_path="docs/data/linkedin_vagas.json",
    include_remote_pass=True,
):
    terms = terms or DEFAULT_SEARCH_TERMS
    remote_terms = remote_terms or DEFAULT_REMOTE_TERMS
    print(f"=== [LinkedIn Jobs Collector] Iniciando Coleta ===")
    print(
        f"Critérios: Termos={len(terms)}, Localização='{location}', "
        f"Horas={hours_old} (~{hours_old//24} dias), EasyApply=True, Limite={results_per_term}/termo"
    )

    all_jobs_dict = {}

    # 1. Varredura padrão com termos prioritários
    for i, term in enumerate(terms, 1):
        print(f"\n[Geral {i}/{len(terms)}] Consultando LinkedIn para: '{term}'...")
        try:
            df = scrape_jobs(
                site_name=["linkedin"],
                search_term=term,
                location=location,
                results_wanted=results_per_term,
                hours_old=hours_old,
                easy_apply=True,
                description_format="markdown",
                fetch_description=False,
                verbose=0,
            )

            if df is not None and not df.empty:
                records = df.to_dict(orient="records")
                print(f"  -> Encontradas {len(records)} vagas com candidatura simplificada.")
                for raw in records:
                    norm = normalize_linkedin_job(raw, is_remote_search=False)
                    job_key = norm["url"] or f"{norm['title']}::{norm['company']}"
                    if job_key not in all_jobs_dict:
                        all_jobs_dict[job_key] = norm
            else:
                print(f"  -> Nenhuma vaga encontrada para '{term}'.")

        except Exception as e:
            print(f"  [Aviso] Falha ao consultar '{term}': {e}")

        if i < len(terms):
            time.sleep(2)

    # 2. Varredura remota dedicada (f_WT=2 via JobSpy patch)
    if include_remote_pass and remote_terms:
        print(f"\n=== [LinkedIn Jobs Collector] Iniciando Busca Remota Dedicada (f_WT=2) ===")
        for i, term in enumerate(remote_terms, 1):
            print(f"\n[Remoto {i}/{len(remote_terms)}] Consultando LinkedIn Remoto: '{term}'...")
            try:
                df = scrape_jobs(
                    site_name=["linkedin"],
                    search_term=term,
                    location=location,
                    is_remote=True,
                    results_wanted=results_per_term,
                    hours_old=hours_old,
                    easy_apply=True,
                    description_format="markdown",
                    fetch_description=False,
                    verbose=0,
                )

                if df is not None and not df.empty:
                    records = df.to_dict(orient="records")
                    print(f"  -> Encontradas {len(records)} vagas remotas Easy Apply.")
                    for raw in records:
                        norm = normalize_linkedin_job(raw, is_remote_search=True)
                        job_key = norm["url"] or f"{norm['title']}::{norm['company']}"
                        if job_key not in all_jobs_dict:
                            all_jobs_dict[job_key] = norm
                else:
                    print(f"  -> Nenhuma vaga remota encontrada para '{term}'.")

            except Exception as e:
                print(f"  [Aviso] Falha ao consultar remoto '{term}': {e}")

            if i < len(remote_terms):
                time.sleep(2)

    collected_list = list(all_jobs_dict.values())
    if not collected_list:
        raise RuntimeError("Nenhuma vaga pública de candidatura simplificada foi coletada")
    print(f"\n==========================================")
    print(f"[Sucesso] Total de vagas únicas coletadas: {len(collected_list)}")
    remotes_count = sum(1 for j in collected_list if j.get("workplaceType") == "remote")
    print(f"[Distribuição] Remotas: {remotes_count} | Híbridas/Presenciais: {len(collected_list) - remotes_count}")
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
            g.write(f"### 🚀 Coleta de Vagas LinkedIn (Candidatura Simplificada)\n\n")
            g.write(f"- **Data/Hora:** `{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}`\n")
            g.write(f"- **Vagas Únicas Coletadas:** `{len(collected_list)}` (Remotas: `{remotes_count}`)\n")
            g.write(f"- **Filtros:** Brasil, últimas {hours_old//24} dias, Easy Apply ativo.\n\n")
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
    parser.add_argument("--terms", nargs="+", default=DEFAULT_SEARCH_TERMS, help="Termos de busca geral")
    parser.add_argument("--remote-terms", nargs="+", default=DEFAULT_REMOTE_TERMS, help="Termos para busca remota dedicada")
    parser.add_argument("--location", type=str, default="Brazil", help="País ou localização")
    parser.add_argument("--results-per-term", type=int, default=25, help="Quantidade por termo")
    parser.add_argument("--hours-old", type=int, default=720, help="Horas desde a publicação (720 = 30 dias)")
    parser.add_argument("--output", type=str, default="docs/data/linkedin_vagas.json", help="Caminho do arquivo de saída")
    parser.add_argument("--skip-remote-pass", action="store_true", help="Pular a etapa dedicada de busca remota")
    args = parser.parse_args()

    collect_linkedin(
        terms=args.terms,
        remote_terms=args.remote_terms,
        location=args.location,
        results_per_term=args.results_per_term,
        hours_old=args.hours_old,
        out_path=args.output,
        include_remote_pass=not args.skip_remote_pass,
    )
