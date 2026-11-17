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
from typing import Any
from zoneinfo import ZoneInfo

BRASILIA = ZoneInfo("America/Sao_Paulo")
DEFAULT_SNAPSHOT_URL = "https://edsonjunioor32.github.io/todas-as-vagas/data/vagas.json"
DEFAULT_CARD_URL = "https://raw.githubusercontent.com/edsonjunioor32/todas-as-vagas/main/docs/assets/img/card_melhores_vagas_do_dia.jpg"
WHATSAPP_CHANNEL = "https://whatsapp.com/channel/0029Vb8RtiHEquiKyIFpqw1s"
MAX_POST_CHARS = 3000

STATE_PATH = Path("docs/data/linkedin_digest_state.json")

# Importa utilitários compartilhados
import publish_linkedin_weekly as utils
import linkedin_api


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


def mark_posted_today(today: date, vacancies: list[dict], post_urn: str | None = None) -> None:
    state = load_state()
    state["last_daily_posted_date"] = today.isoformat()
    history = state.setdefault("history", [])
    entry: dict[str, Any] = {
        "date": today.isoformat(),
        "type": "daily",
        "jobs_count": len(vacancies),
        "timestamp": datetime.now(BRASILIA).isoformat()
    }
    if post_urn:
        entry["urn"] = post_urn
    history.append(entry)
    # Manter no máximo 60 dias de histórico
    state["history"] = history[-60:]
    utils.record_posted_jobs(state, vacancies)
    save_state(state)


def select_daily_vacancies(snapshot: dict, target_count: int = 12) -> list[dict]:
    all_jobs = utils.decode_snapshot(snapshot)

    state = load_state()
    posted_urls = utils.get_posted_urls(state)
    posted_sigs = utils.get_posted_signatures(state)

    candidates = []
    seen_companies = set()
    seen_title_prefixes = set()

    for job in all_jobs:
        job_url = job.get("url", "").strip()
        if not any(domain in job_url for domain in utils.VALID_BRAZIL_DOMAINS):
            continue

        # Tratamento para não repetir vagas já postadas em qualquer edição anterior
        norm_url = utils.normalize_job_url(job_url)
        if norm_url in posted_urls:
            continue

        city = (job.get("city") or "").lower()
        company = (job.get("company") or "").strip()
        model = (job.get("work_model") or "").lower()
        raw_title = (job.get("title") or "").strip()

        if any(f in city or f in company.lower() or f in raw_title.lower() for f in utils.FOREIGN_EXCLUSIONS):
            continue

        # Evita repetição por assinatura empresa + cargo
        sig = utils.make_job_signature(company, raw_title)
        if sig in posted_sigs:
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

        # Deduplicação no lote atual
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
        f"💼 AS MELHORES VAGAS DO DIA — Edição de Hoje ({today:%d/%m/%Y})\n\n"
        "Curadoria exclusiva com as principais posições abertas no mercado corporativo e de tecnologia (100% Remotas e Híbridas):\n\n"
    )

    marker_url = f"https://edsonjunioor32.github.io/todas-as-vagas/?utm_source=linkedin&utm_medium=social&utm_campaign=todas-as-vagas-{today:%Y%m%d}"
    footer = (
        f"\n\n🔎 Explore e filtre mais de 78 mil vagas gratuitas em nosso portal:\n{marker_url}\n\n"
        f"📲 Entre no Canal Oficial no WhatsApp para não perder novas vagas diárias:\n{WHATSAPP_CHANNEL}\n\n"
        "#TodasAsVagas #MelhoresVagasDoDia #VagasRemotas #TrabalhoRemoto #HomeOffice #Emprego #Carreira #VagasTech"
    )

    current_vacancies = list(vacancies)
    while current_vacancies:
        blocks = []
        for idx, job in enumerate(current_vacancies, 1):
            title = job.get("cleaned_title") or job.get("title", "").strip()
            company = utils.clean_company_name(job.get("company", ""))
            url = job.get("url", "").strip()
            block = f"{idx}. 🔹 {title}\n🏢 {company} · 100% Remoto\n🔗 {url}"
            blocks.append(block)

        text = header + "\n\n".join(blocks) + footer
        if len(text) <= 2800:
            return text
        current_vacancies.pop()

    return header + "\n\n".join(blocks) + footer


def publish_daily(dry_run: bool = False, force: bool = False, webhook_url: str | None = None, delete_urn: str | None = None) -> int:
    now_brt = datetime.now(BRASILIA)
    today = now_brt.date()

    if not force:
        # Trava de dias úteis, alinhada ao cron '* * 1-5' do workflow: os gatilhos
        # workflow_run também chegam aos sábados e domingos.
        if now_brt.weekday() >= 5:
            print(f"Aviso: {now_brt:%d/%m/%Y} é fim de semana; a edição diária sai apenas de segunda a sexta.")
            print("Encerrando execução de forma segura.")
            return 0

        # Trava de segurança de horário: só publica a partir das 18h15 BRT
        if now_brt.hour < 18 or (now_brt.hour == 18 and now_brt.minute < 15):
            print(f"Aviso: Horário atual ({now_brt:%H:%M} BRT) é anterior à janela permitida (a partir das 18h15 BRT).")
            print("Encerrando execução de forma segura.")
            return 0

        if is_already_posted_today(today):
            print(f"Aviso: O post diário de hoje ({today:%d/%m/%Y}) já foi realizado anteriormente.")
            print("Encerrando execução de forma segura para impedir publicações duplicadas.")
            return 0

    linkedin_token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    webhook_url = utils.resolve_webhook_url(webhook_url)
    if not linkedin_token and webhook_url is None and not dry_run:
        return utils.report_missing_webhook()

    # Se solicitado, exclui post anterior no LinkedIn antes de publicar o novo
    if delete_urn and linkedin_token and not dry_run:
        print(f"Excluindo post anterior no LinkedIn: {delete_urn}...")
        try:
            if linkedin_api.delete_post(delete_urn, linkedin_token):
                print(f"Post anterior {delete_urn} excluído com sucesso do LinkedIn!")
        except Exception as exc:
            print(f"Aviso: Não foi possível excluir post anterior {delete_urn}: {exc}", file=sys.stderr)

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

    # 1. Tentativa nativa direta via LinkedIn Community Management API
    if linkedin_token:
        print("LINKEDIN_ACCESS_TOKEN detectado. Publicando diretamente via LinkedIn Community Management API...")
        try:
            card_path = Path("docs/assets/img/card_melhores_vagas_do_dia.jpg")
            img_source = str(card_path) if card_path.exists() else DEFAULT_CARD_URL
            post_urn = linkedin_api.publish_to_linkedin(
                commentary=post_text,
                image_path_or_url=img_source,
                token=linkedin_token,
            )
            print(f"Publicação diária realizada com SUCESSO nativo no LinkedIn! Post URN: {post_urn}")
            mark_posted_today(today, vacancies, post_urn=post_urn)
            return 0
        except Exception as exc:
            print(f"Aviso: Erro na publicação nativa do LinkedIn ({exc}).", file=sys.stderr)
            if not webhook_url:
                print("Nenhum webhook Make.com configurado para fallback.", file=sys.stderr)
                return 1
            print("Tentando fallback para Make.com...", file=sys.stderr)

    if webhook_url:
        # Logs do Actions são públicos e só mascaram o secret inteiro: nenhum trecho da URL é impresso.
        print("Enviando para o Webhook do Make (URL omitida do log)...")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        webhook_req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})

        try:
            with urllib.request.urlopen(webhook_req, timeout=25) as resp:
                print(f"Resposta do Webhook: HTTP {resp.status} - {resp.read().decode('utf-8')}")
                print("Publicação diária agendada/disparada com sucesso no LinkedIn!")
                mark_posted_today(today, vacancies)
                return 0
        except Exception as exc:
            print(f"Erro ao disparar webhook: {exc}", file=sys.stderr)
            return 1

    print("Erro: Nenhum método de envio (API nativa ou webhook) foi bem-sucedido.", file=sys.stderr)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Publicador diário das melhores vagas para o LinkedIn")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula e exibe o post sem disparar o webhook")
    parser.add_argument("--force", action="store_true", help="Ignora a checagem de post já publicado hoje e força o envio")
    parser.add_argument(
        "--delete-urn",
        type=str,
        default=None,
        help="URN de post anterior para excluir antes de publicar o novo",
    )
    parser.add_argument(
        "--webhook-url",
        type=str,
        default=None,
        help="URL do webhook Make.com; se omitida, usa MAKE_LINKEDIN_WEBHOOK_URL (obrigatória fora do --dry-run)",
    )
    args = parser.parse_args()

    sys.exit(publish_daily(dry_run=args.dry_run, force=args.force, webhook_url=args.webhook_url, delete_urn=args.delete_urn))


if __name__ == "__main__":
    main()
