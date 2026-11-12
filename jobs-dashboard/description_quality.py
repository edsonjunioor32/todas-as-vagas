# -*- coding: utf-8 -*-
"""Deterministic quality assessment for privately collected descriptions.

The assessment is intentionally derived from stored evidence. It never claims
that a page is semantically complete merely because a request succeeded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


QUALITY_LEVELS = (
    "complete_candidate",
    "usable",
    "short",
    "empty",
    "blocked",
    "gone",
    "stale",
    "pending",
)

_GONE_STATUSES = frozenset({"gone", "removed", "not_found"})

_BLOCKED_STATUSES = frozenset(
    {
        "robots_denied",
        "robots_unavailable",
        "network_error",
        "response_too_large",
        "parse_error",
        "timeout",
        "error",
    }
)

_SECTION_PATTERNS = (
    re.compile(
        r"\b(responsabilidades?|atividades?|atribuicoes?|"
        r"o que voce fara|what you will do)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(requisitos?|qualificacoes?|competencias?|"
        r"skills?|requirements?|experiencia)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(beneficios?|benefits?|o que oferecemos|we offer)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(localizacao|location|sobre a vaga|about the role|"
        r"job description)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class QualityAssessment:
    """One explainable quality result for one stored row."""

    level: str
    reason: str
    character_count: int
    section_count: int


def _value(row: Mapping[str, Any], key: str, default: Any = "") -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _clean_description(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _section_count(description: str) -> int:
    return sum(1 for pattern in _SECTION_PATTERNS if pattern.search(description))


def _is_blocked(status: str) -> bool:
    return (
        status in _BLOCKED_STATUSES
        or status.startswith("http_")
        or status.startswith("network_")
    )


def assess_row(
    row: Mapping[str, Any],
    *,
    now: datetime | None = None,
    stale_after_days: int = 30,
) -> QualityAssessment:
    """Classify one stored description without network or database writes."""

    status = str(_value(row, "status")).strip().lower()
    description = _clean_description(_value(row, "description"))
    character_count = len(description)
    sections = _section_count(description)

    http_status = _value(row, "http_status")
    error = str(_value(row, "error")).strip()
    if status in _GONE_STATUSES:
        return QualityAssessment("gone", "gone", character_count, sections)
    try:
        numeric_http_status = int(http_status or 0)
    except (TypeError, ValueError):
        numeric_http_status = 0
    if numeric_http_status in {404, 410} and (
        status == "stale"
        or status.startswith("http_")
    ):
        return QualityAssessment(
            "gone",
            f"http_{numeric_http_status}",
            character_count,
            sections,
        )
    if status == "stale":
        if numeric_http_status >= 400:
            return QualityAssessment(
                "blocked",
                f"http_{numeric_http_status}",
                character_count,
                sections,
            )
        if error:
            return QualityAssessment(
                "blocked",
                "refresh_failed",
                character_count,
                sections,
            )
        return QualityAssessment("stale", "stored_status_stale", character_count, sections)

    if _is_blocked(status):
        return QualityAssessment("blocked", status or "blocked", character_count, sections)

    if not description:
        if status in {"", "pending"}:
            return QualityAssessment("pending", "not_attempted", 0, 0)
        return QualityAssessment(
            "empty",
            status or "empty_description",
            0,
            0,
        )

    checked_at = _parse_timestamp(_value(row, "checked_at"))
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    cutoff = reference - timedelta(days=max(0, int(stale_after_days)))
    if checked_at is not None and checked_at < cutoff:
        return QualityAssessment(
            "stale",
            "refresh_window_exceeded",
            character_count,
            sections,
        )

    if character_count >= 1000 and sections >= 2:
        return QualityAssessment(
            "complete_candidate",
            "long_text_with_multiple_sections",
            character_count,
            sections,
        )
    if character_count >= 200:
        return QualityAssessment(
            "usable",
            "text_at_least_200_chars",
            character_count,
            sections,
        )
    return QualityAssessment(
        "short",
        "text_below_200_chars",
        character_count,
        sections,
    )
