#!/usr/bin/env python3
"""Preflight checks for catalog snapshots before any public write."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
PRIVATE_KEYS = {
    "description",
    "descricao",
    "requirements",
    "requisitos",
    "email",
    "phone",
}
REQUIRED_COLUMNS = {
    "title",
    "src",
    "cmp",
    "area",
    "sen",
    "wm",
    "mk",
    "co",
    "city",
    "pub",
    "seen",
    "exp",
    "url",
    "np",
    "sk",
    "smin",
    "smax",
    "cur",
    "pcd",
    "blind",
    "ct",
    "status",
    "type",
    "publication_type",
}
REQUIRED_DICTIONARIES = {
    "source",
    "company",
    "area",
    "seniority",
    "work_model",
    "market",
    "country",
    "currency",
}


class PreflightError(ValueError):
    """Raised when a snapshot is unsafe to use as collection input/output."""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_timestamp(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise PreflightError(f"{field} ausente")
    try:
        return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as error:
        raise PreflightError(f"{field} inválido: {text!r}") from error


def load_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PreflightError(f"fotografia ausente: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreflightError(f"fotografia inválida: {path}: {error}") from error
    if not isinstance(data, dict):
        raise PreflightError(f"fotografia não é um objeto JSON: {path}")
    return data


def validate_shape(
    data: dict[str, Any],
    path: Path,
    *,
    minimum_count: int,
    expected_max_age_months: int,
    now: datetime | None = None,
) -> tuple[int, datetime]:
    """Validate the public contract without contacting any portal."""
    if PRIVATE_KEYS & set(data):
        keys = ", ".join(sorted(PRIVATE_KEYS & set(data)))
        raise PreflightError(f"fotografia contém campos privados na raiz: {keys}")

    try:
        count = int(data.get("count") or 0)
    except (TypeError, ValueError) as error:
        raise PreflightError("count inválido") from error
    if count < minimum_count:
        raise PreflightError(
            f"fotografia contém {count} vagas; mínimo esperado: {minimum_count}"
        )

    generated_at = parse_timestamp(data.get("generated_at"), "generated_at")
    reference = _as_utc(now or datetime.now(UTC))
    if generated_at > reference + timedelta(minutes=10):
        raise PreflightError(
            f"generated_at está no futuro: {generated_at.isoformat()}"
        )

    try:
        generated_date = date.fromisoformat(str(data.get("generated_date") or ""))
    except ValueError as error:
        raise PreflightError("generated_date inválido") from error
    if generated_date > reference.date() + timedelta(days=1):
        raise PreflightError(f"generated_date está no futuro: {generated_date}")

    try:
        max_age_months = int(data.get("max_age_months") or 0)
    except (TypeError, ValueError) as error:
        raise PreflightError("max_age_months inválido") from error
    if max_age_months != expected_max_age_months:
        raise PreflightError(
            "max_age_months incompatível: "
            f"{max_age_months}; esperado: {expected_max_age_months}"
        )
    if not str(data.get("publication_cutoff") or "").strip():
        raise PreflightError("publication_cutoff ausente")

    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        raise PreflightError("jobs ausente ou inválido")
    missing_columns = REQUIRED_COLUMNS - set(jobs)
    if missing_columns:
        raise PreflightError(
            "colunas ausentes: " + ", ".join(sorted(missing_columns))
        )
    for name in REQUIRED_COLUMNS:
        values = jobs.get(name)
        if not isinstance(values, list) or len(values) != count:
            actual = len(values) if isinstance(values, list) else "não-lista"
            raise PreflightError(
                f"coluna {name} tem {actual} itens; esperado: {count}"
            )
    if PRIVATE_KEYS & set(jobs):
        keys = ", ".join(sorted(PRIVATE_KEYS & set(jobs)))
        raise PreflightError(f"fotografia contém colunas privadas: {keys}")

    dictionaries = data.get("dict")
    if not isinstance(dictionaries, dict):
        raise PreflightError("dict ausente ou inválido")
    missing_dictionaries = REQUIRED_DICTIONARIES - set(dictionaries)
    if missing_dictionaries:
        raise PreflightError(
            "dicionários ausentes: " + ", ".join(sorted(missing_dictionaries))
        )

    return count, generated_at


def check_before_collection(
    snapshot_path: Path,
    *,
    minimum_count: int,
    expected_max_age_months: int,
    now: datetime | None = None,
) -> str:
    data = load_snapshot(snapshot_path)
    count, generated_at = validate_shape(
        data,
        snapshot_path,
        minimum_count=minimum_count,
        expected_max_age_months=expected_max_age_months,
        now=now,
    )
    return (
        "OK: fotografia anterior íntegra e disponível para retomada "
        f"({count} vagas; generated_at={generated_at.isoformat()})"
    )


def check_after_collection(
    snapshot_path: Path,
    previous_path: Path,
    *,
    minimum_count: int,
    expected_max_age_months: int,
    minimum_ratio: float,
    now: datetime | None = None,
) -> str:
    current = load_snapshot(snapshot_path)
    previous = load_snapshot(previous_path)
    current_count, current_generated_at = validate_shape(
        current,
        snapshot_path,
        minimum_count=minimum_count,
        expected_max_age_months=expected_max_age_months,
        now=now,
    )
    previous_count, previous_generated_at = validate_shape(
        previous,
        previous_path,
        minimum_count=minimum_count,
        expected_max_age_months=expected_max_age_months,
        now=now,
    )
    if current_generated_at <= previous_generated_at:
        raise PreflightError(
            "o snapshot não foi renovado: "
            f"atual={current_generated_at.isoformat()}, "
            f"anterior={previous_generated_at.isoformat()}"
        )
    if previous_count >= 10000 and current_count < previous_count * minimum_ratio:
        raise PreflightError(
            "redução insegura antes da publicação: "
            f"{previous_count} para {current_count} vagas "
            f"(mínimo relativo {minimum_ratio:.0%})"
        )
    return (
        "OK: novo snapshot aprovado para publicação "
        f"({current_count} vagas; generated_at={current_generated_at.isoformat()}; "
        f"anterior={previous_generated_at.isoformat()})"
    )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("before-collection", "after-collection"),
        required=True,
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--previous-snapshot", type=Path)
    parser.add_argument(
        "--min-count",
        type=int,
        default=_env_int("PREFLIGHT_MIN_JOBS", 500),
    )
    parser.add_argument(
        "--expected-max-age-months",
        type=int,
        default=_env_int("PREFLIGHT_MAX_AGE_MONTHS", 2),
    )
    parser.add_argument(
        "--min-allowed-ratio",
        type=float,
        default=_env_float("PREFLIGHT_MIN_ALLOWED_RATIO", 0.5),
    )
    args = parser.parse_args()

    try:
        if args.mode == "before-collection":
            message = check_before_collection(
                args.snapshot,
                minimum_count=args.min_count,
                expected_max_age_months=args.expected_max_age_months,
            )
        else:
            if args.previous_snapshot is None:
                raise PreflightError(
                    "--previous-snapshot é obrigatório no modo after-collection"
                )
            message = check_after_collection(
                args.snapshot,
                args.previous_snapshot,
                minimum_count=args.min_count,
                expected_max_age_months=args.expected_max_age_months,
                minimum_ratio=args.min_allowed_ratio,
            )
    except PreflightError as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 1

    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
