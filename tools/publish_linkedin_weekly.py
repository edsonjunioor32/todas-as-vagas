#!/usr/bin/env python3
"""
Publica a edição especial semanal 'As Melhores Vagas da Semana' no LinkedIn via Make.com.
Curadoria de elite com as melhores vagas executivas, de liderança e alta senioridade da semana (100% Remotas e Híbridas).
Alinhado ao banner: Oportunidades executivas e de liderança selecionadas para acelerar sua carreira.
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
from pathlib import Path
from zoneinfo import ZoneInfo

BRASILIA = ZoneInfo("America/Sao_Paulo")
DEFAULT_SNAPSHOT_URL = "https://edsonjunioor32.github.io/todas-as-vagas/data/vagas.json"
DEFAULT_WEBHOOK_URL = "https://hook.us2.make.com/pmtttsu5fw61y2sjhyevac82zw74mwx0"
DEFAULT_BANNER_URL = "https://raw.githubusercontent.com/edsonjunioor32/todas-as-vagas/main/docs/assets/img/banner_linkedin_semanal.jpg"
WHATSAPP_CHANNEL = "https://whatsapp.com/channel/0029Vb8RtiHEquiKyIFpqw1s"
MAX_POST_CHARS = 3000
TARGET_CHARS = 2800

STATE_PATH = Path("docs/data/linkedin_digest_state.json")

# Portais confiáveis do ecossistema brasileiro
VALID_BRAZIL_DOMAINS = [
    "gupy.io", "inhire.app", "geekhunter.com.br", "geekhunter.com",
    "infojobs.com.br", "vagas.com.br", "solides.com.br", "abler.com.br",
    "quickin.io", "trampos.co", "compleo.com.br", "rhgestor.com.br"
]

# Setores e funções corporativas de alta demanda diária
HIGH_DEMAND_KEYWORDS = [
    "desenvolvedor", "developer", "software", "frontend", "backend", "full stack",
    "dados", "data", "produto", "product", "ux", "ui", "segurança", "security",
    "sdr", "inside sales", "devops", "cloud", "qa", "teste de software", "arquiteto",
    "engenheiro", "analista"
]

# Palavras-chave de Liderança, Executivas e Alta Senioridade ("As melhores da semana mesmo")
LEADERSHIP_KEYWORDS = [
    "head of", "head de", "diretor", "diretora", "director", "gerente", "manager",
    "tech lead", "team lead", "staff engineer", "principal engineer", "staff", "principal",
    "arquiteto", "architect", "coordenador", "coordenadora", "cto", "cpo", "cio", "cfo", "cro"
]

SPECIALIST_KEYWORDS = [
    "especialista", "specialist", "senior", "sênior", "sr", "líder técnico", "lider tecnico",
    "consultor", "consultora"
]

# Exclusões para garantir padrão executivo/sênior e eliminar ruídos operacionais
EXCLUDE_NON_EXECUTIVE = [
    "estagio", "estágio", "intern", "trainee", "junior", "júnior", "jr", "assistente",
    "auxiliar", "atendente", "operador", "telemarketing", "sac", "balconista", "caixa",
    "loja", "vendedor interno", "telefonia", "retenção"
]

FOREIGN_EXCLUSIONS = [
    "germany", "berlin", "munich", "united states", "san francisco", "new york",
    "toronto", "canada", "poland", "uk", "london", "arbeitnow", "jobicy", "himalayas"
]


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Aviso ao ler {STATE_PATH}: {e}")
    return {
        "last_daily_posted_date": None,
        "last_weekly_posted_date": None,
        "last_morning_posted_date": None,
        "posted_job_urls": [],
        "posted_job_signatures": [],
        "history": []
    }


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_job_url(url: str) -> str:
    if not url:
        return ""
    clean = url.split("?")[0].split("#")[0].strip().rstrip("/")
    return clean.lower()


def make_job_signature(company: str, title: str) -> str:
    c = re.sub(r"[^\w\s]", "", (company or "").lower()).strip()
    t = re.sub(r"[^\w\s]", "", (title or "").lower()).strip()
    return f"{c[:25]}:{t[:30]}"


def get_posted_signatures(state: dict) -> set[str]:
    return set(state.get("posted_job_signatures") or [])


def get_posted_urls(state: dict) -> set[str]:
    return set(state.get("posted_job_urls") or [])


def record_posted_jobs(state: dict, vacancies: list[dict]) -> None:
    posted_urls = state.setdefault("posted_job_urls", [])
    posted_sigs = state.setdefault("posted_job_signatures", [])

    for v in vacancies:
        norm_url = normalize_job_url(v.get("url", ""))
        sig = make_job_signature(v.get("company", ""), v.get("cleaned_title") or v.get("title", ""))
        if norm_url and norm_url not in posted_urls:
            posted_urls.append(norm_url)
        if sig and sig not in posted_sigs:
            posted_sigs.append(sig)

    # Mantém os últimos 1500 registros para evitar crescimento ilimitado
    state["posted_job_urls"] = posted_urls[-1500:]
    state["posted_job_signatures"] = posted_sigs[-1500:]


def is_already_posted_this_week(today: date) -> bool:
    state = load_state()
    last = state.get("last_weekly_posted_date")
    if not last:
        return False
    try:
        last_dt = date.fromisoformat(last)
        # Mesma semana (ISO calendar)
        return last_dt.isocalendar() == today.isocalendar()
    except Exception:
        return last == today.isoformat()


def mark_posted_this_week(today: date, jobs_count: int) -> None:
    state = load_state()
    state["last_weekly_posted_date"] = today.isoformat()
    history = state.setdefault("history", [])
    history.append({
        "date": today.isoformat(),
        "type": "weekly_executive",
        "jobs_count": jobs_count,
        "timestamp": datetime.now(BRASILIA).isoformat()
    })
    state["history"] = history[-60:]
    save_state(state)


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
            "url": url.strip(),
            "city": columns.get("city", [""])[index] if index < len(columns.get("city", [])) else "",
            "published_date": columns.get("pub", [""])[index] if index < len(columns.get("pub", [])) else "",
            "seen_date": columns.get("seen", [""])[index] if index < len(columns.get("seen", [])) else "",
        }
        for field, (short_col, dict_key) in index_fields.items():
            indexes = columns.get(short_col) or []
            if index < len(indexes):
                val_idx = indexes[index]
                if isinstance(val_idx, int) and not isinstance(val_idx, bool):
                    options = (snapshot.get("dict") or {}).get(dict_key) or []
                    row[field] = options[val_idx] if 0 <= val_idx < len(options) else ""
                else:
                    row[field] = ""
            else:
                row[field] = ""
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
    return cleaned[:90]


def clean_company_name(company: str) -> str:
    company = (company or "").strip()
    if "sanguelaranja" in company.lower() or "fcamara" in company.lower():
        return "FCamara"
    if "avantiatecnologia" in company.lower():
        return "Avantia Tecnologia"
    if "linkedin.com/company/" in company:
        match = re.search(r"company/([^/?]+)", company)
        if match:
            slug = match.group(1).replace("-", " ").replace("_", " ").title()
            return slug
    company = re.sub(r"https?://\S+", "", company).strip()
    company = re.sub(r"-\s*Página de talentos.*$", "", company, flags=re.IGNORECASE).strip()
    company = re.sub(r"\|\s*Vagas.*$", "", company, flags=re.IGNORECASE).strip()
    company = re.sub(r"\s+", " ", company).strip()
    return company or "Empresa Confidencial"


def select_weekly_vacancies(snapshot: dict, target_count: int = 12, days_window: int = 7) -> list[dict]:
    all_jobs = decode_snapshot(snapshot)

    scored_candidates = []
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
        t_lower = raw_title.lower()

        # Excluir vagas internacionais
        if any(f in city or f in company.lower() or f in t_lower for f in FOREIGN_EXCLUSIONS):
            continue

        # Excluir cargos de entrada ou operacionais para manter calibre executivo/liderança
        if any(ex in t_lower for ex in EXCLUDE_NON_EXECUTIVE):
            continue

        # Apenas Remotas ou Híbridas
        is_remote = (
            "remot" in model or "fully" in model or
            "remot" in city or "home office" in city or "todo o brasil" in city or
            "remot" in t_lower or "home office" in t_lower
        )
        is_hybrid = "hybr" in model or "híbr" in model or "hibr" in model

        if not (is_remote or is_hybrid):
            continue

        score = 0
        is_leadership = any(k in t_lower for k in LEADERSHIP_KEYWORDS)
        is_specialist = any(k in t_lower for k in SPECIALIST_KEYWORDS)

        if is_leadership:
            score += 20
        elif is_specialist:
            score += 10
        else:
            continue  # Exige explicitamente liderança, arquitetura, especialidade ou senioridade

        if is_remote:
            score += 5
        elif is_hybrid:
            score += 2

        cleaned_title = clean_job_title(raw_title)
        job["cleaned_title"] = cleaned_title
        job["score"] = score
        job["is_remote"] = is_remote
        scored_candidates.append(job)

    # Ordena pelos maiores scores (liderança/executivas primeiro)
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)

    final_candidates = []
    for job in scored_candidates:
        company_clean = job.get("company", "").strip().lower()
        t_prefix = job["cleaned_title"].lower()[:25]

        if company_clean in seen_companies or t_prefix in seen_title_prefixes:
            continue

        seen_companies.add(company_clean)
        seen_title_prefixes.add(t_prefix)
        final_candidates.append(job)

        if len(final_candidates) >= target_count:
            break

    return final_candidates


def compose_weekly_digest(vacancies: list[dict], today: date | None = None) -> str:
    today = today or datetime.now(BRASILIA).date()
    header = (
        f"🏆 AS MELHORES VAGAS DA SEMANA — Edição Especial Executiva e Liderança ({today:%d/%m/%Y})\n\n"
        "Fim de semana chegando! Selecionamos as oportunidades executivas, de liderança estratégica e alta senioridade de maior destaque da semana (100% Remotas e Híbridas de alto impacto):\n\n"
    )

    marker_url = f"https://edsonjunioor32.github.io/todas-as-vagas/?utm_source=linkedin&utm_medium=social&utm_campaign=melhores-da-semana-{today:%Y%m%d}"
    footer = (
        f"\n\n🔎 Explore e filtre mais de 78 mil vagas gratuitas em nosso portal:\n{marker_url}\n\n"
        f"📲 Entre no Canal Oficial no WhatsApp para acompanhar as melhores posições do mercado:\n{WHATSAPP_CHANNEL}\n\n"
        "#TodasAsVagas #MelhoresVagas #VagasDaSemana #Lideranca #Executivos #VagasTech #TrabalhoRemoto #Carreira"
    )

    # Monta os blocos ajustando dinamicamente a quantidade de vagas para nunca estourar o limite de 3000 caracteres
    current_vacancies = list(vacancies)
    while current_vacancies:
        blocks = []
        for idx, job in enumerate(current_vacancies, 1):
            title = job.get("cleaned_title") or job.get("title", "").strip()
            company = clean_company_name(job.get("company", ""))
            url = job.get("url", "").strip()
            model_tag = "100% Remoto" if job.get("is_remote", True) else "Híbrido"
            block = f"{idx}. 🔹 {title}\n🏢 {company} · {model_tag}\n🔗 {url}"
            blocks.append(block)

        text = header + "\n\n".join(blocks) + footer
        if len(text) <= TARGET_CHARS:
            return text
        # Remove a última se ultrapassou o orçamento
        current_vacancies.pop()

    return header + "\n\n".join(blocks) + footer


def publish_weekly(dry_run: bool = False, force: bool = False, webhook_url: str | None = None) -> int:
    now_brt = datetime.now(BRASILIA)
    today = now_brt.date()

    if not force:
        # Trava de segurança de horário: só publica às sextas-feiras (weekday == 4) a partir das 19h15 BRT
        if now_brt.weekday() != 4 or now_brt.hour < 19 or (now_brt.hour == 19 and now_brt.minute < 15):
            print(f"Aviso: Horário atual ({now_brt:%A %H:%M} BRT) está fora da janela semanal permitida (Sexta-feira a partir das 19h15 BRT).")
            print("Encerrando execução de forma segura.")
            return 0

        if is_already_posted_this_week(today):
            print(f"Aviso: O resumo semanal da semana ({today:%d/%m/%Y}) já foi realizado anteriormente.")
            print("Encerrando execução de forma segura para impedir publicações duplicadas.")
            return 0

    webhook_url = webhook_url or os.environ.get("MAKE_LINKEDIN_WEBHOOK_URL") or DEFAULT_WEBHOOK_URL
    print(f"Buscando catálogo de vagas de {DEFAULT_SNAPSHOT_URL}...")
    req = urllib.request.Request(DEFAULT_SNAPSHOT_URL, headers={"User-Agent": "TodasAsVagasBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        snapshot = json.loads(resp.read().decode("utf-8"))

    vacancies = select_weekly_vacancies(snapshot, target_count=12, days_window=7)
    print(f"Vagas executivas/liderança selecionadas: {len(vacancies)}")

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
        "type": "weekly_executive_digest"
    }

    if dry_run:
        print("\n--- [DRY-RUN] PRÉVIA DO POST SEMANAL EXECUTIVO ---\n")
        print(post_text)
        print(f"\nBanner anexado: {DEFAULT_BANNER_URL}")
        return 0

    print(f"Enviando para o Webhook do Make ({webhook_url[:35]}...)...")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    webhook_req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})

    try:
        with urllib.request.urlopen(webhook_req, timeout=25) as resp:
            print(f"Resposta do Webhook: HTTP {resp.status} - {resp.read().decode('utf-8')}")
            print("Publicação semanal executiva agendada/disparada com sucesso no LinkedIn!")
            mark_posted_this_week(today, len(vacancies))
            return 0
    except Exception as exc:
        print(f"Erro ao disparar webhook: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Publicador semanal das melhores vagas executivas para o LinkedIn")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula e exibe o post sem disparar o webhook")
    parser.add_argument("--force", action="store_true", help="Ignora a checagem de semana já postada e força o envio")
    parser.add_argument("--webhook-url", type=str, default=None, help="URL customizada do webhook Make.com")
    args = parser.parse_args()

    sys.exit(publish_weekly(dry_run=args.dry_run, force=args.force, webhook_url=args.webhook_url))


if __name__ == "__main__":
    main()
