#!/usr/bin/env python3
"""
Publica a edição matinal 'Desperta Vagas' no LinkedIn via Make.com.
Agendada para todos os dias às 7h17 (Horário de Brasília).
Curadoria com as vagas mais buscadas do momento no Brasil (Remotas, Híbridas e Presenciais).
Inclui provocação de engajamento matinal para interação da comunidade.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BRASILIA = ZoneInfo("America/Sao_Paulo")
DEFAULT_SNAPSHOT_URL = "https://edsonjunioor32.github.io/todas-as-vagas/data/vagas.json"
DEFAULT_WEBHOOK_URL = "https://hook.us2.make.com/pmtttsu5fw61y2sjhyevac82zw74mwx0"
DEFAULT_CARD_URL = "https://raw.githubusercontent.com/edsonjunioor32/todas-as-vagas/main/docs/assets/img/card_desperta_vagas.jpg"
WHATSAPP_CHANNEL = "https://whatsapp.com/channel/0029Vb8RtiHEquiKyIFpqw1s"
MAX_POST_CHARS = 3000
TARGET_CHARS = 2800

STATE_PATH = Path("docs/data/linkedin_digest_state.json")

import publish_linkedin_weekly as utils

# Categorias mais buscadas no mercado nacional de trabalho
POPULAR_CATEGORIES = [
    {
        "name": "Comercial / Vendas",
        "keywords": ["sdr", "bdr", "vendedor", "vendas", "consultor comercial", "inside sales", "executivo de contas", "comercial"],
        "max": 2
    },
    {
        "name": "Administrativo / Financeiro / RH",
        "keywords": ["assistente administrativo", "analista financeiro", "analista contabil", "analista fiscal", "analista de rh", "recursos humanos", "recrutador", "departamento pessoal"],
        "max": 2
    },
    {
        "name": "Tecnologia / Dados",
        "keywords": ["desenvolvedor", "developer", "software", "analista de dados", "devops", "cloud", "suporte", "analista de ti", "qa"],
        "max": 2
    },
    {
        "name": "Atendimento / Customer Success",
        "keywords": ["customer success", "cs", "relacionamento", "atendimento ao cliente", "experiencia do cliente", "ouvidoria"],
        "max": 2
    },
    {
        "name": "Marketing / Design",
        "keywords": ["marketing", "social media", "designer", "criacao", "comunicacao", "conteudo", "growth"],
        "max": 2
    },
    {
        "name": "Operações / Logística",
        "keywords": ["analista de operacoes", "logistica", "supply chain", "compras", "planejamento"],
        "max": 2
    }
]


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Aviso ao ler {STATE_PATH}: {e}")
    return {"last_daily_posted_date": None, "last_weekly_posted_date": None, "last_morning_posted_date": None, "history": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_already_posted_this_morning(today: date) -> bool:
    state = load_state()
    return state.get("last_morning_posted_date") == today.isoformat()


def mark_posted_this_morning(today: date, vacancies: list[dict]) -> None:
    state = load_state()
    state["last_morning_posted_date"] = today.isoformat()
    history = state.setdefault("history", [])
    history.append({
        "date": today.isoformat(),
        "type": "morning_desperta",
        "jobs_count": len(vacancies),
        "timestamp": datetime.now(BRASILIA).isoformat()
    })
    state["history"] = history[-60:]
    utils.record_posted_jobs(state, vacancies)
    save_state(state)


def _format_location(job: dict) -> str:
    work_model = (job.get("work_model") or "").lower()
    city = (job.get("city") or "").strip()

    if "remot" in work_model or "fully" in work_model:
        return "100% Remoto"
    elif "hybr" in work_model or "híbr" in work_model:
        loc = city if city else "Brasil"
        return f"Híbrido · {loc}"
    else:
        loc = city if city else "Brasil"
        return f"Presencial · {loc}"


def select_morning_vacancies(snapshot: dict, target_count: int = 12) -> list[dict]:
    all_jobs = utils.decode_snapshot(snapshot)

    state = load_state()
    posted_urls = utils.get_posted_urls(state)
    posted_sigs = utils.get_posted_signatures(state)

    candidates = []
    seen_companies = set()
    seen_title_prefixes = set()

    for category_cfg in POPULAR_CATEGORIES:
        cat_name = category_cfg["name"]
        keywords = category_cfg["keywords"]
        max_for_cat = category_cfg["max"]
        cat_added = 0

        for job in all_jobs:
            if cat_added >= max_for_cat or len(candidates) >= target_count:
                break

            job_url = job.get("url", "").strip()
            if not any(domain in job_url for domain in utils.VALID_BRAZIL_DOMAINS):
                continue

            # Não repetir vagas já enviadas em qualquer edição anterior
            norm_url = utils.normalize_job_url(job_url)
            if norm_url in posted_urls:
                continue

            city = (job.get("city") or "").lower()
            company = (job.get("company") or "").strip()
            raw_title = (job.get("title") or "").strip()
            t_lower = raw_title.lower()

            if any(f in city or f in company.lower() or f in t_lower for f in utils.FOREIGN_EXCLUSIONS):
                continue

            if any(ex in t_lower for ex in ["telemarketing", "cobrança", "cobranca", "sac ativo", "operador de telemarketing"]):
                continue

            # Evita repetição por assinatura empresa + cargo
            sig = utils.make_job_signature(company, raw_title)
            if sig in posted_sigs:
                continue

            if not any(k in t_lower for k in keywords):
                continue

            cleaned_title = utils.clean_job_title(raw_title)
            t_prefix = cleaned_title.lower()[:25]
            comp_lower = company.lower()

            if comp_lower in seen_companies or t_prefix in seen_title_prefixes:
                continue

            seen_companies.add(comp_lower)
            seen_title_prefixes.add(t_prefix)

            job["cleaned_title"] = cleaned_title
            job["category_name"] = cat_name
            job["location_formatted"] = _format_location(job)
            candidates.append(job)
            cat_added += 1

    return candidates


def compose_morning_digest(vacancies: list[dict], today: date | None = None) -> str:
    today = today or datetime.now(BRASILIA).date()

    header = (
        f"☕ Desperta Vagas — Edição de Hoje ({today:%d/%m/%Y})\n\n"
        "Seu primeiro café com as melhores oportunidades abertas no mercado nacional. "
        "Separamos as posições mais buscadas do momento em diferentes áreas e formatos (Remotas, Híbridas e Presenciais):\n\n"
    )

    marker_url = f"https://edsonjunioor32.github.io/todas-as-vagas/?utm_source=linkedin&utm_medium=social&utm_campaign=desperta-vagas-{today:%Y%m%d}"
    footer = (
        f"\n\n☕💬 E para começarmos o dia alinhados: qual tipo de vaga, cargo ou área você mais quer ver por aqui nas próximas edições? Deixe nos comentários! 👇\n\n"
        f"🔎 Explore e filtre mais de 78 mil vagas gratuitas em nosso portal:\n{marker_url}\n\n"
        f"📲 Entre no Canal Oficial no WhatsApp para não perder novas vagas ao longo do dia:\n{WHATSAPP_CHANNEL}\n\n"
        "#DespertaVagas #TodasAsVagas #VagasDeEmprego #Emprego #Carreira #VagasAbertas #Trabalho #Oportunidades"
    )

    current_vacancies = list(vacancies)
    while current_vacancies:
        blocks = []
        for idx, job in enumerate(current_vacancies, 1):
            title = job.get("cleaned_title") or job.get("title", "").strip()
            company = utils.clean_company_name(job.get("company", ""))
            loc = job.get("location_formatted") or "Brasil"
            url = job.get("url", "").strip()
            block = f"{idx}. 🔹 {title}\n🏢 {company} · {loc}\n🔗 {url}"
            blocks.append(block)

        text = header + "\n\n".join(blocks) + footer
        if len(text) <= TARGET_CHARS:
            return text
        current_vacancies.pop()

    return header + "\n\n".join(blocks) + footer


def publish_morning(dry_run: bool = False, force: bool = False, webhook_url: str | None = None) -> int:
    today = datetime.now(BRASILIA).date()

    if not force and is_already_posted_this_morning(today):
        print(f"Aviso: O 'Desperta Vagas' de hoje ({today:%d/%m/%Y}) já foi realizado anteriormente.")
        print("Encerrando execução de forma segura para impedir publicações duplicadas.")
        return 0

    webhook_url = webhook_url or os.environ.get("MAKE_LINKEDIN_WEBHOOK_URL") or DEFAULT_WEBHOOK_URL
    print(f"Buscando catálogo de vagas de {DEFAULT_SNAPSHOT_URL}...")
    req = urllib.request.Request(DEFAULT_SNAPSHOT_URL, headers={"User-Agent": "TodasAsVagasBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        snapshot = json.loads(resp.read().decode("utf-8"))

    vacancies = select_morning_vacancies(snapshot, target_count=12)
    print(f"Vagas matinais selecionadas: {len(vacancies)}")

    if len(vacancies) < 5:
        print("Aviso: Menos de 5 vagas qualificadas encontradas para a edição matinal.")

    post_text = compose_morning_digest(vacancies, today)
    print(f"Texto gerado: {len(post_text)} caracteres (Limite: {MAX_POST_CHARS})")

    if len(post_text) > MAX_POST_CHARS:
        print(f"Alerta: Post excedeu o limite do LinkedIn ({len(post_text)} > {MAX_POST_CHARS})")
        return 1

    payload = {
        "text": post_text,
        "content": post_text,
        "image_url": DEFAULT_CARD_URL,
        "url": DEFAULT_CARD_URL,
        "image": DEFAULT_CARD_URL,
        "date": today.isoformat(),
        "jobs_count": len(vacancies),
        "type": "desperta_vagas"
    }

    if dry_run:
        print("\n--- [DRY-RUN] PRÉVIA DO DESPERTA VAGAS ---\n")
        print(post_text)
        print(f"\nCard anexado: {DEFAULT_CARD_URL}")
        return 0

    print(f"Enviando para o Webhook do Make ({webhook_url[:35]}...)...")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    webhook_req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})

    try:
        with urllib.request.urlopen(webhook_req, timeout=25) as resp:
            print(f"Resposta do Webhook: HTTP {resp.status} - {resp.read().decode('utf-8')}")
            print("Publicação do Desperta Vagas enviada com sucesso ao LinkedIn!")
            mark_posted_this_morning(today, vacancies)
            return 0
    except Exception as exc:
        print(f"Erro ao disparar webhook: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Publicador matinal Desperta Vagas para o LinkedIn")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula e exibe o post sem disparar o webhook")
    parser.add_argument("--force", action="store_true", help="Ignora a checagem de post matinal já publicado hoje e força o envio")
    parser.add_argument("--webhook-url", type=str, default=None, help="URL customizada do webhook Make.com")
    args = parser.parse_args()

    sys.exit(publish_morning(dry_run=args.dry_run, force=args.force, webhook_url=args.webhook_url))


if __name__ == "__main__":
    main()
