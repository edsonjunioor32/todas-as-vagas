# -*- coding: utf-8 -*-
"""Constantes, exceções e utilitários compartilhados do índice Glassdoor.

Extraído de ``glassdoor.py`` em 16/11/2026 sem mudança de comportamento;
``glassdoor`` reexporta estes nomes para manter a compatibilidade.
"""
from __future__ import annotations

import html
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import (
    date,
    datetime,
    time as datetime_time,
    timezone,
)
from pathlib import Path
from zoneinfo import ZoneInfo


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
DEFAULT_CATALOG_BATCH_SIZE = 100
DEFAULT_CATALOG_PROFILE_DELAY_SECONDS = 0.25
MAX_CATALOG_BATCH_SIZE = 1000
MAX_CATALOG_OFFSET = 100_000
DEFAULT_CATALOG_BROWSERLESS_MAX_CALLS = 0
MAX_CATALOG_BROWSERLESS_MAX_CALLS = 100
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PROFILES = 100
DEFAULT_MCP_QUERY_PATH = PROJECT_ROOT / "jobs-dashboard" / "data" / "glassdoor_mcp_queries.json"
DEFAULT_MCP_MAX_CALLS = 3
MAX_MCP_QUERIES = 50
# Three daily calls remain below the 100-call/month free allowance even in a
# 31-day month; the workflow default is more conservative and uses one.
MAX_MCP_CALLS = 3

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
# O perfil estruturado do Glassdoor usado pelo scraper de referência expõe a
# média da empresa como ``ratings.overallRating``. Aceitamos somente esse
# campo numérico, sem importar endpoints ou texto de avaliações.
_RATING_KEYS = {"ratingvalue", "rating", "overallrating"}
_COUNT_KEYS = {"reviewcount", "ratingcount"}
_ALLOWED_HOSTS = {"glassdoor.com", "glassdoor.com.br"}
_MCP_ALLOWED_DOMAINS = _ALLOWED_HOSTS | {"www.glassdoor.com", "www.glassdoor.com.br"}
_MCP_QUERY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_OMKAR_ENABLED_VALUES = {"1", "true", "yes", "on"}
_BROWSERLESS_ENABLED_VALUES = {"1", "true", "yes", "on"}
_BROWSERLESS_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_CATALOG_RESOLUTION_STATUSES = {"matched", "missing", "ambiguous", "disabled", "error"}
_CATALOG_RESOLUTION_SOURCES = {"cache", "injected", "browserless", "disabled"}
_COMPANY_PROFILE_PATH_RE = re.compile(
    r"^/(?:avalia(?:coes|ções)|reviews|vis(?:ao|ão)-geral|overview|"
    r"sal(?:arios|ários)|salaries|benefits|entrevistas|interviews)/"
    r"[^/]+-(?:e\d+|ei_ie\d+)(?:[.,_%\-][^/]+)?\.htm$",
    flags=re.IGNORECASE,
)


class GlassdoorError(RuntimeError):
    """Base exception for a non-fatal profile refresh failure."""


class GlassdoorConfigurationError(ValueError):
    """Raised when the explicit manifest cannot be safely interpreted."""


class GlassdoorFetchError(GlassdoorError):
    """Raised when robots or a public profile request cannot be used."""


class ProfileDataUnavailable(GlassdoorError):
    """Raised when a public page has no supported structured metrics."""


def _safe_error(error: object) -> str:
    """Return a short diagnostic without leaking tokens or request URLs."""
    message = re.sub(r"\s+", " ", str(error or "")).strip()
    message = re.sub(r"https?://\S+", "[url-redacted]", message, flags=re.IGNORECASE)
    message = re.sub(
        r"(?i)(token|api[_-]?key|authorization)=\S+",
        r"\1=[redacted]",
        message,
    )
    return message[:180]


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


def canonical_company_profile_url(value: object) -> str:
    """Validate a canonical Glassdoor company profile URL.

    This intentionally rejects job listings and generic search pages.  It only
    accepts a URL already supplied by a trusted resolver or manifest; it never
    derives a URL from a company name.
    """
    canonical = canonical_profile_url(value)
    path = urllib.parse.unquote(urllib.parse.urlsplit(canonical).path)
    if not _COMPANY_PROFILE_PATH_RE.fullmatch(path):
        raise GlassdoorConfigurationError(
            "Glassdoor URL não corresponde ao caminho de perfil empresarial aprovado"
        )
    return canonical


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
