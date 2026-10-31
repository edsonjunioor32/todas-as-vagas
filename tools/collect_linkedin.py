# -*- coding: utf-8 -*-
"""
Coleta isolada de vagas do LinkedIn com Candidatura Simplificada (Easy Apply).
Projetado para rodar localmente ou via GitHub Actions para o projeto 'Todas as Vagas'.
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
import pandas as pd
from jobspy import scrape_jobs

# Termos prioritários de busca no LinkedIn
DEFAULT_SEARCH_TERMS = [
    "Analista de Suporte",
    "Suporte Técnico",
    "Suporte N2",
    "Tecnologia da Informação",
    "Desenvolvedor",
    "Analista de Atendimento",
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

def normalize_linkedin_job(raw_job):
    """
    Converte o registro bruto do JobSpy para a estrutura padronizada
    do projeto 'Todas as Vagas'.
    """
    url = clean_value(raw_job.get("job_url")) or ""
    native_id = clean_value(raw_job.get("id")) or ""
    if not native_id and "view/" in url:
        native_id = url.split("view/")[1].split("/")[0].split("?")[0]

    title = clean_value(raw_job.get("title")) or "Vaga sem título"
    company = clean_value(raw_job.get("company")) or "Empresa não informada"
    location = clean_value(raw_job.get("location")) or "Brasil"
    
    # Determina o modelo de trabalho (remote, hybrid, on-site)
    is_remote = bool(raw_job.get("is_remote"))
    loc_lower = str(location).lower()
    title_lower = str(title).lower()
    
    if is_remote or "remoto" in loc_lower or "remote" in loc_lower or "home office" in title_lower:
        workplace_type = "remote"
    elif "híbrido" in loc_lower or "hibrido" in loc_lower or "hybrid" in loc_lower:
        workplace_type = "hybrid"
    else:
        workplace_type = "on-site"

    # Data de publicação
    date_posted = clean_value(raw_job.get("date_posted")) or ""
    if date_posted and not "T" in str(date_posted):
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

def collect_linkedin(terms=None, location="Brazil", results_per_term=15, hours_old=720, out_path="docs/data/linkedin_vagas.json"):
    terms = terms or DEFAULT_SEARCH_TERMS
    print(f"=== [LinkedIn Jobs Collector] Iniciando Coleta ===")
    print(f"Critérios: Termos={len(terms)}, Localização='{location}', Horas={hours_old} (~{hours_old//24} dias), EasyApply=True")
    
    all_jobs_dict = {}
    
    for i, term in enumerate(terms, 1):
        print(f"\n[{i}/{len(terms)}] Consultando LinkedIn para: '{term}'...")
        try:
            df = scrape_jobs(
                site_name=["linkedin"],
                search_term=term,
                location=location,
                results_wanted=results_per_term,
                hours_old=hours_old,
                easy_apply=True,
                description_format="markdown",
                fetch_description=False,  # Mais rápido e leve para GitHub Actions
                verbose=0
            )

            if df is not None and not df.empty:
                records = df.to_dict(orient="records")
                print(f"  -> Encontradas {len(records)} vagas com candidatura simplificada.")
                for raw in records:
                    norm = normalize_linkedin_job(raw)
                    job_key = norm["url"] or f"{norm['title']}::{norm['company']}"
                    if job_key not in all_jobs_dict:
                        all_jobs_dict[job_key] = norm
            else:
                print(f"  -> Nenhuma vaga encontrada para '{term}'.")

        except Exception as e:
            print(f"  [Aviso] Falha ao consultar '{term}': {e}")
            
        # Pausa suave de segurança entre termos para evitar flags
        if i < len(terms):
            time.sleep(3)

    collected_list = list(all_jobs_dict.values())
    if not collected_list:
        raise RuntimeError("Nenhuma vaga pública de candidatura simplificada foi coletada")
    print(f"\n==========================================")
    print(f"[Sucesso] Total de vagas únicas coletadas: {len(collected_list)}")
    print(f"==========================================")

    # Ordena pelas mais recentes
    collected_list.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)

    payload = {
        "schema_version": 1,
        "source": "linkedin",
        "filter": "easy_apply",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(collected_list),
        "jobs": collected_list
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
            g.write(f"- **Vagas Únicas Coletadas:** `{len(collected_list)}`\n")
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
    parser.add_argument("--terms", nargs="+", default=DEFAULT_SEARCH_TERMS, help="Termos de busca")
    parser.add_argument("--location", type=str, default="Brazil", help="País ou localização")
    parser.add_argument("--results-per-term", type=int, default=15, help="Quantidade por termo")
    parser.add_argument("--hours-old", type=int, default=720, help="Horas desde a publicação (720 = 30 dias)")
    parser.add_argument("--output", type=str, default="docs/data/linkedin_vagas.json", help="Caminho do arquivo de saída")
    args = parser.parse_args()

    collect_linkedin(
        terms=args.terms,
        location=args.location,
        results_per_term=args.results_per_term,
        hours_old=args.hours_old,
        out_path=args.output
    )
