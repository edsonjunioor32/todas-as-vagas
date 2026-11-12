# -*- coding: utf-8 -*-
"""Read public InHire job descriptions through InHire's public API.

InHire career pages are client-rendered applications.  Their initial HTML is
usually only an application shell, while the public job response is available
from the API after resolving the tenant from the career-page subdomain.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


API_BASE_URL = "https://api.inhire.app"
INHIRE_HOST_SUFFIX = ".inhire.app"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_JOB_ID_RE = re.compile(
    r"(?i)(?<![0-9a-f])"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?![0-9a-f])"
)
_DESCRIPTION_KEYS = {"description", "jobdescription", "job_description"}


@dataclass(frozen=True)
class InhireDescriptionResult:
    """Result of one public InHire API attempt."""

    description: str = ""
    content_kind: str = ""
    status: str = "error"
    http_status: int | None = None
    error: str = ""


@dataclass(frozen=True)
class InhireJobReference:
    subdomain: str
    job_id: str


def job_reference(url: str) -> InhireJobReference | None:
    """Return the public tenant and job ID encoded in an InHire URL."""

    parsed = urllib.parse.urlsplit(str(url or ""))
    host = parsed.hostname.casefold() if parsed.hostname else ""
    if not host.endswith(INHIRE_HOST_SUFFIX):
        return None
    subdomain = host[: -len(INHIRE_HOST_SUFFIX)].split(".", 1)[0].strip()
    if not subdomain or subdomain in {"www", "api"}:
        return None
    match = _JOB_ID_RE.search(parsed.path)
    if not match:
        return None
    return InhireJobReference(subdomain=subdomain, job_id=match.group(0))


def is_inhire_url(url: str) -> bool:
    return job_reference(url) is not None


def _clean_html(value: object, limit: int = 60000) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(
        r"<\s*(?:br|/p|/li|/h[1-6]|/div|/section|/article)[^>]*>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def _description_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in _DESCRIPTION_KEYS and isinstance(child, str):
                cleaned = _clean_html(child)
                if cleaned:
                    values.append(cleaned)
            elif isinstance(child, (dict, list)):
                values.extend(_description_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_description_values(child))
    return values


def _request_json(
    path: str,
    *,
    timeout: float,
    user_agent: str,
    tenant_id: str = "",
) -> tuple[dict[str, Any], int]:
    headers = {
        "Accept": "application/json",
        "User-Agent": user_agent,
        "X-Inhire-Client": "web-inhire",
    }
    if tenant_id:
        headers["X-Tenant"] = tenant_id
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("resposta pública do InHire excedeu o limite")
        payload = json.loads(body.decode("utf-8", "replace"))
        if not isinstance(payload, dict):
            raise ValueError("resposta pública do InHire não é um objeto JSON")
        return payload, int(getattr(response, "status", 200) or 200)


def _error_result(
    error: Exception,
    *,
    status: str = "error",
    http_status: int | None = None,
) -> InhireDescriptionResult:
    return InhireDescriptionResult(
        status=status,
        http_status=http_status,
        error=str(error)[:300],
    )


def fetch_description(
    url: str,
    *,
    timeout: float,
    user_agent: str,
    min_chars: int = 120,
) -> InhireDescriptionResult:
    """Fetch one description without authentication or browser automation."""

    reference = job_reference(url)
    if reference is None:
        return InhireDescriptionResult(status="unsupported", error="URL não é um anúncio InHire")

    encoded_subdomain = urllib.parse.quote(reference.subdomain, safe="")
    try:
        config, _ = _request_json(
            f"/tenants/public/config/resolve/{encoded_subdomain}",
            timeout=timeout,
            user_agent=user_agent,
        )
        tenant = config.get("tenant") if isinstance(config.get("tenant"), dict) else {}
        subdomain = config.get("subdomain") if isinstance(config.get("subdomain"), dict) else {}
        tenant_id = str(subdomain.get("tenantId") or tenant.get("id") or "").strip()
        if not tenant_id:
            return _error_result(
                ValueError("tenant público não foi resolvido"),
                status="error",
            )
    except urllib.error.HTTPError as error:
        if error.code in {404, 410}:
            return _error_result(error, status="gone", http_status=error.code)
        return _error_result(error, status=f"http_{error.code}", http_status=error.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return _error_result(error, status="network_error")

    try:
        payload, http_status = _request_json(
            f"/job-posts/public/pages/{urllib.parse.quote(reference.job_id, safe='')}",
            timeout=timeout,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )
    except urllib.error.HTTPError as error:
        if error.code in {404, 410}:
            return _error_result(error, status="gone", http_status=error.code)
        return _error_result(error, status=f"http_{error.code}", http_status=error.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return _error_result(error, status="network_error")

    candidates = [value for value in _description_values(payload) if len(value) >= max(1, int(min_chars))]
    if not candidates:
        return InhireDescriptionResult(
            status="no_description",
            http_status=http_status,
            error="API pública do InHire não retornou descrição suficiente",
        )
    return InhireDescriptionResult(
        description=max(candidates, key=len),
        content_kind="inhire_api",
        status="fetched",
        http_status=http_status,
    )
