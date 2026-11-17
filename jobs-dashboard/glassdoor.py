# -*- coding: utf-8 -*-
"""Conservative public Glassdoor profile refresh and snapshot enrichment.

The daily job is intentionally independent from vacancy collection.  It only
reads explicitly approved public profile URLs from the manifest, checks
robots.txt before each page, runs sequentially, and keeps the last successful
values when a request or parser fails.

Organização: ``glassdoor_common`` (constantes, exceções e utilitários),
``glassdoor_profiles`` (busca e leitura de perfis), ``glassdoor_hasdata``
(complemento pelo MCP da HasData) e ``glassdoor_catalog`` (cache das empresas
do catálogo). Este módulo mantém o fluxo diário e reexporta todos esses nomes.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import (
    date,
    datetime,
)
from pathlib import Path

from glassdoor_common import (  # noqa: F401 - API pública de glassdoor
    _ALLOWED_HOSTS,
    _BROWSERLESS_ENABLED_VALUES,
    _BROWSERLESS_LOCAL_HOSTS,
    _CATALOG_RESOLUTION_SOURCES,
    _CATALOG_RESOLUTION_STATUSES,
    _COMPANY_PROFILE_PATH_RE,
    _COUNT_KEYS,
    _DATE_RE,
    _env_float,
    _env_int,
    _iso_date,
    _local_date,
    _MCP_ALLOWED_DOMAINS,
    _MCP_QUERY_ID_RE,
    _OMKAR_ENABLED_VALUES,
    _PROFILE_ID_RE,
    _rating,
    _RATING_KEYS,
    _review_count,
    _safe_error,
    _utc_iso,
    canonical_company_profile_url,
    canonical_profile_url,
    canonical_reference_url,
    company_key,
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_CACHE_PATH,
    DEFAULT_CATALOG_BATCH_SIZE,
    DEFAULT_CATALOG_BROWSERLESS_MAX_CALLS,
    DEFAULT_CATALOG_PROFILE_DELAY_SECONDS,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_MCP_MAX_CALLS,
    DEFAULT_MCP_QUERY_PATH,
    DEFAULT_PROFILE_DELAY_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_SNAPSHOT_PATH,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    GlassdoorConfigurationError,
    GlassdoorError,
    GlassdoorFetchError,
    hasdata_mcp_enabled,
    is_canonical_profile_url,
    is_canonical_reference_url,
    LOCAL_TIMEZONE,
    MAX_CATALOG_BATCH_SIZE,
    MAX_CATALOG_BROWSERLESS_MAX_CALLS,
    MAX_CATALOG_OFFSET,
    MAX_MCP_CALLS,
    MAX_MCP_QUERIES,
    MAX_PROFILES,
    MAX_RESPONSE_BYTES,
    ProfileDataUnavailable,
    PROJECT_ROOT,
    SCHEMA_VERSION,
)
from glassdoor_profiles import (  # noqa: F401 - API pública de glassdoor
    _browserless_endpoint,
    _browserless_token,
    _fetch_direct_profile,
    _omkar_endpoint,
    _post_json,
    _PublicProfileParser,
    _read_url,
    _robots_allowed,
    _structured_values,
    _VisibleTextParser,
    browserless_enabled,
    fetch_browserless_profile,
    fetch_omkar_profile,
    fetch_profile,
    parse_browserless_profile,
    parse_omkar_company_ratings,
    parse_public_profile,
    resolve_catalog_profile_via_browserless,
)
from glassdoor_hasdata import (  # noqa: F401 - API pública de glassdoor
    _mcp_company_name,
    _mcp_job_rating,
    _mcp_job_url,
    _mcp_jobs,
    _mcp_match,
    load_hasdata_queries,
    update_hasdata_fallback,
)
from glassdoor_catalog import (  # noqa: F401 - API pública de glassdoor
    _catalog_cache_metrics,
    _snapshot_company_candidates,
    _snapshot_company_names,
    resolve_catalog_profile,
    update_catalog_cache,
)


def load_manifest(path: str | os.PathLike[str] = DEFAULT_MANIFEST_PATH) -> dict:
    """Load the active, explicitly approved profile manifest."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise GlassdoorConfigurationError(f"manifesto Glassdoor inválido: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise GlassdoorConfigurationError("manifesto Glassdoor com schema_version inválido")
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list):
        raise GlassdoorConfigurationError("manifesto Glassdoor precisa de profiles como lista")
    if len(raw_profiles) > MAX_PROFILES:
        raise GlassdoorConfigurationError(f"manifesto Glassdoor excede {MAX_PROFILES} perfis")

    profiles: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    urls: dict[str, str] = {}
    for index, raw in enumerate(raw_profiles):
        if not isinstance(raw, dict):
            raise GlassdoorConfigurationError(f"perfil Glassdoor {index} não é um objeto")
        # A profile must be explicitly approved.  Disabled/unapproved entries
        # remain harmless and are not queried or exported.
        if raw.get("approved") is not True or raw.get("enabled", True) is False:
            continue
        profile_id = str(raw.get("id") or "").strip().casefold()
        if not _PROFILE_ID_RE.fullmatch(profile_id):
            raise GlassdoorConfigurationError(f"id de perfil Glassdoor inválido: {profile_id!r}")
        if profile_id in profiles:
            raise GlassdoorConfigurationError(f"id de perfil Glassdoor duplicado: {profile_id}")
        names = raw.get("company_names")
        if not isinstance(names, list) or not names:
            raise GlassdoorConfigurationError(f"perfil {profile_id} sem company_names")
        clean_names: list[str] = []
        clean_keys: list[str] = []
        for name in names:
            clean_name = str(name or "").strip()
            key = company_key(clean_name)
            if not clean_name or not key:
                raise GlassdoorConfigurationError(f"perfil {profile_id} contém alias vazio")
            if key in aliases:
                raise GlassdoorConfigurationError(
                    f"alias Glassdoor duplicado: {clean_name!r} ({aliases[key]})"
                )
            aliases[key] = profile_id
            clean_names.append(clean_name)
            clean_keys.append(key)
        url = canonical_profile_url(raw.get("url"))
        if url in urls:
            raise GlassdoorConfigurationError(
                f"URL Glassdoor duplicada entre {profile_id} e {urls[url]}"
            )
        urls[url] = profile_id
        scraper_company = str(raw.get("scraper_company") or clean_names[0]).strip()
        if company_key(scraper_company) not in set(clean_keys):
            raise GlassdoorConfigurationError(
                f"scraper_company do perfil {profile_id} não corresponde a um alias aprovado"
            )
        profiles[profile_id] = {
            "id": profile_id,
            "company_names": clean_names,
            "company_keys": clean_keys,
            "scraper_company": scraper_company,
            "url": url,
            "browserless_fallback": raw.get("browserless_fallback") is True,
        }
    return {"schema_version": SCHEMA_VERSION, "profiles": profiles}


def _raw_cache(path: str | os.PathLike[str]) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cache_metrics(raw: object, profile: dict, *, reset: bool = False) -> dict:
    source = raw if isinstance(raw, dict) and not reset else {}
    try:
        reference_url = canonical_reference_url(source.get("hasdata_reference_url"))
    except (GlassdoorConfigurationError, TypeError, ValueError):
        reference_url = None
    rating = _rating(source.get("rating"))
    count = _review_count(source.get("review_count"))
    checked_at = _iso_date(source.get("checked_at"))
    attempted = _iso_date(source.get("last_attempted_date"))
    return {
        "id": profile["id"],
        "company_names": list(profile["company_names"]),
        "url": profile["url"],
        "rating": rating,
        "review_count": count,
        "checked_at": checked_at,
        "last_attempted_date": attempted,
        "hasdata_rating": _rating(source.get("hasdata_rating")),
        "hasdata_reference_url": reference_url,
        "hasdata_checked_at": _iso_date(source.get("hasdata_checked_at")),
        "hasdata_last_attempted_date": _iso_date(source.get("hasdata_last_attempted_date")),
        "source": (
            str(source.get("source") or "").strip().casefold()
            if str(source.get("source") or "").strip().casefold()
            in {"omkar", "direct", "browserless"}
            else None
        ),
    }


def align_cache(manifest: dict, raw_cache: dict | None) -> dict:
    """Keep cache entries only for the currently approved manifest profiles."""
    raw_profiles = raw_cache.get("profiles") if isinstance(raw_cache, dict) else {}
    if not isinstance(raw_profiles, dict):
        raw_profiles = {}
    profiles: dict[str, dict] = {}
    for profile_id, profile in (manifest.get("profiles") or {}).items():
        previous = raw_profiles.get(profile_id)
        reset = False
        if isinstance(previous, dict):
            try:
                previous_url = canonical_profile_url(previous.get("url"))
            except GlassdoorConfigurationError:
                previous_url = ""
            previous_names = {
                company_key(value) for value in (previous.get("company_names") or [])
            }
            reset = previous_url != profile["url"] or previous_names != set(profile["company_keys"])
        profiles[profile_id] = _cache_metrics(previous, profile, reset=reset)
    catalog_profiles: dict[str, dict] = {}
    raw_catalog = raw_cache.get("catalog_profiles") if isinstance(raw_cache, dict) else {}
    if isinstance(raw_catalog, dict):
        for raw_key, raw_entry in raw_catalog.items():
            if not isinstance(raw_entry, dict):
                continue
            raw_names = raw_entry.get("company_names") or []
            company_name = str(raw_names[0] if isinstance(raw_names, list) and raw_names else "").strip()
            key = company_key(company_name)
            if not key or key != str(raw_key).strip():
                continue
            catalog_profiles[key] = _catalog_cache_metrics(raw_entry, company_name)
    generated_at = (
        str(raw_cache.get("generated_at") or "").strip()
        if isinstance(raw_cache, dict)
        else ""
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "profiles": profiles,
        "catalog_profiles": catalog_profiles,
    }


def load_cache(
    cache_path: str | os.PathLike[str] = DEFAULT_CACHE_PATH,
    manifest_path: str | os.PathLike[str] = DEFAULT_MANIFEST_PATH,
) -> dict:
    """Load a cache filtered through the approved manifest.

    Missing/corrupt cache data becomes an empty aligned cache.  Callers can
    therefore continue the vacancy publication without making Glassdoor a
    dependency of the main collection.
    """
    manifest = load_manifest(manifest_path)
    return align_cache(manifest, _raw_cache(cache_path))


def build_snapshot_index(cache: dict | None) -> dict[str, dict]:
    """Index canonical and exact-match catalog entries by company alias."""
    if not isinstance(cache, dict):
        return {}
    indexed: dict[str, dict] = {}
    for section in ("profiles", "catalog_profiles"):
        raw_profiles = cache.get(section) or {}
        if not isinstance(raw_profiles, dict):
            continue
        for raw in raw_profiles.values():
            if not isinstance(raw, dict):
                continue
            aliases = raw.get("company_names") or []
            if not isinstance(aliases, list):
                continue
            try:
                url = canonical_profile_url(raw.get("url")) if raw.get("url") else None
            except GlassdoorConfigurationError:
                url = None
            try:
                fallback_url = (
                    canonical_reference_url(raw.get("hasdata_reference_url"))
                    if raw.get("hasdata_reference_url") else None
                )
            except GlassdoorConfigurationError:
                fallback_url = None
            primary_rating = _rating(raw.get("rating"))
            entry = {
                "glassdoor_rating": primary_rating,
                "glassdoor_review_count": _review_count(raw.get("review_count")),
                "glassdoor_url": url,
                "glassdoor_checked_at": _iso_date(raw.get("checked_at")),
                # A HasData job-listing rating is only a fallback when the
                # official company profile has no rating.  Never show two
                # different numbers for the same employer.
                "glassdoor_fallback_rating": None if primary_rating is not None else _rating(raw.get("hasdata_rating")),
                "glassdoor_fallback_url": None if primary_rating is not None else fallback_url,
                "glassdoor_fallback_checked_at": (
                    None if primary_rating is not None else _iso_date(raw.get("hasdata_checked_at"))
                ),
            }
            for alias in aliases:
                key = company_key(alias)
                if key and key not in indexed:
                    indexed[key] = entry
    return indexed


def update_cache(
    manifest: dict,
    previous_cache: dict | None,
    *,
    now: date | datetime | None = None,
    fetcher=fetch_profile,
    sleeper=time.sleep,
    profile_delay: float = DEFAULT_PROFILE_DELAY_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF_SECONDS,
    force: bool = False,
) -> tuple[dict, dict]:
    """Refresh profiles once per day, unless an explicit recovery run forces it."""
    current_date = _local_date(now).isoformat()
    cache = align_cache(manifest, previous_cache or {})
    profiles = cache["profiles"]
    summary = {"attempted": 0, "skipped": 0, "succeeded": 0, "failed": 0, "errors": {}}
    for position, (profile_id, profile) in enumerate((manifest.get("profiles") or {}).items()):
        entry = profiles[profile_id]
        if not force and (
            entry.get("last_attempted_date") == current_date
            or entry.get("checked_at") == current_date
        ):
            summary["skipped"] += 1
            continue
        if position and profile_delay > 0:
            sleeper(profile_delay)
        summary["attempted"] += 1
        # Persist the attempt marker even when the request later times out; a
        # repeated workflow invocation on the same day must not retry it.
        entry["last_attempted_date"] = current_date
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
            rating = _rating(result.get("rating"))
            count = _review_count(result.get("review_count"))
            if rating is None and count is None:
                raise ProfileDataUnavailable("coletor não retornou métricas válidas")
            # A partial successful parse must not erase another valid field.
            if rating is not None:
                entry["rating"] = rating
            if count is not None:
                entry["review_count"] = count
            source = str(result.get("source") or "").strip().casefold()
            if source in {"omkar", "direct", "browserless"}:
                entry["source"] = source
            entry["checked_at"] = current_date
            summary["succeeded"] += 1
        except Exception as error:  # one optional profile never blocks others
            summary["failed"] += 1
            summary["errors"][profile_id] = str(error)[:180]
    cache["generated_at"] = _utc_iso(now)
    return cache, summary


def write_cache(path: str | os.PathLike[str], cache: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": str(cache.get("generated_at") or _utc_iso()),
        "profiles": cache.get("profiles") or {},
        "catalog_profiles": cache.get("catalog_profiles") or {},
    }
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def enrich_snapshot(payload: dict, cache: dict | None, *, generated_at: str | None = None) -> tuple[dict, int]:
    """Add aligned optional Glassdoor arrays without changing vacancy rows."""
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), dict):
        raise ValueError("snapshot inválido: jobs ausente")
    count = int(payload.get("count") or 0)
    jobs = payload["jobs"]
    dictionaries = payload.get("dict") or {}
    companies = dictionaries.get("company") or []
    company_codes = jobs.get("cmp") or []
    if len(company_codes) != count:
        raise ValueError("snapshot inválido: coluna cmp desalinhada")
    index = build_snapshot_index(cache)
    arrays = {
        "gdr": [],
        "gdc": [],
        "gdu": [],
        "gdt": [],
        "gfr": [],
        "gfu": [],
        "gft": [],
    }
    matched = 0
    for code in company_codes:
        try:
            company = companies[int(code)]
        except (IndexError, TypeError, ValueError):
            company = ""
        value = index.get(company_key(company))
        if value:
            matched += 1
        arrays["gdr"].append(value.get("glassdoor_rating") if value else None)
        arrays["gdc"].append(value.get("glassdoor_review_count") if value else None)
        arrays["gdu"].append(value.get("glassdoor_url") if value else None)
        arrays["gdt"].append(value.get("glassdoor_checked_at") if value else None)
        arrays["gfr"].append(value.get("glassdoor_fallback_rating") if value else None)
        arrays["gfu"].append(value.get("glassdoor_fallback_url") if value else None)
        arrays["gft"].append(value.get("glassdoor_fallback_checked_at") if value else None)
    changed = any(jobs.get(name) != values for name, values in arrays.items())
    updated = dict(payload)
    updated_jobs = dict(jobs)
    updated_jobs.update(arrays)
    updated["jobs"] = updated_jobs
    if changed and generated_at:
        updated["generated_at"] = generated_at
    return updated, matched


def update_snapshot_file(
    path: str | os.PathLike[str],
    cache: dict,
    *,
    now: date | datetime | None = None,
) -> tuple[bool, int]:
    output = Path(path)
    payload = json.loads(output.read_text(encoding="utf-8"))
    updated, matched = enrich_snapshot(payload, cache, generated_at=_utc_iso(now))
    changed = updated != payload
    if not changed:
        return False, matched
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(updated, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return True, matched


def run_daily(
    manifest_path: str | os.PathLike[str] = DEFAULT_MANIFEST_PATH,
    cache_path: str | os.PathLike[str] = DEFAULT_CACHE_PATH,
    snapshot_path: str | os.PathLike[str] = DEFAULT_SNAPSHOT_PATH,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF_SECONDS,
    profile_delay: float = DEFAULT_PROFILE_DELAY_SECONDS,
    catalog_batch_size: int = DEFAULT_CATALOG_BATCH_SIZE,
    catalog_offset: int = 0,
    catalog_profile_delay: float = DEFAULT_CATALOG_PROFILE_DELAY_SECONDS,
    catalog_browserless_max_calls: int = DEFAULT_CATALOG_BROWSERLESS_MAX_CALLS,
    force: bool = False,
) -> dict:
    manifest = load_manifest(manifest_path)
    previous = load_cache(cache_path, manifest_path)
    cache, summary = update_cache(
        manifest,
        previous,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
        profile_delay=profile_delay,
        force=force,
    )
    catalog_summary = {
        "enabled": False,
        "discovered": 0,
        "attempted": 0,
        "skipped": 0,
        "succeeded": 0,
        "failed": 0,
        "queued": 0,
        "resolved": 0,
        "resolution_missing": 0,
        "resolution_ambiguous": 0,
        "resolution_disabled": 0,
        "resolution_errors": 0,
        "omkar_failed": 0,
        "browserless_succeeded": 0,
        "browserless_failed": 0,
        "errors": {},
    }
    snapshot = Path(snapshot_path)
    snapshot_payload = None
    if snapshot.exists():
        try:
            snapshot_payload = json.loads(snapshot.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            catalog_summary["errors"]["snapshot"] = str(error)[:180]
    if (
        snapshot_payload is not None
        and str(os.environ.get("OMKAR_GLASSDOOR_ENABLED") or "").strip().casefold()
        in _OMKAR_ENABLED_VALUES
    ):
        cache, catalog_summary = update_catalog_cache(
            snapshot_payload,
            cache,
            now=None,
            batch_size=catalog_batch_size,
            catalog_offset=catalog_offset,
            timeout=timeout,
            retries=retries,
            backoff=backoff,
            profile_delay=catalog_profile_delay,
            catalog_browserless_max_calls=catalog_browserless_max_calls,
            force=force,
        )
        catalog_summary["enabled"] = True
    try:
        mcp_queries_path = Path(
            os.environ.get("HASDATA_MCP_QUERIES_PATH") or DEFAULT_MCP_QUERY_PATH
        )
        mcp_queries = load_hasdata_queries(mcp_queries_path)
        cache, mcp_summary = update_hasdata_fallback(cache, mcp_queries)
    except Exception as error:
        # The optional provider is isolated from profile refresh and vacancy ETL.
        mcp_summary = {
            "enabled": hasdata_mcp_enabled(),
            "configured": bool(os.environ.get("HASDATA_API_KEY")),
            "attempted": 0,
            "skipped": 0,
            "succeeded": 0,
            "failed": 1,
            "capped": 0,
            "errors": {"configuration": str(error)[:180]},
        }
    write_cache(cache_path, cache)
    snapshot_changed = False
    matched = 0
    if snapshot.exists():
        snapshot_changed, matched = update_snapshot_file(snapshot, cache)
    result = {
        **summary,
        "catalog": catalog_summary,
        "hasdata_mcp": mcp_summary,
        "profiles": len(manifest.get("profiles") or {}),
        "catalog_profiles": len(cache.get("catalog_profiles") or {}),
        "snapshot_changed": snapshot_changed,
        "matched_jobs": matched,
    }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atualiza o cache público opcional do Glassdoor")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_PATH))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT_PATH))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--backoff", type=float, default=DEFAULT_BACKOFF_SECONDS)
    parser.add_argument("--profile-delay", type=float, default=DEFAULT_PROFILE_DELAY_SECONDS)
    parser.add_argument(
        "--catalog-batch-size",
        type=int,
        default=DEFAULT_CATALOG_BATCH_SIZE,
        help="quantidade máxima de empresas novas consultadas por execução",
    )
    parser.add_argument(
        "--catalog-offset",
        type=int,
        default=0,
        help="posição inicial do lote no catálogo ordenado; use com --force",
    )
    parser.add_argument(
        "--catalog-profile-delay",
        type=float,
        default=DEFAULT_CATALOG_PROFILE_DELAY_SECONDS,
        help="intervalo entre consultas de empresas descobertas",
    )
    parser.add_argument(
        "--catalog-browserless-max-calls",
        type=int,
        default=DEFAULT_CATALOG_BROWSERLESS_MAX_CALLS,
        help="máximo de fallbacks Browserless no lote; 0 mantém desativado",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="refaz a consulta dos perfis mesmo quando já houve tentativa hoje",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_daily(
        args.manifest,
        args.cache,
        args.snapshot,
        timeout=max(1.0, args.timeout),
        retries=max(1, args.retries),
        backoff=max(0.0, args.backoff),
        profile_delay=max(0.0, args.profile_delay),
        catalog_batch_size=max(1, args.catalog_batch_size),
        catalog_offset=max(0, min(MAX_CATALOG_OFFSET, args.catalog_offset)),
        catalog_profile_delay=max(0.0, args.catalog_profile_delay),
        catalog_browserless_max_calls=max(
            0,
            min(MAX_CATALOG_BROWSERLESS_MAX_CALLS, args.catalog_browserless_max_calls),
        ),
        force=args.force,
    )
    print(
        "Glassdoor: "
        f"{result['profiles']} perfis aprovados · "
        f"{result['succeeded']} atualizados · "
        f"{result['failed']} falhas · "
        f"{result['skipped']} já verificados hoje · "
        f"{result['matched_jobs']} vagas associadas"
    )
    catalog = result.get("catalog") or {}
    print(
        "Glassdoor catálogo: "
        f"{'ativo' if catalog.get('enabled') else 'desativado'} · "
        f"{catalog.get('discovered', 0)} empresas descobertas · "
        f"{catalog.get('succeeded', 0)} atualizadas · "
        f"{catalog.get('failed', 0)} falhas · "
        f"Omkar {catalog.get('omkar_failed', 0)} falhas · "
        f"sem perfil {catalog.get('resolution_missing', 0)} · "
        f"ambíguas {catalog.get('resolution_ambiguous', 0)} · "
        f"Browserless ok {catalog.get('browserless_succeeded', 0)} · "
        f"Browserless falhou {catalog.get('browserless_failed', 0)} · "
        f"{catalog.get('queued', 0)} na fila · "
        f"offset {catalog.get('offset', 0)}"
    )
    for company_id, error in sorted((catalog.get("errors") or {}).items()):
        print(f"  [Glassdoor catálogo:{company_id}] aviso: {_safe_error(error)}")
    for profile_id, error in sorted(result["errors"].items()):
        print(f"  [{profile_id}] aviso: {error}")
    mcp = result.get("hasdata_mcp") or {}
    print(
        "HasData MCP: "
        f"{'ativo' if mcp.get('enabled') else 'desativado'} · "
        f"{mcp.get('attempted', 0)} tentativas · "
        f"{mcp.get('succeeded', 0)} notas capturadas · "
        f"{mcp.get('failed', 0)} falhas · "
        f"{mcp.get('capped', 0)} limitadas"
    )
    for query_id, error in sorted((mcp.get("errors") or {}).items()):
        print(f"  [HasData:{query_id}] aviso: {error}")
    if result["snapshot_changed"]:
        print(f"  snapshot Glassdoor atualizado: {DEFAULT_SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
