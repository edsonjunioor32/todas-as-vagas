#!/usr/bin/env python3
"""
Publica a edição especial semanal 'As Melhores Vagas da Semana' no LinkedIn via Make.com.
Curadoria de 12 vagas brasileiras de alta demanda (100% remotas/híbridas) dos últimos 7 dias.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

BRASILIA = ZoneInfo("America/Sao_Paulo")
DEFAULT_SNAPSHOT_URL = "https://edsonjunioor32.github.io/todas-as-vagas/data/vagas.json"
DEFAULT_WEBHOOK_URL = "https://hook.us2.make.com/pmtttsu5fw61y2sjhyevac82zw74mwx0"
DEFAULT_BANNER_URL = "https://raw.githubusercontent.com/edsonjunioor32/todas-as-vagas/main/docs/assets/img/banner_linkedin_semanal.jpg"
WHATSAPP_CHANNEL = "https://whatsapp.com/channel/0029Vb8RtiHEquiKyIFpqw1s"
MAX_POST_CHARS = 3000

# Portais confiáveis do ecossistema brasileiro
VALID_BRAZIL_DOMAINS = [
    "gupy.io", "inhire.app", "geekhunter.com.br", "geekhunter.com",
    "infojobs.com.br", "vagas.com.br", "solides.com.br", "abler.com.br",
    "quickin.io", "trampos.co", "compleo.com.br", "rhgestor.com.br"
]

# Setores e funções corporativas de alta demanda no momento
HIGH_DEMAND_KEYWORDS = [
    "desenvolvedor", "developer", "software", "frontend", "backend", "full stack",
    "dados", "data", "produto", "product", "ux", "ui", "segurança", "security",
    "sdr", "inside sales", "devops", "cloud", "qa", "teste de software", "arquiteto",
    "engenheiro", "analista"
]

FOREIGN_EXCLUSIONS = [
    "germany", "berlin", "munich", "united states", "san francisco", "new york",
    "toronto", "canada", "poland", "uk", "london", "arbeitnow", "jobicy", "himalayas"
]


def _parse_date(value: str | None) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    val = value.strip()
    try:
        return date.fromisoformat(val[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _column_value(columns: dict, name: str, row_index: int) -> str:
    values = columns.get(name) or []
    if row_index >= len(values):
        return ""
    value = values[row_index]
    return value if isinstance(value, str) else ""


def _lookup_dictionary(snapshot: dict, index_key: str, dictionary_key: str, row_index: int) -> str:
    columns = snapshot.get("jobs") or {}
    indexes = columns.get(index_key) or []
    if row_index >= len(indexes):
        return ""
    value = indexes[row_index]
    if isinstance(value, bool) or not isinstance(value, int):
        return ""
    options = (snapshot.get("dict") or {}).get(dictionary_key) or []
    return options[value] if 0 <= value < len(options) else ""


def decode_snapshot(snapshot: dict) -> list[dict]:
    columns = snapshot.get("jobs")
    if not isinstance(columns, dict):
        raise RuntimeError("O snapshot público não contém a lista compacta de vagas esperada.")
    titles = columns.get("title") or []
    urls = columns.get("url") or []

    index_fields = {
        "source": ("src", "source"),
        "company": ("cmp", "company"),
        "area": ("area", "area"),
        "seniority": ("sen", "seniority"),
        "work_model": ("wm", "work_model"),
        "market": ("mk", "market"),
        "country": ("co", "country"),
    }
    rows = []
    for index, title in enumerate(titles):
        url = urls[index] if index < len(urls) else ""
        if not isinstance(title, str) or not title.strip() or not isinstance(url, str):
            continue
        row = {
            "title": title.strip(),
            "city": _column_value(columns, "city", index),
            "published_date": _column_value(columns, "pub", index),
            "seen_date": _column_value(columns, "seen", index),
            "expires_date": _column_value(columns, "exp", index),
            "url": url.strip(),
        }
        for field, (index_key, dictionary_key) in index_fields.items():
            row[field] = _lookup_dictionary(snapshot, index_key, dictionary_key, index)
        rows.append(row)
    return rows


def clean_job_title(raw_title: str) -> str:
    cleaned = re.sub(r'^[💻🟦🔹\d\s:_-]+', '', raw_title).strip()
    cleaned = re.sub(r'\|\s*REMOTO.*$', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'-\s*REMOTO.*$', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\(Remoto\).*$', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'-\s*Home Office.*$', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'-\s*RHA\d+.*$', '', cleaned).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:100]


def select_weekly_vacancies(snapshot: dict, target_count: int = 12, days_window: int = 7) -> list[dict]:
    today = date.today()
    cutoff_date = today - timedelta(days=days_window)
    all_jobs = decode_snapshot(snapshot)

    candidates = []
    seen_companies = set()
    seen_title_prefixes = set()

    for job in all_jobs:
        job_url = job.get("url", "").strip()
        if not any(domain in job_url for domain in VALID_BRAZIL_DOMAINS):
            continue

        city = (job.get("city") or "").lower()
        company = (job.get("company") or "").strip()
        model = (job.get("work_model") or "").lower()
        raw_title = (job.get("title") or "").strip()

        # Excluir gringas
        if any(f in city or f in company.lower() or f in raw_title.lower() for f in FOREIGN_EXCLUSIONS):
            continue

        # Validar vigência da semana
        pub_date = _parse_date(job.get("published_date")) or _parse_date(job.get("seen_date"))
        if pub_date and pub_date < cutoff_date:
            continue

        # Apenas Remotas ou Híbridas
        is_remote = (
            "remot" in model or "fully" in model or
            "remot" in city or "home office" in city or "todo o brasil" in city or
            "remot" in raw_title.lower() or "home office" in raw_title.lower()
        )
        if not is_remote:
            continue

        cleaned_title = clean_job_title(raw_title)
        t_lower = cleaned_title.lower()
        comp_lower = company.lower()

        # Relevância de mercado
        if not any(k in t_lower for k in HIGH_DEMAND_KEYWORDS):
            continue

        # Deduplicação rigorosa
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


def compose_weekly_digest(vacancies: list[dict], today: date | None = None) -> str:
    today = today or date.today()
    header = (
        f"🏆 AS MELHORES VAGAS DA SEMANA — Edição Especial de Sexta-feira ({today:%d/%m/%Y})\n\n"
        "Fim de semana chegando! Selecionamos as oportunidades remotas de maior destaque e demanda da semana no mercado corporativo e de tecnologia brasileiro:\n\n"
    )

    blocks = []
    for idx, job in enumerate(vacancies, 1):
        title = job.get("cleaned_title") or job.get("title", "").strip()
        company = job.get("company", "").strip() or "Empresa Confidencial"
        url = job.get("url", "").strip()
        block = f"{idx}. 🔹 {title}\n🏢 {company} · 100% Remoto\n🔗 {url}"
        blocks.append(block)

    marker_url = f"https://edsonjunioor32.github.io/todas-as-vagas/?utm_source=linkedin&utm_medium=social&utm_campaign=melhores-da-semana-{today:%Y%m%d}"
    footer = (
        f"\n\n🔎 Explore e filtre mais de 78 mil vagas gratuitas em nosso portal:\n{marker_url}\n\n"
        f"📲 Entre no Canal Oficial no WhatsApp para não perder novas vagas diárias:\n{WHATSAPP_CHANNEL}\n\n"
        "#TodasAsVagas #VagasDaSemana #VagasRemotas #TrabalhoRemoto #HomeOffice #Carreira #VagasTech"
    )

    return header + "\n\n".join(blocks) + footer


def publish_weekly(dry_run: bool = False, webhook_url: str | None = None) -> int:
    webhook_url = webhook_url or os.environ.get("MAKE_LINKEDIN_WEBHOOK_URL") or DEFAULT_WEBHOOK_URL
    print(f"Buscando catálogo de vagas de {DEFAULT_SNAPSHOT_URL}...")
    req = urllib.request.Request(DEFAULT_SNAPSHOT_URL, headers={"User-Agent": "TodasAsVagasBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        snapshot = json.loads(resp.read().decode("utf-8"))

    today = date.today()
    vacancies = select_weekly_vacancies(snapshot, target_count=12, days_window=7)
    print(f"Vagas semanais selecionadas: {len(vacancies)}")

    if len(vacancies) < 5:
        print("Aviso: Menos de 5 vagas qualificadas encontradas para o digest semanal.")

    post_text = compose_weekly_digest(vacancies, today)
    print(f"Texto gerado: {len(post_text)} caracteres (Limite: {MAX_POST_CHARS})")

    if len(post_text) > MAX_POST_CHARS:
        print(f"Alerta: Post excedeu o limite do LinkedIn ({len(post_text)} > {MAX_POST_CHARS})")
        return 1

    payload = {
        "text": post_text,
        "content": post_text,
        "image_url": DEFAULT_BANNER_URL,
        "url": DEFAULT_BANNER_URL,
        "image": DEFAULT_BANNER_URL,
        "date": today.isoformat(),
        "jobs_count": len(vacancies),
        "type": "weekly_digest"
    }

    if dry_run:
        print("\n--- [DRY-RUN] PRÉVIA DO POST SEMANAL ---\n")
        print(post_text)
        print(f"\nBanner anexado: {DEFAULT_BANNER_URL}")
        return 0

    print(f"Enviando para o Webhook do Make ({webhook_url[:35]}...)...")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    webhook_req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})

    try:
        with urllib.request.urlopen(webhook_req, timeout=25) as resp:
            print(f"Resposta do Webhook: HTTP {resp.status} - {resp.read().decode('utf-8')}")
            print("Publicação semanal agendada/disparada com sucesso no LinkedIn!")
            return 0
    except Exception as exc:
        print(f"Erro ao disparar webhook: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Publicador semanal das melhores vagas para o LinkedIn")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula e exibe o post sem disparar o webhook")
    parser.add_argument("--webhook-url", type=str, default=None, help="URL customizada do webhook Make.com")
    args = parser.parse_args()

    sys.exit(publish_weekly(dry_run=args.dry_run, webhook_url=args.webhook_url))


if __name__ == "__main__":
    main()
