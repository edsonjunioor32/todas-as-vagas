# -*- coding: utf-8 -*-
"""Adapter for the public LinkedIn Easy Apply snapshot.

The LinkedIn collector runs in its own GitHub-hosted job because the JobSpy
dependency is not part of the ARM64 catalog runner. It writes a small,
public-only snapshot; this adapter validates that snapshot and feeds the same
ETL, history, deduplication and publication path used by every other source.
"""
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

from ._common import is_brazil_location, iso_date, job, work_model_label

SOURCE = "linkedin"
DEFAULT_SNAPSHOT = (
    Path(__file__).resolve().parents[2] / "docs" / "data" / "linkedin_vagas.json"
)
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_SNAPSHOT_MAX_AGE_HOURS = 36
JOB_URL_RE = re.compile(
    r"^https://(?:www\.)?linkedin\.com/jobs/view/(\d+)(?:[/?#]|$)",
    re.IGNORECASE,
)


def _snapshot_path():
    configured = str(os.environ.get("LINKEDIN_SNAPSHOT_PATH") or "").strip()
    return Path(configured) if configured else DEFAULT_SNAPSHOT


def _integer_env(name, default, minimum=1, maximum=365):
    try:
        value = int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _snapshot_age_hours():
    try:
        value = float(
            os.environ.get(
                "LINKEDIN_SNAPSHOT_MAX_AGE_HOURS",
                DEFAULT_SNAPSHOT_MAX_AGE_HOURS,
            )
        )
    except (TypeError, ValueError):
        value = DEFAULT_SNAPSHOT_MAX_AGE_HOURS
    return max(1.0, value)


def _parse_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("LinkedIn snapshot has an invalid generated_at") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _amount(value):
    if value in (None, ""):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount >= 0 else None


def _list_of_strings(value):
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize(raw, today=None):
    if not isinstance(raw, dict):
        return None
    if raw.get("easyApply") is not True and raw.get("easy_apply") is not True:
        return None

    url = str(raw.get("url") or "").strip()
    match = JOB_URL_RE.fullmatch(url)
    if not match:
        return None

    title = str(raw.get("title") or "").strip()
    company = str(raw.get("company") or "").strip()
    location = str(raw.get("location") or "").strip()
    if not title or not company or not location or not is_brazil_location(location):
        return None

    published = iso_date(raw.get("publishedAt") or raw.get("published_at"))
    if not published:
        return None
    published_day = date.fromisoformat(published[:10])
    today = today or date.today()
    max_age = _integer_env(
        "LINKEDIN_MAX_AGE_DAYS",
        DEFAULT_MAX_AGE_DAYS,
        minimum=1,
        maximum=90,
    )
    if published_day > today or (today - published_day).days > max_age:
        return None

    native_id = str(raw.get("native_id") or "").strip() or f"li-{match.group(1)}"
    raw_model = str(raw.get("workplaceType") or raw.get("workplace_type") or "")
    work_model = work_model_label(raw=raw_model)

    salary_min = _amount(raw.get("salaryMin", raw.get("salary_min")))
    salary_max = _amount(raw.get("salaryMax", raw.get("salary_max")))
    currency = str(raw.get("currency") or "").strip() or None

    return job(
        SOURCE,
        native_id,
        title=title,
        company=company,
        url=url,
        work_model=work_model,
        city=location,
        country="BR",
        market="BR",
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency if salary_min is not None or salary_max is not None else None,
        published_date=published,
        skills=_list_of_strings(raw.get("skills"))[:12],
        categories=_list_of_strings(raw.get("categories"))[:12],
        contract_types=_list_of_strings(raw.get("contract_types"))[:8],
        pcd=bool(raw.get("pcd") or raw.get("pcdOnly")),
        # Descriptions are intentionally not copied from the LinkedIn snapshot.
        description="",
    )


def fetch():
    path = _snapshot_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"LinkedIn snapshot not found: {path}") from error
    except (OSError, ValueError) as error:
        raise RuntimeError(f"LinkedIn snapshot is unreadable: {error}") from error

    if not isinstance(payload, dict):
        raise RuntimeError("LinkedIn snapshot must be a JSON object")
    if payload.get("schema_version") != 1:
        raise RuntimeError("LinkedIn snapshot schema_version is unsupported")
    if str(payload.get("source") or "").strip().casefold() != SOURCE:
        raise RuntimeError("LinkedIn snapshot source is not LinkedIn")
    if str(payload.get("filter") or "").strip().casefold() != "easy_apply":
        raise RuntimeError("LinkedIn snapshot is not restricted to Easy Apply")

    generated_at = _parse_timestamp(payload.get("generated_at"))
    if generated_at is None:
        raise RuntimeError("LinkedIn snapshot has no generated_at")
    age_hours = (
        datetime.now(timezone.utc) - generated_at
    ).total_seconds() / 3600
    if age_hours < -2:
        raise RuntimeError("LinkedIn snapshot timestamp is in the future")
    if age_hours > _snapshot_age_hours():
        raise RuntimeError(
            f"LinkedIn snapshot is stale ({age_hours:.1f}h; "
            f"limit {_snapshot_age_hours():.1f}h)"
        )

    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list):
        raise RuntimeError("LinkedIn snapshot jobs must be a list")

    today = date.today()
    rows = []
    seen = set()
    for raw in raw_jobs:
        row = _normalize(raw, today=today)
        if not row:
            continue
        key = f"{row['native_id']}|{row['url']}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    if not rows:
        raise RuntimeError(
            "LinkedIn snapshot contains no valid Brazilian Easy Apply vacancies"
        )
    return rows
