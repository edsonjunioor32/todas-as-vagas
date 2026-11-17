# -*- coding: utf-8 -*-
"""Busca e leitura de perfis públicos do Glassdoor (página, Omkar e Browserless).

Extraído de ``glassdoor.py`` em 16/11/2026 sem mudança de comportamento;
``glassdoor`` reexporta estes nomes para manter a compatibilidade.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

from glassdoor_common import (
    _BROWSERLESS_ENABLED_VALUES,
    _BROWSERLESS_LOCAL_HOSTS,
    _COUNT_KEYS,
    _env_int,
    _OMKAR_ENABLED_VALUES,
    _rating,
    _RATING_KEYS,
    _review_count,
    canonical_company_profile_url,
    company_key,
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    GlassdoorConfigurationError,
    GlassdoorError,
    GlassdoorFetchError,
    MAX_RESPONSE_BYTES,
    ProfileDataUnavailable,
)


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


def parse_omkar_company_ratings(payload: bytes | str | dict, profile: dict) -> dict:
    """Extract only the approved company's overall rating from Omkar's API.

    The scraper exposes many review fields.  This integration deliberately
    ignores them and accepts only ``ratings.overall`` plus the aggregate count.
    The returned company name must match an explicitly approved alias so a
    broad search cannot attach another employer's rating to a vacancy.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProfileDataUnavailable("scraper Glassdoor retornou JSON inválido") from error
    if not isinstance(payload, dict):
        raise ProfileDataUnavailable("scraper Glassdoor retornou payload inválido")

    company = payload.get("company")
    returned_name = company.get("name") if isinstance(company, dict) else None
    allowed_names = {
        company_key(name) for name in (profile.get("company_names") or []) if company_key(name)
    }
    if not returned_name or company_key(returned_name) not in allowed_names:
        raise ProfileDataUnavailable("scraper Glassdoor retornou empresa diferente do perfil aprovado")

    ratings = payload.get("ratings")
    rating = _rating(ratings.get("overall") if isinstance(ratings, dict) else None)
    if rating is None:
        raise ProfileDataUnavailable("scraper Glassdoor não retornou ratings.overall válido")
    return {
        "rating": rating,
        "review_count": _review_count(payload.get("reviews_count")),
        "source": "omkar",
    }


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


def _omkar_endpoint() -> str:
    """Validate the local-only scraper endpoint used by the daily runner."""
    raw = str(os.environ.get("OMKAR_GLASSDOOR_ENDPOINT") or "").strip().rstrip("/")
    if not raw:
        raise GlassdoorConfigurationError("OMKAR_GLASSDOOR_ENDPOINT ausente")
    parsed = urllib.parse.urlsplit(raw)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
    ):
        raise GlassdoorConfigurationError(
            "endpoint Omkar deve ser HTTP(S) local (127.0.0.1/localhost/::1)"
        )
    return raw


def fetch_omkar_profile(
    profile: dict,
    *,
    endpoint: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener=urllib.request.urlopen,
) -> dict:
    """Fetch a single approved profile through Omkar's ratings endpoint."""
    base = _omkar_endpoint() if endpoint is None else endpoint.rstrip("/")
    query_name = str(profile.get("scraper_company") or (profile.get("company_names") or [""])[0]).strip()
    if not query_name:
        raise GlassdoorConfigurationError("perfil Glassdoor sem nome para o scraper")
    url = f"{base}/companies/ratings?{urllib.parse.urlencode({'company': query_name})}"
    body = _read_url(
        url,
        timeout=timeout,
        opener=opener,
        accept="application/json",
    )
    return parse_omkar_company_ratings(body, profile)


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
    if not parser.entries and parser.default_entry is None:
        return True
    return parser.can_fetch(DEFAULT_USER_AGENT, target_url)


def browserless_enabled() -> bool:
    """Return whether the optional rendered-page fallback is enabled."""
    return str(os.environ.get("BROWSERLESS_GLASSDOOR_ENABLED", "false")).strip().casefold() in _BROWSERLESS_ENABLED_VALUES


def _browserless_endpoint() -> str:
    """Validate a Browserless Content API endpoint without permitting SSRF."""
    raw = str(os.environ.get("BROWSERLESS_ENDPOINT") or "").strip().rstrip("/")
    if not raw:
        raise GlassdoorConfigurationError("BROWSERLESS_ENDPOINT ausente")
    parsed = urllib.parse.urlsplit(raw)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() not in {"http", "https"} or not host:
        raise GlassdoorConfigurationError("endpoint Browserless deve usar HTTP(S)")
    if parsed.username or parsed.password:
        raise GlassdoorConfigurationError("endpoint Browserless não pode conter credenciais")
    if host not in _BROWSERLESS_LOCAL_HOSTS and not (
        host == "browserless.io" or host.endswith(".browserless.io")
    ):
        raise GlassdoorConfigurationError("host não aprovado para Browserless")
    try:
        port = parsed.port
    except ValueError as error:
        raise GlassdoorConfigurationError("porta inválida no endpoint Browserless") from error
    if port is not None and host not in _BROWSERLESS_LOCAL_HOSTS:
        raise GlassdoorConfigurationError("endpoint Browserless remoto não pode informar porta")
    path = parsed.path.rstrip("/")
    if not (path.endswith("/content") or path.endswith("/chromium/content")):
        raise GlassdoorConfigurationError(
            "endpoint Browserless deve terminar em /content ou /chromium/content"
        )
    return raw


def _browserless_token() -> str:
    token = str(os.environ.get("BROWSERLESS_TOKEN") or "").strip()
    if not token:
        raise GlassdoorConfigurationError("BROWSERLESS_TOKEN ausente")
    return token


def _post_json(
    target_url: str,
    payload: dict,
    *,
    timeout: float,
    opener=urllib.request.urlopen,
) -> bytes:
    request = urllib.request.Request(
        target_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with opener(request, timeout=timeout) as response:
        content = response.read(MAX_RESPONSE_BYTES + 1)
    if len(content) > MAX_RESPONSE_BYTES:
        raise GlassdoorFetchError(f"resposta excedeu {MAX_RESPONSE_BYTES} bytes")
    return content


class _VisibleTextParser(HTMLParser):
    """Collect transient visible text for narrow aggregate-metric parsing."""

    _IGNORED = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in self._IGNORED:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._IGNORED and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data)


def parse_browserless_profile(payload: bytes | str) -> dict:
    """Extract only the overall rating and exact review count from rendered HTML."""
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
    parser = _VisibleTextParser()
    try:
        parser.feed(text)
        parser.close()
    except (TypeError, ValueError):
        pass
    visible = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    marker = re.search(r"avaliações\s+da\s+empresa", visible, flags=re.IGNORECASE)
    segment = visible[marker.end():] if marker else visible
    cutoff = re.search(
        r"classificação\s+por\s+categoria|avaliações\s+e\s+benefícios",
        segment,
        flags=re.IGNORECASE,
    )
    if cutoff:
        segment = segment[:cutoff.start()]
    rating = None
    rating_window = segment[:320]
    for pattern in (
        r"(?<![\d.,])([0-5](?:[.,]\d{1,2})?)\s*[★☆]",
        r"(?<![\d.,])([0-5](?:[.,]\d{1,2})?)\s+de\s+5\b",
        r"(?<![\d.,])([0-5][.,]\d{1,2})(?![\d.])",
    ):
        match = re.search(pattern, rating_window, flags=re.IGNORECASE)
        if match:
            rating = _rating(match.group(1))
            if rating is not None:
                break
    if rating is None:
        description_match = re.search(
            r"a\s+classificação\s+da\s+empresa\b.*?\bé\s+de\s+([0-5](?:[.,]\d{1,2})?)\s+de\s+5",
            visible,
            flags=re.IGNORECASE,
        )
        if description_match:
            rating = _rating(description_match.group(1))
    count_match = re.search(
        r"total\s+de\s*([\d., ]+)\s+avaliações",
        segment,
        flags=re.IGNORECASE,
    )
    count = _review_count(count_match.group(1)) if count_match else None
    if rating is None and count is None:
        raise ProfileDataUnavailable(
            "página renderizada sem média geral/quantidade exata de avaliações"
        )
    return {"rating": rating, "review_count": count}


def resolve_catalog_profile_via_browserless(
    company_name: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener=urllib.request.urlopen,
) -> dict:
    """Resolve one catalog company through the public Glassdoor search page."""
    if not browserless_enabled():
        return {
            "status": "disabled",
            "reason": "browserless_disabled",
            "source": "disabled",
        }
    try:
        endpoint = _browserless_endpoint()
        token = _browserless_token()
    except GlassdoorConfigurationError:
        return {
            "status": "disabled",
            "reason": "browserless_misconfigured",
            "source": "disabled",
        }

    search_url = (
        "https://www.glassdoor.com.br/Search/results.htm?"
        f"{urllib.parse.urlencode({'keyword': str(company_name).strip()})}"
    )
    if not _robots_allowed(search_url, timeout=timeout, opener=opener):
        return {
            "status": "missing",
            "reason": "no_exact_profile",
            "source": "browserless",
        }
    separator = "&" if "?" in endpoint else "?"
    browserless_url = f"{endpoint}{separator}{urllib.parse.urlencode({'token': token})}"
    try:
        body = _post_json(
            browserless_url,
            {
                "url": search_url,
                "waitForTimeout": _env_int("BROWSERLESS_WAIT_MS", 3000, 0, 15000),
                "gotoOptions": {"waitUntil": "networkidle2"},
            },
            timeout=timeout,
            opener=opener,
        )
    except Exception:
        return {
            "status": "error",
            "reason": "browserless_search_error",
            "source": "browserless",
        }

    class _SearchLinkParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.links: list[tuple[str, str]] = []
            self._href: str | None = None
            self._text: list[str] = []
            self._nested = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag.casefold() == "a" and self._href is None:
                attributes = dict(attrs)
                href = attributes.get("href")
                if href:
                    self._href = href
                    self._text = []
                    self._nested = 0
            elif self._href is not None:
                self._nested += 1

        def handle_endtag(self, tag: str) -> None:
            if self._href is None:
                return
            if tag.casefold() == "a" and self._nested == 0:
                self.links.append((self._href, " ".join(self._text)))
                self._href = None
                self._text = []
                return
            if self._nested:
                self._nested -= 1

        def handle_data(self, data: str) -> None:
            if self._href is not None and data.strip():
                self._text.append(data)

    parser = _SearchLinkParser()
    try:
        parser.feed(body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body))
        parser.close()
    except (TypeError, ValueError):
        return {
            "status": "error",
            "reason": "browserless_search_error",
            "source": "browserless",
        }

    requested_key = company_key(company_name)
    candidates: dict[str, str] = {}
    for raw_href, raw_text in parser.links:
        if company_key(raw_text) != requested_key:
            continue
        raw_href = html.unescape(str(raw_href or "").strip())
        parsed = urllib.parse.urlsplit(raw_href)
        if raw_href.startswith("//"):
            continue
        if raw_href.startswith("/"):
            candidate_url = urllib.parse.urljoin(
                "https://www.glassdoor.com.br", raw_href
            )
        elif parsed.scheme or parsed.netloc:
            candidate_url = raw_href
        else:
            continue
        candidate_parts = urllib.parse.urlsplit(candidate_url)
        if (
            candidate_parts.scheme.casefold() != "https"
            or (candidate_parts.hostname or "").casefold() != "www.glassdoor.com.br"
            or candidate_parts.username
            or candidate_parts.password
            or candidate_parts.port
        ):
            continue
        try:
            canonical = canonical_company_profile_url(candidate_url)
        except (GlassdoorConfigurationError, TypeError, ValueError):
            continue
        candidates[canonical] = raw_text.strip() or str(company_name).strip()

    if len(candidates) == 1:
        url, returned_name = next(iter(candidates.items()))
        return {
            "status": "matched",
            "company_name": returned_name,
            "url": url,
            "source": "browserless",
        }
    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "reason": "multiple_exact_profiles",
            "source": "browserless",
        }
    return {
        "status": "missing",
        "reason": "no_exact_profile",
        "source": "browserless",
    }


def fetch_browserless_profile(
    profile: dict,
    *,
    endpoint: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener=urllib.request.urlopen,
) -> dict:
    """Render one approved Glassdoor page through Browserless Content API."""
    url = canonical_company_profile_url(profile.get("url"))
    if not _robots_allowed(url, timeout=timeout, opener=opener):
        raise GlassdoorFetchError("robots.txt não autorizou o fallback Browserless")
    base = _browserless_endpoint() if endpoint is None else endpoint.rstrip("/")
    token = _browserless_token()
    separator = "&" if "?" in base else "?"
    target = f"{base}{separator}{urllib.parse.urlencode({'token': token})}"
    payload = {
        "url": url,
        "waitForTimeout": _env_int("BROWSERLESS_WAIT_MS", 3000, 0, 15000),
        "gotoOptions": {"waitUntil": "networkidle2"},
    }
    body = _post_json(target, payload, timeout=timeout, opener=opener)
    result = parse_browserless_profile(body)
    result["source"] = "browserless"
    return result


def _fetch_direct_profile(
    profile: dict,
    *,
    timeout: float,
    retries: int,
    backoff: float,
    sleeper,
    opener,
) -> dict:
    """Fetch a public profile without a rendering proxy."""
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
            result = parse_public_profile(body)
            result["source"] = "direct"
            return result
        except urllib.error.HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable:
                raise GlassdoorFetchError(f"Glassdoor respondeu HTTP {error.code}") from error
        except (GlassdoorError, OSError, TimeoutError, urllib.error.URLError) as error:
            last_error = error
        if attempt < attempts:
            sleeper(max(0.0, float(backoff)) * attempt)
    raise GlassdoorFetchError(
        f"consulta Glassdoor falhou após {attempts} tentativas: {last_error}"
    ) from last_error


def fetch_profile(
    profile: dict,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF_SECONDS,
    sleeper=time.sleep,
    opener=urllib.request.urlopen,
) -> dict:
    """Fetch primary data and use Browserless only for curated profiles on failure."""
    use_fallback = profile.get("browserless_fallback") is True and browserless_enabled()
    omkar_enabled = str(os.environ.get("OMKAR_GLASSDOOR_ENABLED") or "").strip().casefold() in _OMKAR_ENABLED_VALUES
    try:
        if omkar_enabled:
            return fetch_omkar_profile(profile, timeout=timeout, opener=opener)
        return _fetch_direct_profile(
            profile,
            timeout=timeout,
            retries=retries,
            backoff=backoff,
            sleeper=sleeper,
            opener=opener,
        )
    except Exception as primary_error:
        if not use_fallback:
            raise
        try:
            return fetch_browserless_profile(profile, timeout=timeout, opener=opener)
        except Exception as fallback_error:
            combined_error = GlassdoorFetchError(
                f"fonte primária falhou ({primary_error}); fallback Browserless falhou ({fallback_error})"
            )
            combined_error.fallback_attempted = True
            raise combined_error from fallback_error
