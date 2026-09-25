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


def env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def main():
    if not SNAPSHOT.exists():
        fail(f"arquivo ausente: {SNAPSHOT}")
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    count = int(data.get("count") or 0)
    minimum = int(os.environ.get("MIN_PUBLIC_JOBS") or 1)
    if count < minimum:
        fail(f"somente {count} vagas; mínimo esperado: {minimum}")

    previous_path = os.environ.get("PREVIOUS_SNAPSHOT_PATH", "").strip()
    if previous_path:
        previous_file = Path(previous_path)
        if not previous_file.exists():
            fail(f"fotografia anterior ausente: {previous_file}")
        try:
            previous = json.loads(previous_file.read_text(encoding="utf-8"))
            previous_count = int(previous.get("count") or 0)
            ratio = float(os.environ.get("MIN_ALLOWED_PUBLIC_RATIO") or "0.5")
            guarded_minimum = int(os.environ.get("MIN_GUARDED_PUBLIC_JOBS") or "10000")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            fail(f"fotografia anterior inválida: {error}")
        if (
            previous_count >= guarded_minimum
            and count < previous_count * ratio
        ):
            fail(
                "redução insegura do snapshot geral: "
                f"{previous_count} para {count} vagas; publicação bloqueada"
            )
    failed_sources = sorted({
        str(source).strip() for source in (data.get("failed_sources") or [])
        if str(source).strip()
    })
    max_failed_sources = env_int("MAX_FAILED_SOURCES", 50)
    if max_failed_sources >= 0 and len(failed_sources) > max_failed_sources:
        print(
            "AVISO: fontes indisponíveis acima do limite de alerta: "
            f"{len(failed_sources)} (limite {max_failed_sources}); "
            "os dados anteriores dessas fontes serão preservados e a "
            "publicação das demais fontes continuará.",
            file=sys.stderr,
        )

    collected_source_counts = data.get("collected_source_counts") or {}
    try:
        collected_count = int(data.get("collected_count") or sum(
            max(0, int(value or 0)) for value in collected_source_counts.values()
        ))
    except (TypeError, ValueError):
        fail("métrica collected_count inválida")
    preserved_count = max(0, int(data.get("preserved_count") or count - collected_count))
    if count:
        preserved_ratio = preserved_count / count
        max_preserved_ratio = env_float("MAX_PRESERVED_PUBLIC_RATIO", 0.50)
        if max_preserved_ratio >= 0 and preserved_ratio > max_preserved_ratio:
            fail(
                "proporção de vagas preservadas acima do limite seguro: "
                f"{preserved_ratio:.2%} (máximo {max_preserved_ratio:.2%})"
            )

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
    urls = [str(url or "").strip() for url in columns["url"]]
    duplicate_count = len(urls) - len(set(urls))
    duplicate_ratio = duplicate_count / count if count else 0.0
    max_duplicate_ratio = env_float("MAX_DUPLICATE_URL_RATIO", 0.005)
    if max_duplicate_ratio >= 0 and duplicate_ratio > max_duplicate_ratio:
        fail(
            "proporção de URLs duplicadas acima do limite seguro: "
            f"{duplicate_ratio:.2%} ({duplicate_count} duplicadas)"
        )

    generated_date = str(data.get("generated_date") or date.today().isoformat())
    for index, url in enumerate(columns["url"]):
        if not str(url).startswith("https://"):
            fail(f"URL inválida na linha {index}: {url}")
    for index, published in enumerate(columns["pub"]):
        if published and str(published)[:10] > generated_date:
            fail(
                f"data de publicação futura na linha {index}: "
                f"{published} > {generated_date}"
            )
    max_age_months = int(data.get("max_age_months") or 0)
    expected_cutoff = storage.publication_cutoff(
        data.get("generated_date") or date.today().isoformat(), max_age_months
    )
    if data.get("publication_cutoff") != expected_cutoff:
        fail("data de corte de publicação ausente ou inconsistente")
    source_names = dictionaries["source"]
    generated_date = data.get("generated_date") or date.today().isoformat()
    old_indexes = [
        index for index, value in enumerate(columns["pub"])
        if value and value < expected_cutoff
        and not (
            source_names[columns["src"][index]] == "gupy"
            and columns["exp"][index]
            and columns["exp"][index] >= generated_date
        )
        and source_names[columns["src"][index]] not in storage.ACTIVE_PUBLIC_FEED_SOURCES
    ]
    if old_indexes:
        fail(f"há {len(old_indexes)} vagas publicadas antes do corte {expected_cutoff}")
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
