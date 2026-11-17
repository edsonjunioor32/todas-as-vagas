# -*- coding: utf-8 -*-
"""Cache de notas para as empresas do catálogo de vagas.

Extraído de ``glassdoor.py`` em 16/11/2026 sem mudança de comportamento;
``glassdoor`` reexporta estes nomes para manter a compatibilidade.
"""
from __future__ import annotations

import copy
import time
from datetime import (
    date,
    datetime,
)

from glassdoor_common import (
    _CATALOG_RESOLUTION_SOURCES,
    _CATALOG_RESOLUTION_STATUSES,
    _iso_date,
    _local_date,
    _rating,
    _review_count,
    _safe_error,
    _utc_iso,
    canonical_company_profile_url,
    company_key,
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_CATALOG_BATCH_SIZE,
    DEFAULT_CATALOG_BROWSERLESS_MAX_CALLS,
    DEFAULT_CATALOG_PROFILE_DELAY_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    GlassdoorConfigurationError,
    MAX_CATALOG_BATCH_SIZE,
    MAX_CATALOG_BROWSERLESS_MAX_CALLS,
    MAX_CATALOG_OFFSET,
    ProfileDataUnavailable,
)
from glassdoor_profiles import (
    _browserless_endpoint,
    _browserless_token,
    browserless_enabled,
    fetch_profile,
    resolve_catalog_profile_via_browserless,
)


def _catalog_cache_metrics(raw: object, company_name: str) -> dict:
    """Normalize one automatically discovered catalog company entry."""
    source = raw if isinstance(raw, dict) else {}
    status = str(source.get("status") or "").strip().casefold()
    if status not in {"matched", "unavailable"}:
        status = ""
    try:
        resolved_url = canonical_company_profile_url(source.get("resolved_url"))
    except (GlassdoorConfigurationError, TypeError, ValueError):
        resolved_url = None
    resolution_status = str(source.get("resolution_status") or "").strip().casefold()
    if resolution_status not in _CATALOG_RESOLUTION_STATUSES:
        resolution_status = ""
    resolution_source = str(source.get("resolution_source") or "").strip().casefold()
    if resolution_source not in _CATALOG_RESOLUTION_SOURCES:
        resolution_source = None
    resolution_reason = str(source.get("resolution_reason") or "").strip().casefold()
    if resolution_reason not in {
        "resolver_not_configured",
        "no_exact_profile",
        "multiple_exact_profiles",
        "resolver_error",
        "browserless_disabled",
        "browserless_misconfigured",
        "browserless_budget_exhausted",
        "browserless_search_error",
        "browserless_not_allowed",
    }:
        resolution_reason = None
    return {
        "company_names": [company_name],
        "url": None,
        "resolved_url": resolved_url,
        "rating": _rating(source.get("rating")),
        "review_count": _review_count(source.get("review_count")),
        "checked_at": _iso_date(source.get("checked_at")),
        "last_attempted_date": _iso_date(source.get("last_attempted_date")),
        "status": status,
        "resolution_status": resolution_status,
        "resolution_reason": resolution_reason,
        "resolution_checked_at": _iso_date(source.get("resolution_checked_at")),
        "resolution_source": resolution_source,
    }


def _snapshot_company_candidates(
    snapshot: dict | None,
) -> list[tuple[str, str, int, int]]:
    """Return company candidates with job counts and stable source positions."""
    if not isinstance(snapshot, dict):
        return []
    dictionaries = snapshot.get("dict") or {}
    raw_companies = dictionaries.get("company") if isinstance(dictionaries, dict) else []
    if not isinstance(raw_companies, list):
        return []

    jobs = snapshot.get("jobs") or {}
    raw_company_indexes = jobs.get("cmp") if isinstance(jobs, dict) else []
    job_counts: dict[str, int] = {}
    if isinstance(raw_company_indexes, list):
        for raw_index in raw_company_indexes:
            if isinstance(raw_index, bool):
                continue
            try:
                company_index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if not 0 <= company_index < len(raw_companies):
                continue
            key = company_key(raw_companies[company_index])
            if key:
                job_counts[key] = job_counts.get(key, 0) + 1

    candidates: dict[str, tuple[str, int]] = {}
    for position, raw_name in enumerate(raw_companies):
        company_name = str(raw_name or "").strip()
        key = company_key(company_name)
        if key and key not in candidates:
            candidates[key] = (company_name, position)

    return sorted(
        [
            (key, company_name, job_counts.get(key, 0), position)
            for key, (company_name, position) in candidates.items()
        ],
        key=lambda item: (item[0], item[3]),
    )


def _snapshot_company_names(snapshot: dict | None) -> list[tuple[str, str]]:
    """Return stable, deduplicated company names from a public snapshot."""
    return [
        (key, company_name)
        for key, company_name, _job_count, _position in _snapshot_company_candidates(snapshot)
    ]


def resolve_catalog_profile(company_name: str, resolver=None) -> dict:
    """Resolve one catalog name through an injected, network-free adapter.

    The production default is deliberately disabled because this repository
    does not contain a safe Glassdoor profile-search contract.  An adapter may
    return a list of candidate dictionaries with ``company_name`` (or ``name``)
    and ``url``.  Only one candidate with an exact normalized name and an
    approved company-profile URL is accepted.
    """
    if resolver is None:
        return {
            "status": "disabled",
            "reason": "resolver_not_configured",
            "source": "disabled",
        }
    try:
        raw_candidates = resolver(company_name)
    except Exception:
        return {"status": "error", "reason": "resolver_error", "source": "injected"}
    if isinstance(raw_candidates, dict):
        raw_candidates = raw_candidates.get("candidates")
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    valid: list[dict] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        returned_name = str(
            candidate.get("company_name") or candidate.get("companyName") or candidate.get("name") or ""
        ).strip()
        if company_key(returned_name) != company_key(company_name):
            continue
        try:
            url = canonical_company_profile_url(candidate.get("url"))
        except (GlassdoorConfigurationError, TypeError, ValueError):
            continue
        valid.append({"company_name": returned_name, "url": url})
    if len(valid) == 1:
        return {
            "status": "matched",
            "company_name": valid[0]["company_name"],
            "url": valid[0]["url"],
            "source": "injected",
        }
    if len(valid) > 1:
        return {
            "status": "ambiguous",
            "reason": "multiple_exact_profiles",
            "source": "injected",
        }
    return {
        "status": "missing",
        "reason": "no_exact_profile",
        "source": "injected",
    }


def update_catalog_cache(
    snapshot: dict,
    previous_cache: dict | None,
    *,
    now: date | datetime | None = None,
    batch_size: int = DEFAULT_CATALOG_BATCH_SIZE,
    catalog_offset: int = 0,
    fetcher=fetch_profile,
    resolver=None,
    sleeper=time.sleep,
    profile_delay: float = DEFAULT_CATALOG_PROFILE_DELAY_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF_SECONDS,
    catalog_browserless_max_calls: int = DEFAULT_CATALOG_BROWSERLESS_MAX_CALLS,
    force: bool = False,
) -> tuple[dict, dict]:
    """Refresh exact-match ratings in relevance-ordered resumable batches.

    Unrated companies are ordered by associated job count (descending), then
    by normalized name and source position for deterministic fallback. Existing
    ratings remain in the cache and are not queried again. A catalog company is
    resolved through the injected adapter or the explicit Browserless opt-in
    before any scraper call; without either, catalog enrichment stays disabled
    instead of inventing a URL. Browserless is enabled only within the explicit
    per-batch budget.
    """
    cache = copy.deepcopy(previous_cache or {})
    raw_catalog = cache.get("catalog_profiles")
    catalog_profiles = raw_catalog if isinstance(raw_catalog, dict) else {}
    cache["catalog_profiles"] = catalog_profiles

    canonical_keys = set()
    for profile in (cache.get("profiles") or {}).values():
        if not isinstance(profile, dict):
            continue
        canonical_keys.update(
            company_key(alias)
            for alias in (profile.get("company_names") or [])
            if company_key(alias)
        )

    discovered = [
        candidate
        for candidate in _snapshot_company_candidates(snapshot)
        if candidate[0] not in canonical_keys
    ]
    summary = {
        "discovered": len(discovered),
        "unrated": 0,
        "preserved": 0,
        "attempted": 0,
        "skipped": 0,
        "succeeded": 0,
        "failed": 0,
        "resolved": 0,
        "resolution_missing": 0,
        "resolution_ambiguous": 0,
        "resolution_disabled": 0,
        "resolution_errors": 0,
        "omkar_failed": 0,
        "browserless_succeeded": 0,
        "browserless_failed": 0,
        "queued": 0,
        "before_offset": 0,
        "offset": 0,
        "errors": {},
    }
    current_date = _local_date(now).isoformat()
    limit = min(max(1, int(batch_size)), MAX_CATALOG_BATCH_SIZE)
    offset = min(max(0, int(catalog_offset)), MAX_CATALOG_OFFSET)
    summary["offset"] = offset
    browserless_budget = min(
        max(0, int(catalog_browserless_max_calls)),
        MAX_CATALOG_BROWSERLESS_MAX_CALLS,
    )
    # Unit tests and callers that inject a fetcher may exercise the catalog
    # loop without a URL resolver.  The production fetcher never takes this
    # path: it remains disabled until an approved resolver is supplied.
    legacy_injected_fetcher = (
        resolver is None
        and fetcher is not fetch_profile
        and not browserless_enabled()
    )

    pending: list[tuple[str, str, int, int, dict]] = []
    for key, company_name, job_count, source_position in discovered:
        entry = _catalog_cache_metrics(catalog_profiles.get(key), company_name)
        catalog_profiles[key] = entry
        if _rating(entry.get("rating")) is not None:
            summary["preserved"] += 1
            continue
        pending.append((key, company_name, job_count, source_position, entry))

    pending.sort(
        key=lambda item: (
            -item[2],
            item[1].casefold(),
            item[0],
            item[3],
        )
    )
    summary["unrated"] = len(pending)
    selected = 0

    for position, (key, company_name, _job_count, _source_position, entry) in enumerate(pending):
        if position < offset:
            summary["before_offset"] += 1
            continue
        if not force and (
            entry.get("last_attempted_date") == current_date
            or entry.get("checked_at") == current_date
        ):
            summary["skipped"] += 1
            continue
        if selected >= limit:
            summary["queued"] += 1
            continue
        if selected and profile_delay > 0:
            sleeper(profile_delay)
        selected += 1
        summary["attempted"] += 1
        entry["last_attempted_date"] = current_date
        resolved_url = None
        cached_url = entry.get("resolved_url")
        if cached_url:
            try:
                resolved_url = canonical_company_profile_url(cached_url)
            except (GlassdoorConfigurationError, TypeError, ValueError):
                resolved_url = None
        if resolved_url:
            resolution = {
                "status": "matched",
                "url": resolved_url,
                "source": "cache",
            }
        elif legacy_injected_fetcher:
            resolution = {"status": "matched", "url": None, "source": "injected"}
        elif resolver is not None:
            resolution = resolve_catalog_profile(company_name, resolver)
        elif not browserless_enabled():
            resolution = {
                "status": "disabled",
                "reason": "browserless_disabled",
                "source": "disabled",
            }
        elif browserless_budget <= 0:
            resolution = {
                "status": "disabled",
                "reason": "browserless_budget_exhausted",
                "source": "disabled",
            }
        else:
            try:
                _browserless_endpoint()
                _browserless_token()
            except GlassdoorConfigurationError:
                resolution = {
                    "status": "disabled",
                    "reason": "browserless_misconfigured",
                    "source": "disabled",
                }
            else:
                browserless_budget = max(0, browserless_budget - 1)
                resolution = resolve_catalog_profile_via_browserless(
                    company_name,
                    timeout=timeout,
                )
        resolution_status = str(resolution.get("status") or "error").strip().casefold()
        entry["resolution_checked_at"] = current_date
        entry["resolution_status"] = resolution_status
        entry["resolution_reason"] = resolution.get("reason")
        entry["resolution_source"] = resolution.get("source")
        if resolution_status != "matched":
            entry["status"] = "unavailable"
            if resolution_status == "missing":
                summary["resolution_missing"] += 1
            elif resolution_status == "ambiguous":
                summary["resolution_ambiguous"] += 1
            elif resolution_status == "disabled":
                summary["resolution_disabled"] += 1
            else:
                summary["resolution_errors"] += 1
            summary["errors"][key] = _safe_error(
                resolution.get("reason") or resolution_status
            )
            continue
        resolved_url = resolution.get("url")
        if resolved_url:
            try:
                resolved_url = canonical_company_profile_url(resolved_url)
            except (GlassdoorConfigurationError, TypeError, ValueError) as error:
                entry["status"] = "unavailable"
                summary["resolution_errors"] += 1
                summary["errors"][key] = _safe_error(error)
                continue
            entry["resolved_url"] = resolved_url
        summary["resolved"] += 1
        profile = {
            "company_names": [company_name],
            "scraper_company": company_name,
        }
        if resolved_url:
            profile["url"] = resolved_url
            fallback_enabled = browserless_budget > 0 and browserless_enabled()
            if fallback_enabled:
                try:
                    _browserless_endpoint()
                    _browserless_token()
                except GlassdoorConfigurationError:
                    fallback_enabled = False
            profile["browserless_fallback"] = fallback_enabled
        attempt_source = ""
        failure_counted = False
        try:
            result = fetcher(
                profile,
                timeout=timeout,
                retries=retries,
                backoff=backoff,
                sleeper=sleeper,
            )
            if not isinstance(result, dict):
                raise ProfileDataUnavailable("coletor não retornou métricas")
            attempt_source = str(result.get("source") or "").strip().casefold()
            rating = _rating(result.get("rating"))
            count = _review_count(result.get("review_count"))
            if rating is None:
                if attempt_source == "browserless":
                    summary["browserless_failed"] += 1
                    browserless_budget = max(0, browserless_budget - 1)
                else:
                    summary["omkar_failed"] += 1
                failure_counted = True
                raise ProfileDataUnavailable("coletor não retornou média geral válida")
            entry["rating"] = rating
            if count is not None:
                entry["review_count"] = count
            entry["checked_at"] = current_date
            entry["status"] = "matched"
            if attempt_source == "browserless":
                summary["browserless_succeeded"] += 1
                browserless_budget = max(0, browserless_budget - 1)
            summary["succeeded"] += 1
        except Exception as error:  # one optional company never blocks the catalog
            entry["status"] = "unavailable"
            summary["failed"] += 1
            if not failure_counted:
                if getattr(error, "fallback_attempted", False):
                    summary["browserless_failed"] += 1
                    browserless_budget = max(0, browserless_budget - 1)
                elif attempt_source != "browserless":
                    summary["omkar_failed"] += 1
            summary["errors"][key] = _safe_error(error)
    cache["generated_at"] = _utc_iso(now)
    return cache, summary
