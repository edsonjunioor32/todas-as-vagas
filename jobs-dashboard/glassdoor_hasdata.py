# -*- coding: utf-8 -*-
"""Complemento das notas pelo MCP Glassdoor da HasData.

Extraído de ``glassdoor.py`` em 16/11/2026 sem mudança de comportamento;
``glassdoor`` reexporta estes nomes para manter a compatibilidade.
"""
from __future__ import annotations

import json
import os
import time
from datetime import (
    date,
    datetime,
)
from pathlib import Path
from hasdata_glassdoor_mcp import (
    DEFAULT_BACKOFF_SECONDS as HASDATA_DEFAULT_BACKOFF_SECONDS,
    DEFAULT_ENDPOINT as HASDATA_DEFAULT_ENDPOINT,
    DEFAULT_RETRIES as HASDATA_DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS as HASDATA_DEFAULT_TIMEOUT_SECONDS,
    HasDataGlassdoorMcpClient,
)

from glassdoor_common import (
    _env_float,
    _env_int,
    _local_date,
    _MCP_ALLOWED_DOMAINS,
    _MCP_QUERY_ID_RE,
    _PROFILE_ID_RE,
    _rating,
    canonical_reference_url,
    company_key,
    DEFAULT_MCP_MAX_CALLS,
    DEFAULT_MCP_QUERY_PATH,
    GlassdoorConfigurationError,
    hasdata_mcp_enabled,
    MAX_MCP_CALLS,
    MAX_MCP_QUERIES,
    ProfileDataUnavailable,
)


def load_hasdata_queries(path: str | os.PathLike[str] = DEFAULT_MCP_QUERY_PATH) -> list[dict]:
    """Load a bounded, explicit allowlist for optional HasData searches."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GlassdoorConfigurationError(f"manifesto MCP Glassdoor inválido: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise GlassdoorConfigurationError("manifesto MCP Glassdoor com schema_version inválido")
    raw_queries = payload.get("queries")
    if not isinstance(raw_queries, list) or len(raw_queries) > MAX_MCP_QUERIES:
        raise GlassdoorConfigurationError("manifesto MCP Glassdoor precisa de uma lista limitada de queries")
    queries: list[dict] = []
    ids: set[str] = set()
    for index, raw in enumerate(raw_queries):
        if not isinstance(raw, dict):
            raise GlassdoorConfigurationError(f"query MCP Glassdoor {index} não é um objeto")
        if raw.get("approved") is not True or raw.get("enabled", True) is False:
            continue
        query_id = str(raw.get("id") or "").strip().casefold()
        profile_id = str(raw.get("profile_id") or "").strip().casefold()
        keyword = str(raw.get("keyword") or "").strip()
        location = str(raw.get("location") or "").strip()
        if not _MCP_QUERY_ID_RE.fullmatch(query_id) or query_id in ids:
            raise GlassdoorConfigurationError(f"id de query MCP Glassdoor inválido: {query_id!r}")
        if not _PROFILE_ID_RE.fullmatch(profile_id):
            raise GlassdoorConfigurationError(f"profile_id MCP Glassdoor inválido: {profile_id!r}")
        names = raw.get("company_names")
        if not isinstance(names, list) or not names or any(not company_key(name) for name in names):
            raise GlassdoorConfigurationError(f"query MCP {query_id} sem company_names válidos")
        if not keyword or not location:
            raise GlassdoorConfigurationError(f"query MCP {query_id} sem keyword/location")
        domain = str(raw.get("domain") or "glassdoor.com.br").strip().casefold()
        if domain not in _MCP_ALLOWED_DOMAINS:
            raise GlassdoorConfigurationError(f"domínio MCP Glassdoor não aprovado: {domain}")
        sort = str(raw.get("sort") or "recent").strip().casefold()
        if sort not in {"recent", "relevant"}:
            raise GlassdoorConfigurationError(f"sort MCP Glassdoor inválido: {sort}")
        ids.add(query_id)
        queries.append({
            "id": query_id,
            "profile_id": profile_id,
            "company_names": [str(name).strip() for name in names],
            "keyword": keyword,
            "location": location,
            "domain": domain,
            "sort": sort,
        })
    return queries


def _mcp_jobs(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    for container in (payload, payload.get("json"), payload.get("data")):
        if isinstance(container, dict) and isinstance(container.get("jobs"), list):
            return [job for job in container["jobs"] if isinstance(job, dict)]
    return []


def _mcp_company_name(job: dict) -> str:
    for key in ("company", "employer"):
        value = job.get(key)
        if isinstance(value, dict):
            for name_key in ("name", "shortName", "companyName", "employerName"):
                if value.get(name_key):
                    return str(value[name_key]).strip()
        elif value:
            return str(value).strip()
    for key in ("companyName", "employerName"):
        if job.get(key):
            return str(job[key]).strip()
    return ""


def _mcp_job_rating(job: dict) -> float | None:
    candidates: list[object] = [job.get("employerRating"), job.get("companyRating")]
    for key in ("company", "employer"):
        value = job.get(key)
        if isinstance(value, dict):
            candidates.extend(value.get(name) for name in ("rating", "ratingValue", "overallRating"))
    return next((value for value in (_rating(item) for item in candidates) if value is not None), None)


def _mcp_job_url(job: dict) -> str | None:
    for key in ("url", "jobUrl", "job_url", "link"):
        if not job.get(key):
            continue
        try:
            return canonical_reference_url(job[key])
        except (GlassdoorConfigurationError, TypeError, ValueError):
            continue
    return None


def _mcp_match(payload: object, query: dict) -> dict:
    allowed_names = {company_key(name) for name in query.get("company_names") or []}
    jobs = _mcp_jobs(payload)
    returned_names = set()
    for job in jobs:
        returned_company = company_key(_mcp_company_name(job))
        if returned_company:
            returned_names.add(returned_company)
        if not returned_company or returned_company not in allowed_names:
            continue
        rating = _mcp_job_rating(job)
        reference_url = _mcp_job_url(job)
        if rating is not None and reference_url:
            return {
                "rating": rating,
                "reference_url": reference_url,
            }
    names = ", ".join(sorted(returned_names)[:5]) or "nenhuma"
    raise ProfileDataUnavailable(
        "HasData não retornou vaga da empresa aprovada com rating e referência válidos"
        f" (vagas={len(jobs)}; empresas={names})"
    )


def update_hasdata_fallback(
    cache: dict,
    queries: list[dict],
    *,
    now: date | datetime | None = None,
    fetcher=None,
    max_calls: int | None = None,
    sleeper=time.sleep,
) -> tuple[dict, dict]:
    """Optionally add HasData ratings without replacing profile/cache values."""
    current_date = _local_date(now).isoformat()
    summary = {
        "enabled": hasdata_mcp_enabled(),
        "configured": bool(os.environ.get("HASDATA_API_KEY")),
        "attempted": 0,
        "skipped": 0,
        "succeeded": 0,
        "failed": 0,
        "capped": 0,
        "errors": {},
    }
    if not summary["enabled"]:
        summary["disabled_reason"] = "HASDATA_MCP_ENABLED não está habilitado"
        return cache, summary
    if not summary["configured"]:
        summary["disabled_reason"] = "HASDATA_API_KEY não configurada"
        return cache, summary
    if not isinstance(cache, dict) or not isinstance(cache.get("profiles"), dict):
        summary["disabled_reason"] = "cache Glassdoor indisponível"
        return cache, summary

    limit = _env_int("HASDATA_MCP_MAX_CALLS", DEFAULT_MCP_MAX_CALLS, 1, MAX_MCP_CALLS)
    if max_calls is not None:
        limit = min(limit, _env_int("HASDATA_MCP_TEST_MAX_CALLS", int(max_calls), 1, MAX_MCP_CALLS))
    client = None
    if fetcher is None:
        client = HasDataGlassdoorMcpClient(
            os.environ["HASDATA_API_KEY"],
            endpoint=os.environ.get("HASDATA_MCP_ENDPOINT") or HASDATA_DEFAULT_ENDPOINT,
            timeout=_env_float("HASDATA_MCP_TIMEOUT", HASDATA_DEFAULT_TIMEOUT_SECONDS, 0.1),
            retries=_env_int("HASDATA_MCP_RETRIES", HASDATA_DEFAULT_RETRIES, 0, 5),
            backoff=_env_float("HASDATA_MCP_BACKOFF", HASDATA_DEFAULT_BACKOFF_SECONDS, 0.0),
            sleeper=sleeper,
        )

        def fetcher(query):
            return client.search_jobs(
                keyword=query["keyword"],
                location=query["location"],
                domain=query["domain"],
                sort=query["sort"],
            )

    profiles = cache["profiles"]
    ordered_queries = sorted(
        queries or [],
        key=lambda query: (
            (profiles.get(str(query.get("profile_id") or "").strip().casefold()) or {}).get(
                "hasdata_last_attempted_date"
            ) == current_date,
            (profiles.get(str(query.get("profile_id") or "").strip().casefold()) or {}).get(
                "hasdata_last_attempted_date"
            ) or "",
            str(query.get("id") or "query").strip().casefold(),
        ),
    )
    used_calls = 0
    for query in ordered_queries:
        query_id = str(query.get("id") or "query").strip()
        profile_id = str(query.get("profile_id") or "").strip().casefold()
        entry = profiles.get(profile_id)
        if not isinstance(entry, dict):
            summary["failed"] += 1
            summary["errors"][query_id] = "profile_id não existe no cache aprovado"
            continue
        profile_names = {
            company_key(name) for name in entry.get("company_names") or [] if company_key(name)
        }
        query_names = {
            company_key(name) for name in query.get("company_names") or [] if company_key(name)
        }
        if not query_names or not query_names.issubset(profile_names):
            summary["failed"] += 1
            summary["errors"][query_id] = "aliases MCP não pertencem ao perfil aprovado"
            continue
        # A successful result is checked once per day. Failed attempts may be
        # retried by a manually dispatched run, subject to the execution cap;
        # this avoids waiting a full day after a transient/provider mismatch.
        if entry.get("hasdata_checked_at") == current_date:
            summary["skipped"] += 1
            continue
        if used_calls >= limit:
            summary["capped"] += 1
            continue
        used_calls += 1
        summary["attempted"] += 1
        entry["hasdata_last_attempted_date"] = current_date
        try:
            result = fetcher(query)
            match = _mcp_match(result, query)
            entry["hasdata_rating"] = match["rating"]
            entry["hasdata_reference_url"] = match["reference_url"]
            entry["hasdata_checked_at"] = current_date
            summary["succeeded"] += 1
        except Exception as error:
            summary["failed"] += 1
            summary["errors"][query_id] = str(error)[:180]
    return cache, summary
