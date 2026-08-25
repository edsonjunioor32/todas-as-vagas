# -*- coding: utf-8 -*-
"""Send newly published public vacancies to a Telegram chat.

The script compares the generated public snapshot with the version stored at
HEAD before the pipeline writes its new files. It deliberately uses only the
public fields already exported for the website.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "docs" / "data" / "vagas.json"
TI_RE = re.compile(
    r"\b(?:ti|tecnologia|software|sistemas?|suporte|desenvolv|devops|"
    r"dados?|analista de dados|engenheir|programa[cç]|infraestrutura|"
    r"cloud|seguran[cç]a|produto digital|qa|testes?|api|sre)\b",
    re.I,
)


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _head_snapshot():
    try:
        raw = subprocess.check_output(
            ["git", "show", "HEAD:docs/data/vagas.json"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return json.loads(raw)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return {"count": 0, "jobs": {}, "dict": {}}


def _value(snapshot, name, index, dictionary=None):
    values = snapshot.get("jobs", {}).get(name, [])
    value = values[index] if index < len(values) else ""
    if dictionary:
        entries = snapshot.get("dict", {}).get(dictionary, [])
        return entries[value] if isinstance(value, int) and value < len(entries) else ""
    return value or ""


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
        remote = str(work_model).casefold() in {"remote", "remoto", "remota"}
        is_ti = bool(TI_RE.search(" ".join(map(str, (title, area, skills)))))
        rows.append({
            "key": f"{_value(snapshot, 'src', index, 'source')}:{url}",
            "title": title,
            "company": _value(snapshot, "cmp", index, "company"),
            "source": _value(snapshot, "src", index, "source"),
            "url": url,
            "work_model": work_model,
            "city": _value(snapshot, "city", index),
            "published": _value(snapshot, "pub", index),
            "remote": remote,
            "ti": is_ti,
        })
    return rows


def _new_rows(current, previous):
    known = {row["key"] for row in _rows(previous)}
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
        company = html.escape(str(row["company"] or "Empresa"))
        modality = html.escape(str(row["work_model"] or "Não informada"))
        city = html.escape(str(row["city"] or "Brasil"))
        source = html.escape(str(row["source"] or "Portal"))
        url = html.escape(str(row["url"]), quote=True)
        lines.append(
            f"• <a href=\"{url}\"><b>{title}</b></a>\n"
            f"  {company} · {modality} · {city}\n"
            f"  {source}"
        )
    return "\n".join(lines)


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
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        raise RuntimeError(f"Telegram request failed: {error}") from error
    if not data.get("ok"):
        raise RuntimeError(f"Telegram rejected the message: {data.get('description', 'unknown error')}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    current = _load(SNAPSHOT)
    rows = _new_rows(current, _head_snapshot())
    print(f"Telegram: {len(rows)} vagas novas detectadas.")
    if not rows:
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram não configurado: faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID.")
        return

    groups = [rows[index:index + 10] for index in range(0, len(rows), 10)]
    if args.dry_run:
        print(f"Dry-run: seriam enviados {len(groups)} grupos.")
        return
    for index, group in enumerate(groups, start=1):
        _send(token, chat_id, _text(group, index, len(groups)))
    print(f"Telegram: {len(groups)} grupo(s) enviado(s).")


if __name__ == "__main__":
    main()
