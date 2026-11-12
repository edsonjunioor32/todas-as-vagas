#!/usr/bin/env python3
"""
Publica a edição diária 'As Melhores Vagas do Dia' no LinkedIn via Make.com.
Curadoria de 12 vagas brasileiras de alta demanda (100% remotas/híbridas) coletadas hoje.
Inclui controle de estado idempotente para impedir postagens duplicadas no mesmo dia.
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
DEFAULT_CARD_URL = "https://raw.githubusercontent.com/edsonjunioor32/todas-as-vagas/main/docs/assets/img/card_melhores_vagas_do_dia.jpg"
WHATSAPP_CHANNEL = "https://whatsapp.com/channel/0029Vb8RtiHEquiKyIFpqw1s"
MAX_POST_CHARS = 3000

STATE_PATH = Path("docs/data/linkedin_digest_state.json")

# Importa utilitários compartilhados
import publish_linkedin_weekly as utils


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Aviso ao ler {STATE_PATH}: {e}")
    return {"last_daily_posted_date": None, "last_weekly_posted_date": None, "history": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_already_posted_today(today: date) -> bool:
    state = load_state()
    return state.get("last_daily_posted_date") == today.isoformat()


def mark_posted_today(today: date, jobs_count: int) -> None:
    state = load_state()
    state["last_daily_posted_date"] = today.isoformat()
    history = state.setdefault("history", [])
    history.append({
        "date": today.isoformat(),
        "type": "daily",
        "jobs_count": jobs_count,
        "timestamp": datetime.now(BRASILIA).isoformat()
    })
    # Manter no máximo 60 dias de histórico
    state["history"] = history[-60:]
    save_state(state)


def select_daily_vacancies(snapshot: dict, target_count: int = 12) -> list[dict]:
    all_jobs = utils.decode_snapshot(snapshot)

    candidates = []
    seen_companies = set()
    seen_title_prefixes = set()

    for job in all_jobs:
        job_url = job.get("url", "").strip()
        if not any(domain in job_url for domain in utils.VALID_BRAZIL_DOMAINS):
            continue

        city = (job.get("city") or "").lower()
        company = (job.get("company") or "").strip()
        model = (job.get("work_model") or "").lower()
        raw_title = (job.get("title") or "").strip()

        if any(f in city or f in company.lower() or f in raw_title.lower() for f in utils.FOREIGN_EXCLUSIONS):
            continue

        # Apenas Remotas ou Híbridas
        is_remote = (
            "remot" in model or "fully" in model or
            "remot" in city or "home office" in city or "todo o brasil" in city or
            "remot" in raw_title.lower() or "home office" in raw_title.lower()
        )
        if not is_remote:
            continue

        cleaned_title = utils.clean_job_title(raw_title)
        t_lower = cleaned_title.lower()
        comp_lower = company.lower()

        # Relevância de mercado
        if not any(k in t_lower for k in utils.HIGH_DEMAND_KEYWORDS):
            continue

        # Deduplicação
        t_prefix = t_lower[:25]
        if comp_lower in seen_companies or t_prefix in seen_title_prefixes:
            continue

        seen_companies.add(comp_lower)
        seen_title_prefixes.add(t_prefix)

        job["cleaned_title"] = cleaned_title
        candidates.append(job)

        if len(candidates) >= target_count:
            break

    return candidates


def compose_daily_digest(vacancies: list[dict], today: date | None = None) -> str:
    today = today or datetime.now(BRASILIA).date()
    header = (
        f"💼 Oportunidades em Alta no Brasil — Edição de Hoje ({today:%d/%m/%Y})\n\n"
        "Confira as 12 posições com alta demanda no mercado nacional corporativo e de tecnologia selecionadas hoje (100% Remotas / Home Office):\n\n"
    )

    blocks = []
    for idx, job in enumerate(vacancies, 1):
        title = job.get("cleaned_title") or job.get("title", "").strip()
        company = job.get("company", "").strip() or "Empresa Confidencial"
        url = job.get("url", "").strip()
        block = f"{idx}. 🔹 {title}\n🏢 {company} · 100% Remoto\n🔗 {url}"
        blocks.append(block)

    marker_url = f"https://edsonjunioor32.github.io/todas-as-vagas/?utm_source=linkedin&utm_medium=social&utm_campaign=todas-as-vagas-{today:%Y%m%d}"
    footer = (
        f"\n\n🔎 Explore e filtre mais de 78 mil vagas gratuitas em nosso portal:\n{marker_url}\n\n"
        f"📲 Entre no Canal Oficial no WhatsApp para não perder novas vagas diárias:\n{WHATSAPP_CHANNEL}\n\n"
        "#TodasAsVagas #VagasRemotas #TrabalhoRemoto #HomeOffice #Emprego #Carreira #VagasTech"
    )

    return header + "\n\n".join(blocks) + footer


def publish_daily(dry_run: bool = False, force: bool = False, webhook_url: str | None = None) -> int:
    today = datetime.now(BRASILIA).date()

    if not force and is_already_posted_today(today):
        print(f"Aviso: O post diário de hoje ({today:%d/%m/%Y}) já foi realizado anteriormente.")
        print("Encerrando execução de forma segura para impedir publicações duplicadas.")
        return 0

    webhook_url = webhook_url or os.environ.get("MAKE_LINKEDIN_WEBHOOK_URL") or DEFAULT_WEBHOOK_URL
    print(f"Buscando catálogo de vagas de {DEFAULT_SNAPSHOT_URL}...")
    req = urllib.request.Request(DEFAULT_SNAPSHOT_URL, headers={"User-Agent": "TodasAsVagasBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        snapshot = json.loads(resp.read().decode("utf-8"))

    vacancies = select_daily_vacancies(snapshot, target_count=12)
    print(f"Vagas diárias selecionadas: {len(vacancies)}")

    if len(vacancies) < 5:
        print("Aviso: Menos de 5 vagas qualificadas encontradas para o digest diário.")

    post_text = compose_daily_digest(vacancies, today)
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
        "type": "daily_digest"
    }

    if dry_run:
        print("\n--- [DRY-RUN] PRÉVIA DO POST DIÁRIO ---\n")
        print(post_text)
        print(f"\nCard anexado: {DEFAULT_CARD_URL}")
        return 0

    print(f"Enviando para o Webhook do Make ({webhook_url[:35]}...)...")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    webhook_req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})

    try:
        with urllib.request.urlopen(webhook_req, timeout=25) as resp:
            print(f"Resposta do Webhook: HTTP {resp.status} - {resp.read().decode('utf-8')}")
            print("Publicação diária agendada/disparada com sucesso no LinkedIn!")
            mark_posted_today(today, len(vacancies))
            return 0
    except Exception as exc:
        print(f"Erro ao disparar webhook: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Publicador diário das melhores vagas para o LinkedIn")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula e exibe o post sem disparar o webhook")
    parser.add_argument("--force", action="store_true", help="Ignora a checagem de post já publicado hoje e força o envio")
    parser.add_argument("--webhook-url", type=str, default=None, help="URL customizada do webhook Make.com")
    args = parser.parse_args()

    sys.exit(publish_daily(dry_run=args.dry_run, force=args.force, webhook_url=args.webhook_url))


if __name__ == "__main__":
    main()
