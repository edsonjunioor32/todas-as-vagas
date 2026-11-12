# -*- coding: utf-8 -*-
"""Integrity and privacy checks for the GitHub Pages snapshot."""
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import glassdoor
import storage

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "docs" / "data" / "vagas.json"
REQUIRED_COLUMNS = {
    "title", "src", "cmp", "area", "sen", "wm", "mk", "co", "city",
    "pub", "seen", "exp", "url", "np", "sk", "smin", "smax", "cur",
    "pcd", "blind", "ct", "status", "type", "publication_type",
}
GLASSDOOR_COLUMNS = {"gdr", "gdc", "gdu", "gdt"}
GLASSDOOR_FALLBACK_COLUMNS = {"gfr", "gfu", "gft"}
FORBIDDEN_KEYS = {"description", "descricao", "requirements", "requisitos", "email", "phone"}
GUPY_TALENT_POOL_RE = re.compile(
    r"\b(?:banco\s+(?:de\s+)?talentos?|talent\s+pool)\b", re.I
)


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


def _source_counts(snapshot):
    counts = {}
    for source, value in (snapshot.get("source_counts") or {}).items():
        source = str(source).strip()
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            continue
        if source and count > 0:
            counts[source] = count
    return counts


def _parse_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_source_continuity(current, previous, failed_sources):
    """Reject silent source loss between consecutive public snapshots.

    A partial run can legitimately publish fewer rows, but it must not make a
    previously present source disappear without either a current health
    update or an explicit failure. This is what distinguishes an unattempted
    LinkedIn-only run from a full run in which a portal returned no jobs.
    """
    previous_counts = _source_counts(previous)
    if not previous_counts:
        return
    current_counts = _source_counts(current)
    previous_health = previous.get("source_last_success_at") or {}
    current_health = current.get("source_last_success_at") or {}
    missing = [
        source for source in previous_counts
        if not current_counts.get(source)
    ]
    unconfirmed = []
    for source in missing:
        if source in failed_sources:
            continue
        before = _parse_timestamp(previous_health.get(source))
        after = _parse_timestamp(current_health.get(source))
        if after is not None and (before is None or after > before):
            continue
        unconfirmed.append(source)
    if not unconfirmed:
        return
    scope = os.environ.get("CATALOG_COLLECTION_SCOPE", "unknown").strip() or "unknown"
    collected = sorted(
        str(source).strip()
        for source in (current.get("collected_source_counts") or {})
        if str(source).strip()
    )
    sample = ", ".join(sorted(unconfirmed)[:20])
    suffix = f"; outras: {len(unconfirmed) - 20}" if len(unconfirmed) > 20 else ""
    fail(
        "fontes presentes no snapshot anterior desapareceram sem confirmação "
        f"(escopo={scope}; coletadas agora={', '.join(collected) or 'nenhuma'}): "
        f"{sample}{suffix}. A publicação foi bloqueada."
    )


def main():
    if not SNAPSHOT.exists():
        fail(f"arquivo ausente: {SNAPSHOT}")
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    count = int(data.get("count") or 0)
    minimum = int(os.environ.get("MIN_PUBLIC_JOBS") or 1)
    if count < minimum:
        fail(f"somente {count} vagas; mínimo esperado: {minimum}")

    previous = None
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
    if previous is not None:
        validate_source_continuity(data, previous, set(failed_sources))
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
            print(
                "AVISO: proporção de vagas preservadas acima do nível de atenção: "
                f"{preserved_ratio:.2%} (referência {max_preserved_ratio:.2%}); "
                "as validações estruturais continuam obrigatórias, mas a publicação "
                "não será bloqueada apenas por indisponibilidade parcial de fontes.",
                file=sys.stderr,
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

    glassdoor_columns = GLASSDOOR_COLUMNS & set(columns)
    if glassdoor_columns and glassdoor_columns != GLASSDOOR_COLUMNS:
        fail(
            "colunas Glassdoor incompletas: "
            + ", ".join(sorted(glassdoor_columns))
        )
    if glassdoor_columns == GLASSDOOR_COLUMNS:
        for name in sorted(GLASSDOOR_COLUMNS):
            if len(columns[name]) != count:
                fail(f"coluna {name} tem {len(columns[name])} itens; esperado: {count}")
        for index, value in enumerate(columns["gdr"]):
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 5:
                    fail(f"nota Glassdoor inválida na linha {index}: {value!r}")
        for index, value in enumerate(columns["gdc"]):
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    fail(f"quantidade de avaliações Glassdoor inválida na linha {index}: {value!r}")
        for index, value in enumerate(columns["gdu"]):
            if value is not None and not glassdoor.is_canonical_profile_url(value):
                fail(f"URL Glassdoor inválida na linha {index}: {value!r}")
        for index, value in enumerate(columns["gdt"]):
            if value is not None:
                try:
                    date.fromisoformat(str(value))
                except (TypeError, ValueError):
                    fail(f"data Glassdoor inválida na linha {index}: {value!r}")

    fallback_columns = GLASSDOOR_FALLBACK_COLUMNS & set(columns)
    if fallback_columns and fallback_columns != GLASSDOOR_FALLBACK_COLUMNS:
        fail(
            "colunas de fallback Glassdoor incompletas: "
            + ", ".join(sorted(fallback_columns))
        )
    if fallback_columns == GLASSDOOR_FALLBACK_COLUMNS:
        for name in sorted(GLASSDOOR_FALLBACK_COLUMNS):
            if len(columns[name]) != count:
                fail(f"coluna {name} tem {len(columns[name])} itens; esperado: {count}")
        for index, value in enumerate(columns["gfr"]):
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 5:
                    fail(f"nota de fallback Glassdoor inválida na linha {index}: {value!r}")
        for index, value in enumerate(columns["gfu"]):
            if value is not None and not glassdoor.is_canonical_reference_url(value):
                fail(f"URL de referência Glassdoor inválida na linha {index}: {value!r}")
        for index, value in enumerate(columns["gft"]):
            if value is not None:
                try:
                    date.fromisoformat(str(value))
                except (TypeError, ValueError):
                    fail(f"data de fallback Glassdoor inválida na linha {index}: {value!r}")

    dictionaries = data.get("dict") or {}
    for name in ("source", "company", "area", "seniority", "work_model", "market", "country", "currency"):
        if name not in dictionaries:
            fail(f"dicionário ausente: {name}")
    urls = [str(url or "").strip() for url in columns["url"]]
    duplicate_count = len(urls) - len(set(urls))
    duplicate_ratio = duplicate_count / count if count else 0.0
    max_duplicate_ratio = env_float("MAX_DUPLICATE_URL_RATIO", 0.005)
    if max_duplicate_ratio >= 0 and duplicate_ratio > max_duplicate_ratio:
        print(
            "AVISO: proporção de URLs repetidas acima da referência: "
            f"{duplicate_ratio:.2%} ({duplicate_count} linhas; "
            f"referência {max_duplicate_ratio:.2%}); a publicação continuará, "
            "pois vagas distintas podem compartilhar o mesmo link de candidatura "
            "e a identidade da vaga é validada separadamente.",
            file=sys.stderr,
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
    generated_date = data.get("generated_date") or date.today().isoformat()
    expected_cutoff = storage.publication_cutoff(
        generated_date, max_age_months
    )
    if data.get("publication_cutoff") != expected_cutoff:
        fail("data de corte de publicação ausente ou inconsistente")
    source_names = dictionaries["source"]
    old_indexes = [
        index for index, value in enumerate(columns["pub"])
        if value and value < expected_cutoff
        and source_names[columns["src"][index]] not in storage.ACTIVE_PUBLIC_FEED_SOURCES
    ]
    if old_indexes:
        fail(f"há {len(old_indexes)} vagas publicadas antes do corte {expected_cutoff}")
    gupy_cutoff = storage.months_ago(
        date.fromisoformat(generated_date), max(0, max_age_months)
    ).isoformat()
    gupy_invalid = []
    for index in range(count):
        if source_names[columns["src"][index]] != "gupy":
            continue
        published = str(columns["pub"][index] or "")[:10]
        title = str(columns["title"][index] or "")
        status = str(columns["status"][index] or "").strip().casefold()
        job_type = str(columns["type"][index] or "").strip().casefold()
        publication_type = str(
            columns["publication_type"][index] or ""
        ).strip().casefold()
        expires = str(columns["exp"][index] or "")[:10]
        public_evidence = (
            (status == "published" and publication_type == "external")
            or (status == "public_search" and publication_type == "candidate_mcp")
        )
        if (
            not public_evidence
            or not job_type
            or job_type == "vacancy_type_talent_pool"
            or GUPY_TALENT_POOL_RE.search(title)
            or not published
            or published < gupy_cutoff
            or (expires and expires < generated_date)
        ):
            gupy_invalid.append(index)
    if gupy_invalid:
        fail(
            f"há {len(gupy_invalid)} vagas Gupy sem evidência pública confirmada, "
            f"fora do corte estrito de {max_age_months} meses ({gupy_cutoff}) "
            "ou com prazo expirado"
        )
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
