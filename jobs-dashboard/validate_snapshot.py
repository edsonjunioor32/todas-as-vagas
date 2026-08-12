# -*- coding: utf-8 -*-
"""Integrity and privacy checks for the GitHub Pages snapshot."""
import json
import os
import sys
from datetime import date
from pathlib import Path

import storage

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "docs" / "data" / "vagas.json"
REQUIRED_COLUMNS = {
    "title", "src", "cmp", "area", "sen", "wm", "mk", "co", "city",
    "pub", "seen", "exp", "url", "np", "sk", "smin", "smax", "cur",
    "pcd", "blind", "ct",
}
FORBIDDEN_KEYS = {"description", "descricao", "requirements", "requisitos", "email", "phone"}


def fail(message):
    print(f"ERRO: {message}", file=sys.stderr)
    raise SystemExit(1)


def main():
    if not SNAPSHOT.exists():
        fail(f"arquivo ausente: {SNAPSHOT}")
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    count = int(data.get("count") or 0)
    minimum = int(os.environ.get("MIN_PUBLIC_JOBS") or 1)
    if count < minimum:
        fail(f"somente {count} vagas; mínimo esperado: {minimum}")
    if FORBIDDEN_KEYS & set(data):
        fail("a raiz contém campos privados ou descrições")

    columns = data.get("jobs") or {}
    missing = REQUIRED_COLUMNS - set(columns)
    if missing:
        fail(f"colunas ausentes: {', '.join(sorted(missing))}")
    for name in REQUIRED_COLUMNS:
        if len(columns[name]) != count:
            fail(f"coluna {name} tem {len(columns[name])} itens; esperado: {count}")

    dictionaries = data.get("dict") or {}
    for name in ("source", "company", "area", "seniority", "work_model", "market", "country", "currency"):
        if name not in dictionaries:
            fail(f"dicionário ausente: {name}")
    for index, url in enumerate(columns["url"]):
        if not str(url).startswith("https://"):
            fail(f"URL inválida na linha {index}: {url}")
    max_age_months = int(data.get("max_age_months") or 0)
    expected_cutoff = storage.publication_cutoff(
        data.get("generated_date") or date.today().isoformat(), max_age_months
    )
    if data.get("publication_cutoff") != expected_cutoff:
        fail("data de corte de publicação ausente ou inconsistente")
    old_dates = [value for value in columns["pub"] if value and value < expected_cutoff]
    if old_dates:
        fail(f"há {len(old_dates)} vagas publicadas antes do corte {expected_cutoff}")
    source_names = dictionaries["source"]
    country_names = dictionaries["country"]
    autozone_foreign = [
        index for index in range(count)
        if source_names[columns["src"][index]] == "autozone"
        and country_names[columns["co"][index]] != "BR"
    ]
    if autozone_foreign:
        fail(f"há {len(autozone_foreign)} vagas estrangeiras da AutoZone")
    if any("<script" in str(title).lower() for title in columns["title"]):
        fail("título contém marcação de script")
    print(
        f"OK: {count} vagas, {len(dictionaries['source'])} portais, "
        f"publicadas desde {expected_cutoff}, sem descrições completas"
    )


if __name__ == "__main__":
    main()
