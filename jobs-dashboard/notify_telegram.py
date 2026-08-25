# -*- coding: utf-8 -*-
"""Send newly published public vacancies to a Telegram chat.

The script compares the generated public snapshot with the version stored at
HEAD before the pipeline writes its new files. It deliberately uses only the
public fields already exported for the website.
"""
import argparse
from datetime import datetime, timezone
import html
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "docs" / "data" / "vagas.json"
SNAPSHOT_RELATIVE = SNAPSHOT.relative_to(ROOT)
PORTAL_URL = "https://edsonjunioor32.github.io/todas-as-vagas/"
SOURCE_LABELS = {
    "inhire": "InHire",
    "empregare": "Empregare",
    "gupy": "Gupy",
    "solides": "Sólides",
    "geekhunter": "GeekHunter",
    "stone": "Stone",
    "ifood": "iFood",
    "picpay": "PicPay",
    "bancooriginal": "Banco Original",
    "braskem": "Braskem",
    "gmfinancial": "GM Financial",
    "dell": "Dell Technologies",
    "arcelormittal": "ArcelorMittal",
    "grupomateus": "Grupo Mateus",
    "autozone": "AutoZone",
    "nov": "NOV",
    "arcorbrasil": "Arcor Brasil",
    "themuse": "The Muse",
    "remotive": "Remotive",
    "jobicy": "Jobicy",
    "remoteok": "Remote OK",
    "himalayas": "Himalayas",
    "workingnomads": "Working Nomads",
    "arbeitnow": "Arbeitnow",
    "weworkremotely": "We Work Remotely",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "github": "GitHub",
    "Nerdin": "Nerdin",
    "abler": "Abler",
    "infojobs": "InfoJobs",
    "recrutei": "Recrutei",
    "accenture": "Accenture",
    "bradesco": "Bradesco",
    "cloudwalk": "CloudWalk",
    "nestle": "Nestlé",
    "digisystem": "Digisystem",
    "totvs": "TOTVS",
    "wise": "Wise",
    "fiserv": "Fiserv",
    "metalfrio": "Metalfrio",
    "experian": "Experian",
    "providerit": "Provider IT",
    "inlog": "Inlog",
    "revolut": "Revolut",
}
TI_RE = re.compile(
    r"\b(?:ti|tecnologia|software|sistemas?|suporte|desenvolv|devops|"
    r"dados?|analista de dados|engenheir|programa[cç]|infraestrutura|"
    r"cloud|seguran[cç]a|produto digital|qa|testes?|api|sre)\b",
    re.I,
)


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _snapshot_from_ref(ref):
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{ref}:{SNAPSHOT_RELATIVE}"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return json.loads(raw)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return {"count": 0, "jobs": {}, "dict": {}}


def _head_snapshot():
    return _snapshot_from_ref("HEAD")


def _resolve_state_path(value):
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _load_state(path):
    if not path or not path.exists():
        return None
    try:
        data = _load(path)
    except (OSError, json.JSONDecodeError):
        return None
    keys = data.get("notified_keys")
    if not isinstance(keys, list):
        return None
    return {str(key) for key in keys}


def _write_state(path, keys, snapshot):
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_generated_at": snapshot.get("generated_at", ""),
        "notified_keys": sorted(keys),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _value(snapshot, name, index, dictionary=None):
    values = snapshot.get("jobs", {}).get(name, [])
    value = values[index] if index < len(values) else ""
    if dictionary:
        entries = snapshot.get("dict", {}).get(dictionary, [])
        return entries[value] if isinstance(value, int) and value < len(entries) else ""
    return value or ""


def _source_label(value):
    return SOURCE_LABELS.get(value, str(value or "Portal não informado"))


def _workplace_label(value):
    key = str(value or "").casefold().strip()
    if key in {"remote", "remoto", "remota"}:
        return "Remoto"
    if key in {"hybrid", "hibrido", "híbrido"}:
        return "Híbrido"
    if key in {"on-site", "onsite", "presencial"}:
        return "Presencial"
    return "Não informada"


def _market_label(value):
    return {
        "BR": "Brasil",
        "Global remote": "Global remoto",
        "Global": "Global",
    }.get(str(value or ""), str(value or "Não informado"))


def _contract_label(value):
    return "CNPJ" if str(value or "").casefold().strip() == "pj" else str(value or "")


def _contract_types(value):
    contracts = [_contract_label(part.strip()) for part in str(value or "").split(" · ") if part.strip()]
    return " · ".join(contracts) or "Não informado"


def _date_label(value):
    text = str(value or "")
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return "Não informada"
    year, month, day = match.groups()
    return f"{day}/{month}/{year}"


def _rows(snapshot):
    count = int(snapshot.get("count") or 0)
    rows = []
    for index in range(count):
        url = _value(snapshot, "url", index)
        if not url:
            continue
        title = _value(snapshot, "title", index)
        area = _value(snapshot, "area", index, "area")
        skills = _value(snapshot, "sk", index)
        work_model = _value(snapshot, "wm", index, "work_model")
        source = _value(snapshot, "src", index, "source")
        category = area or "Outros"
        seniority = _value(snapshot, "sen", index, "seniority") or "Não informado"
        market = _value(snapshot, "mk", index, "market")
        country = _value(snapshot, "co", index, "country")
        location = _value(snapshot, "city", index) or country or "Local não informado"
        contract_types = _contract_types(_value(snapshot, "ct", index))
        try:
            portals = max(1, int(_value(snapshot, "np", index) or 1))
        except (TypeError, ValueError):
            portals = 1
        remote = _workplace_label(work_model) == "Remoto"
        is_ti = bool(TI_RE.search(" ".join(map(str, (title, area, skills)))))
        rows.append({
            "key": f"{source}:{url}",
            "title": title,
            "company": _value(snapshot, "cmp", index, "company"),
            "source": source,
            "source_label": _source_label(source),
            "url": url,
            "work_model": work_model,
            "workplace_label": _workplace_label(work_model),
            "city": location,
            "category": category,
            "seniority": seniority,
            "market_label": _market_label(market),
            "contract_types": contract_types,
            "published_label": _date_label(_value(snapshot, "pub", index)),
            "pcd": bool(_value(snapshot, "pcd", index)),
            "portals": portals,
            "published": _value(snapshot, "pub", index),
            "remote": remote,
            "ti": is_ti,
        })
    return rows


def _new_rows(current, previous):
    known = {row["key"] for row in _rows(previous)}
    return _unnotified_rows(current, known)


def _unnotified_rows(current, known):
    rows = [row for row in _rows(current) if row["key"] not in known]
    # First remote TI, then the remaining TI, then remote, then all other jobs.
    return sorted(rows, key=lambda row: (
        0 if row["remote"] and row["ti"] else 1 if row["ti"] else 2 if row["remote"] else 3,
        row["published"],
        row["title"].casefold(),
    ))


def _text(rows, page, pages):
    lines = [
        f"🔔 <b>{len(rows)} novas vagas</b> — lote {page}/{pages}",
        "Remotas de TI aparecem primeiro; todas as novas vagas são enviadas.",
        "",
    ]
    for row in rows:
        title = html.escape(str(row["title"] or "Vaga"))
        company = html.escape(str(row.get("company") or "Empresa não informada"))
        location = html.escape(str(row.get("city") or "Local não informado"))
        modality = html.escape(str(row.get("workplace_label") or _workplace_label(row.get("work_model"))))
        contract = html.escape(str(row.get("contract_types") or "Não informado"))
        category = html.escape(str(row.get("category") or "Outros"))
        seniority = html.escape(str(row.get("seniority") or "Não informado"))
        source = html.escape(str(row.get("source_label") or _source_label(row.get("source"))))
        market = html.escape(str(row.get("market_label") or "Não informado"))
        published = html.escape(str(row.get("published_label") or _date_label(row.get("published"))))
        pcd = "Sim" if row.get("pcd") else "Não"
        multiple_portals = "Sim" if int(row.get("portals") or 1) > 1 else "Não"
        portal_count = int(row.get("portals") or 1)
        url = html.escape(str(row["url"]), quote=True)
        lines.append(
            f"• <b>Cargo:</b> <a href=\"{url}\"><b>{title}</b></a>\n"
            f"  <b>Empresa:</b> {company}\n"
            f"  <b>Localização:</b> {location}\n"
            f"  <b>Modalidade:</b> {modality}\n"
            f"  <b>Tipo de contrato:</b> {contract}\n"
            f"  <b>Área de atuação:</b> {category}\n"
            f"  <b>Nível de experiência:</b> {seniority}\n"
            f"  <b>Portal:</b> {source}\n"
            f"  <b>Mercado:</b> {market}\n"
            f"  <b>Publicação:</b> {published}\n"
            f"  <b>PcD:</b> {pcd}\n"
            f"  <b>Encontrada em mais de um portal:</b> {multiple_portals}"
            + (f" ({portal_count} portais)" if portal_count > 1 else "")
        )
    lines.extend([
        "",
        f'📌 <a href="{PORTAL_URL}">Acesse o portal Todas as Vagas</a>',
    ])
    return "\n".join(lines)


def _groups(rows, max_rows=10, max_chars=3700):
    """Keep Telegram messages under its 4096-character limit."""
    groups, current = [], []
    for row in rows:
        candidate = current + [row]
        if current and (len(candidate) > max_rows or len(_text(candidate, 1, 1)) > max_chars):
            groups.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        groups.append(current)
    return groups


def _send(token, chat_id, message):
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )

    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {}
            retry_after = data.get("parameters", {}).get("retry_after")
            if error.code == 429 and retry_after and attempt < 3:
                time.sleep(max(1, int(retry_after)))
                continue
            raise RuntimeError(f"Telegram request failed ({error.code}): {body}") from error
        except Exception as error:
            raise RuntimeError(f"Telegram request failed: {error}") from error

        if data.get("ok"):
            return
        retry_after = data.get("parameters", {}).get("retry_after")
        if data.get("error_code") == 429 and retry_after and attempt < 3:
            time.sleep(max(1, int(retry_after)))
            continue
        raise RuntimeError(f"Telegram rejected the message: {data.get('description', 'unknown error')}")

    raise RuntimeError("Telegram rate limit persisted after retries.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--previous-ref",
        default="",
        help="Git ref containing the previous public snapshot when state is not initialized",
    )
    parser.add_argument(
        "--state-file",
        default="",
        help="Repository-relative JSON file used to avoid sending the same vacancy twice",
    )
    parser.add_argument(
        "--resend-from-ref",
        default="",
        help="Explicitly resend the vacancies added after this ref, ignoring the notification state",
    )
    args = parser.parse_args()

    current = _load(SNAPSHOT)
    state_path = _resolve_state_path(args.state_file) if args.state_file else None
    state_keys = _load_state(state_path)
    if args.resend_from_ref:
        previous = _snapshot_from_ref(args.resend_from_ref)
        known_keys = {row["key"] for row in _rows(previous)}
    elif state_keys is None:
        previous = _snapshot_from_ref(args.previous_ref) if args.previous_ref else _head_snapshot()
        known_keys = {row["key"] for row in _rows(previous)}
    else:
        known_keys = state_keys

    current_rows = _rows(current)
    rows = _unnotified_rows(current, known_keys)
    print(f"Telegram: {len(rows)} vagas novas detectadas.")
    if not rows:
        if state_path and not args.dry_run:
            _write_state(state_path, known_keys | {row["key"] for row in current_rows}, current)
        return

    groups = _groups(rows)
    if args.dry_run:
        print(f"Dry-run: seriam enviados {len(groups)} grupos.")
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram não configurado: faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID.")
        return

    notified_keys = set(known_keys)
    for index, group in enumerate(groups, start=1):
        _send(token, chat_id, _text(group, index, len(groups)))
        notified_keys.update(row["key"] for row in group)
        # Persist after each successful group so a later retry can resume
        # without repeating groups already accepted by Telegram.
        _write_state(state_path, notified_keys, current)
    if state_path:
        _write_state(state_path, notified_keys | {row["key"] for row in current_rows}, current)
    print(f"Telegram: {len(groups)} grupo(s) enviado(s).")


if __name__ == "__main__":
    main()
