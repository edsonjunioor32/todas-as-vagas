# -*- coding: utf-8 -*-
"""Conservative public Glassdoor profile refresh and snapshot enrichment.

The daily job is intentionally independent from vacancy collection.  It only
reads explicitly approved public profile URLs from the manifest, checks
robots.txt before each page, runs sequentially, and keeps the last successful
values when a request or parser fails.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import date, datetime, time as datetime_time, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from hasdata_glassdoor_mcp import (
    DEFAULT_BACKOFF_SECONDS as HASDATA_DEFAULT_BACKOFF_SECONDS,
    DEFAULT_ENDPOINT as HASDATA_DEFAULT_ENDPOINT,
    DEFAULT_RETRIES as HASDATA_DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS as HASDATA_DEFAULT_TIMEOUT_SECONDS,
    HasDataGlassdoorMcpClient,
)


SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "jobs-dashboard" / "data" / "glassdoor_profiles.json"
DEFAULT_CACHE_PATH = PROJECT_ROOT / "jobs-dashboard" / "data" / "glassdoor_cache.json"
DEFAULT_SNAPSHOT_PATH = PROJECT_ROOT / "docs" / "data" / "vagas.json"
LOCAL_TIMEZONE = ZoneInfo("America/Fortaleza")
DEFAULT_USER_AGENT = "TodasAsVagasGlassdoorIndexer/1.0 (+public-catalog)"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 2.0
DEFAULT_PROFILE_DELAY_SECONDS = 1.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PROFILES = 100
DEFAULT_MCP_QUERY_PATH = PROJECT_ROOT / "jobs-dashboard" / "data" / "glassdoor_mcp_queries.json"
DEFAULT_MCP_MAX_CALLS = 1
MAX_MCP_QUERIES = 50
# Three daily calls remain below the 100-call/month free allowance even in a
# 31-day month; the workflow default is more conservative and uses one.
MAX_MCP_CALLS = 3

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_RATING_KEYS = {"ratingvalue", "rating"}
_COUNT_KEYS = {"reviewcount", "ratingcount"}
_ALLOWED_HOSTS = {"glassdoor.com", "glassdoor.com.br"}
_MCP_ALLOWED_DOMAINS = _ALLOWED_HOSTS | {"www.glassdoor.com", "www.glassdoor.com.br"}
_MCP_QUERY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


class GlassdoorError(RuntimeError):
    """Base exception for a non-fatal profile refresh failure."""


class GlassdoorConfigurationError(ValueError):
    """Raised when the explicit manifest cannot be safely interpreted."""


class GlassdoorFetchError(GlassdoorError):
    """Raised when robots or a public profile request cannot be used."""


class ProfileDataUnavailable(GlassdoorError):
    """Raised when a public page has no supported structured metrics."""


def company_key(value: object) -> str:
    """Return a strict, accent-insensitive key for an approved alias."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _iso_date(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text[:10]
    if not _DATE_RE.fullmatch(candidate):
        return None
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate


def _rating(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = html.unescape(str(value)).strip().replace(",", ".")
    match = re.search(r"(?<!\d)(\d{1,2}(?:\.\d+)?)(?!\d)", text)
    if not match:
        return None
    try:
        parsed = float(match.group(1))
    except ValueError:
        return None
    if not 0 <= parsed <= 5:
        return None
    return round(parsed, 2)


def _review_count(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = html.unescape(str(value)).strip()
    # Approximate values such as 1.2K are deliberately rejected: gdc is an
    # exact count, not an estimate.
    if not re.fullmatch(r"\d[\d., ]*", text):
        return None
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    try:
        parsed = int(digits)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def canonical_profile_url(value: object) -> str:
    """Validate and canonicalize an explicitly supplied public URL.

    The function removes query strings/fragments and a trailing slash, but it
    never creates a host or path.  Only HTTPS Glassdoor hosts are accepted.
    """
    raw = str(value or "").strip()
    parsed = urllib.parse.urlsplit(raw)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or not host:
        raise GlassdoorConfigurationError("Glassdoor URL must use HTTPS")
    if parsed.username or parsed.password or parsed.port:
        raise GlassdoorConfigurationError("Glassdoor URL cannot contain credentials or a port")
    if not (
        host in _ALLOWED_HOSTS
        or any(host.endswith(f".{suffix}") for suffix in _ALLOWED_HOSTS)
    ):
        raise GlassdoorConfigurationError(f"host não aprovado para Glassdoor: {host}")
    path = re.sub(r"/{2,}", "/", parsed.path or "").rstrip("/")
    if not path or path == "/":
        raise GlassdoorConfigurationError("Glassdoor URL must point to a public profile path")
    return urllib.parse.urlunsplit(("https", host, path, "", ""))


def is_canonical_profile_url(value: object) -> bool:
    try:
        return str(value or "").strip() == canonical_profile_url(value)
    except (GlassdoorConfigurationError, TypeError, ValueError):
        return False


def canonical_reference_url(value: object) -> str:
    """Validate a HasData job reference without treating it as a profile URL."""
    raw = str(value or "").strip()
    parsed = urllib.parse.urlsplit(raw)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or not host:
        raise GlassdoorConfigurationError("URL de referência Glassdoor deve usar HTTPS")
    if parsed.username or parsed.password or parsed.port:
        raise GlassdoorConfigurationError("URL de referência Glassdoor não pode conter credenciais ou porta")
    if not (
        host in _ALLOWED_HOSTS
        or any(host.endswith(f".{suffix}") for suffix in _ALLOWED_HOSTS)
    ):
        raise GlassdoorConfigurationError(f"host não aprovado para referência Glassdoor: {host}")
    path = re.sub(r"/{2,}", "/", parsed.path or "").rstrip("/")
    if not path:
        raise GlassdoorConfigurationError("URL de referência Glassdoor sem caminho")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    safe_query = urllib.parse.urlencode({"jl": query["jl"][0]}) if query.get("jl") else ""
    return urllib.parse.urlunsplit(("https", host, path, safe_query, ""))


def is_canonical_reference_url(value: object) -> bool:
    try:
        return str(value or "").strip() == canonical_reference_url(value)
    except (GlassdoorConfigurationError, TypeError, ValueError):
        return False


def hasdata_mcp_enabled() -> bool:
    """Return whether the optional HasData fallback was explicitly enabled."""
    return str(os.environ.get("HASDATA_MCP_ENABLED", "false")).strip().casefold() in {
        "1", "true", "yes", "on"
    }


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


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
        profiles[profile_id] = {
            "id": profile_id,
            "company_names": clean_names,
            "company_keys": clean_keys,
            "url": url,
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
    generated_at = (
        str(raw_cache.get("generated_at") or "").strip()
        if isinstance(raw_cache, dict)
        else ""
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "profiles": profiles,
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
    """Index cache entries by exact approved company aliases."""
    if not isinstance(cache, dict):
        return {}
    raw_profiles = cache.get("profiles") or {}
    if not isinstance(raw_profiles, dict):
        return {}
    indexed: dict[str, dict] = {}
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
        entry = {
            "glassdoor_rating": _rating(raw.get("rating")),
            "glassdoor_review_count": _review_count(raw.get("review_count")),
            "glassdoor_url": url,
            "glassdoor_checked_at": _iso_date(raw.get("checked_at")),
            "glassdoor_fallback_rating": _rating(raw.get("hasdata_rating")),
            "glassdoor_fallback_url": fallback_url,
            "glassdoor_fallback_checked_at": _iso_date(raw.get("hasdata_checked_at")),
        }
        for alias in aliases:
            key = company_key(alias)
            if key and key not in indexed:
                indexed[key] = entry
    return indexed


class _PublicProfileParser(HTMLParser):
    """Read only structured public metadata; visible prose is ignored."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rating_values: list[object] = []
        self.count_values: list[object] = []
        self._jsonld_depth = 0
        self._jsonld_parts: list[str] = []
        self.jsonld_payloads: list[object] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(key).casefold(): str(value or "") for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = self._attrs(attrs)
        if tag == "meta":
            key = (values.get("itemprop") or values.get("name") or "").casefold()
            content = values.get("content", "")
            normalized = re.sub(r"[^a-z]", "", key)
            if normalized in _RATING_KEYS:
                self.rating_values.append(content)
            elif normalized in _COUNT_KEYS:
                self.count_values.append(content)
            return
        if tag != "script":
            return
        script_type = values.get("type", "").casefold()
        if "ld+json" in script_type:
            self._jsonld_depth = 1
            self._jsonld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "script" or not self._jsonld_depth:
            return
        raw = "".join(self._jsonld_parts).strip()
        if raw:
            try:
                self.jsonld_payloads.append(json.loads(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        self._jsonld_depth = 0
        self._jsonld_parts = []

    def handle_data(self, data: str) -> None:
        if self._jsonld_depth:
            self._jsonld_parts.append(data)


def _structured_values(value: object, ratings: list[object], counts: list[object]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z]", "", str(key).casefold())
            if normalized in _RATING_KEYS:
                ratings.append(child)
            elif normalized in _COUNT_KEYS:
                counts.append(child)
            _structured_values(child, ratings, counts)
    elif isinstance(value, list):
        for child in value:
            _structured_values(child, ratings, counts)


def parse_public_profile(payload: bytes | str) -> dict:
    """Extract exact rating/count values from JSON-LD or itemprop metadata."""
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
    parser = _PublicProfileParser()
    try:
        parser.feed(text)
        parser.close()
    except (TypeError, ValueError):
        pass
    ratings: list[object] = []
    counts: list[object] = []
    for item in parser.jsonld_payloads:
        _structured_values(item, ratings, counts)
    ratings.extend(parser.rating_values)
    counts.extend(parser.count_values)
    parsed_rating = next((value for value in (_rating(item) for item in ratings) if value is not None), None)
    parsed_count = next((value for value in (_review_count(item) for item in counts) if value is not None), None)
    if parsed_rating is None and parsed_count is None:
        raise ProfileDataUnavailable("página pública sem rating/review count estruturado suportado")
    return {"rating": parsed_rating, "review_count": parsed_count}


def _read_url(
    url: str,
    *,
    timeout: float,
    opener=urllib.request.urlopen,
    accept: str,
) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": accept},
    )
    with opener(request, timeout=timeout) as response:
        content = response.read(MAX_RESPONSE_BYTES + 1)
    if len(content) > MAX_RESPONSE_BYTES:
        raise GlassdoorFetchError(f"resposta excedeu {MAX_RESPONSE_BYTES} bytes")
    return content


def _robots_allowed(
    target_url: str,
    *,
    timeout: float,
    opener=urllib.request.urlopen,
) -> bool:
    parsed = urllib.parse.urlsplit(target_url)
    robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    try:
        body = _read_url(
            robots_url,
            timeout=timeout,
            opener=opener,
            accept="text/plain,*/*;q=0.1",
        )
    except urllib.error.HTTPError as error:
        # A missing robots.txt means there are no published robots rules.  A
        # refusal or a transient failure is fail-closed for this optional step.
        if error.code == 404:
            return True
        return False
    except Exception:
        return False
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(body.decode("utf-8", "replace").splitlines())
    return parser.can_fetch(DEFAULT_USER_AGENT, target_url)


def fetch_profile(
    profile: dict,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF_SECONDS,
    sleeper=time.sleep,
    opener=urllib.request.urlopen,
) -> dict:
    """Read one approved public profile, respecting robots.txt and backoff."""
    url = profile["url"]
    if not _robots_allowed(url, timeout=timeout, opener=opener):
        raise GlassdoorFetchError("robots.txt não autorizou ou não respondeu com segurança")
    attempts = max(1, int(retries))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            body = _read_url(
                url,
                timeout=timeout,
                opener=opener,
                accept="text/html,application/xhtml+xml",
            )
            return parse_public_profile(body)
        except urllib.error.HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable:
                raise GlassdoorFetchError(f"Glassdoor respondeu HTTP {error.code}") from error
        except (GlassdoorError, OSError, TimeoutError, urllib.error.URLError) as error:
            last_error = error
        if attempt < attempts:
            sleeper(max(0.0, float(backoff)) * attempt)
    raise GlassdoorFetchError(f"consulta Glassdoor falhou após {attempts} tentativas: {last_error}") from last_error


def _local_date(value: date | datetime | None = None) -> date:
    if value is None:
        return datetime.now(LOCAL_TIMEZONE).date()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=LOCAL_TIMEZONE).date()
        return value.astimezone(LOCAL_TIMEZONE).date()
    return value


def _utc_iso(value: date | datetime | None = None) -> str:
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, date):
        current = datetime.combine(value, datetime_time.min, tzinfo=timezone.utc)
    else:
        current = datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


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
        if entry.get("hasdata_last_attempted_date") == current_date or entry.get("hasdata_checked_at") == current_date:
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
) -> tuple[dict, dict]:
    """Refresh each profile at most once for the current local date."""
    current_date = _local_date(now).isoformat()
    cache = align_cache(manifest, previous_cache or {})
    profiles = cache["profiles"]
    summary = {"attempted": 0, "skipped": 0, "succeeded": 0, "failed": 0, "errors": {}}
    for position, (profile_id, profile) in enumerate((manifest.get("profiles") or {}).items()):
        entry = profiles[profile_id]
        if entry.get("last_attempted_date") == current_date or entry.get("checked_at") == current_date:
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
    )
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
    snapshot = Path(snapshot_path)
    if snapshot.exists():
        snapshot_changed, matched = update_snapshot_file(snapshot, cache)
    result = {
        **summary,
        "hasdata_mcp": mcp_summary,
        "profiles": len(manifest.get("profiles") or {}),
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
    )
    print(
        "Glassdoor: "
        f"{result['profiles']} perfis aprovados · "
        f"{result['succeeded']} atualizados · "
        f"{result['failed']} falhas · "
        f"{result['skipped']} já verificados hoje · "
        f"{result['matched_jobs']} vagas associadas"
    )
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
