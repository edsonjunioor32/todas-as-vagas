"""Optional, local-only recovery paths for the private description crawler.

The normal HTTP/Obscura collector remains authoritative. These adapters never
use hosted AI or paid scraping endpoints, and they never search for a different
job to silently fill a known vacancy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import unicodedata
import urllib.parse
import urllib.request


MAX_ADAPTER_BYTES = 4 * 1024 * 1024
BLOCKED_PREFIXES = (
    "access denied", "acesso negado", "403 forbidden", "404 not found",
    "just a moment", "verifying you are human", "enable javascript",
    "captcha", "page not found", "página não encontrada",
    "utilizamos cookies", "we use cookies", "política de privacidade",
)
UNAVAILABLE_MARKERS = (
    "esta vaga não está mais disponível", "este vaga não está mais disponível",
    "this job is no longer available", "this job has expired",
)


def _tokens(value: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", str(value or "").casefold())
    ascii_text = "".join(c for c in folded if not unicodedata.combining(c))
    return {part for part in re.findall(r"[a-z0-9]+", ascii_text) if len(part) >= 4}


def same_posting_url(original: str, resolved: str) -> bool:
    """Do not associate a redirected generic page or a different job."""
    first = urllib.parse.urlsplit(original)
    second = urllib.parse.urlsplit(resolved)
    return (
        first.scheme in {"http", "https"}
        and second.scheme in {"http", "https"}
        and first.hostname == second.hostname
        and first.path.rstrip("/") == second.path.rstrip("/")
        and sorted(urllib.parse.parse_qsl(first.query, keep_blank_values=True))
            == sorted(urllib.parse.parse_qsl(second.query, keep_blank_values=True))
    )


def acceptable_description(
    job: dict,
    description: str,
    *,
    kind: str,
    resolved_url: str,
    page_title: str = "",
    min_chars: int = 120,
) -> bool:
    """Career-Ops-style provenance/quality gate for recovered page text."""
    value = str(description or "").strip()
    if len(value) < max(1, min_chars) or not same_posting_url(job["url"], resolved_url):
        return False
    opening = value[:400].casefold().strip()
    if (any(opening.startswith(marker) for marker in BLOCKED_PREFIXES)
            or any(marker in value[:4000].casefold() for marker in UNAVAILABLE_MARKERS)):
        return False
    if kind in {"job_container", "selector"} and len(value) < max(200, min_chars):
        return False
    if kind in {"json", "jsonld", "job_container", "selector"}:
        return True
    # Whole-page/Markdown fallbacks need evidence that the page is this job.
    title_tokens = _tokens(job.get("title", ""))
    if not title_tokens:
        return False
    evidence = _tokens(page_title + " " + value[:4000])
    return len(title_tokens & evidence) >= min(2, len(title_tokens))


def _local_firecrawl_url(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(str(endpoint or "").strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Firecrawl deve usar apenas HTTP local na VPS")
    return urllib.parse.urlunsplit(("http", parsed.netloc, "/v2/scrape", "", ""))


def firecrawl_local(
    job: dict,
    *,
    endpoint: str,
    timeout: float,
    min_chars: int,
) -> tuple[str, str, str]:
    """Ask a self-hosted Firecrawl for HTML; never contact Firecrawl Cloud."""
    if not endpoint:
        return "", "", "firecrawl desabilitado"
    try:
        api_url = _local_firecrawl_url(endpoint)
        request = urllib.request.Request(
            api_url,
            data=json.dumps({
                "url": job["url"], "formats": ["html"],
                "timeout": int(max(5, timeout) * 1000),
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=max(5, timeout) + 5) as response:
            raw = response.read(MAX_ADAPTER_BYTES + 1)
        if len(raw) > MAX_ADAPTER_BYTES:
            return "", "", "firecrawl excedeu o limite de resposta"
        result = json.loads(raw)
        if result.get("success") is not True:
            return "", "", "firecrawl não retornou sucesso"
        data = result.get("data") or {}
        metadata = data.get("metadata") or {}
        status = metadata.get("statusCode")
        if status is not None and int(status) >= 400:
            return "", "", f"firecrawl retornou HTTP {status}"
        resolved = str(metadata.get("url") or metadata.get("sourceURL") or job["url"])
        if not same_posting_url(job["url"], resolved):
            return "", "", "firecrawl redirecionou para outra página"
        from description_crawler import extract_description

        html = str(data.get("html") or "")
        description, kind = extract_description(
            html.encode("utf-8"), "text/html", min_chars=min_chars,
        )
        if acceptable_description(
            job, description, kind=kind, resolved_url=resolved,
            page_title=str(metadata.get("title") or ""), min_chars=min_chars,
        ):
            return description, f"firecrawl_{kind}", ""
        return "", "", "firecrawl não forneceu descrição verificável"
    except (OSError, TimeoutError, ValueError, TypeError, KeyError) as error:
        return "", "", f"firecrawl falhou: {type(error).__name__}"


def browser_use_local(
    job: dict,
    *,
    python: str,
    timeout: float,
    min_chars: int,
    chromium: str = "/snap/bin/chromium",
) -> tuple[str, str, str]:
    """Render in local Chromium via browser-use's Browser API, without an LLM."""
    executable = str(python or "").strip()
    if not executable:
        return "", "", "browser-use desabilitado"
    helper = Path(__file__).with_name("browser_use_description.py")
    environment = os.environ.copy()
    environment.update({
        "ANONYMIZED_TELEMETRY": "false",
        "BROWSER_USE_CLOUD_SYNC": "false",
        "BROWSER_USE_VERSION_CHECK": "false",
        "BROWSER_USE_LOGGING_LEVEL": "critical",
        "BROWSER_USE_SETUP_LOGGING": "false",
    })
    for key in ("BROWSER_USE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        environment.pop(key, None)
    try:
        result = subprocess.run(
            [executable, str(helper), job["url"], str(max(5, int(timeout))),
             str(max(1, int(min_chars))), chromium],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=max(10, float(timeout) + 15), check=False, env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return "", "", f"browser-use falhou: {type(error).__name__}"
    if result.returncode:
        return "", "", f"browser-use terminou com código {result.returncode}"
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, TypeError, IndexError):
        return "", "", "browser-use retornou resposta inválida"
    description = str(data.get("description") or "").strip()[:60000]
    kind = str(data.get("kind") or "")
    if acceptable_description(
        job, description, kind=kind,
        resolved_url=str(data.get("url") or ""),
        page_title=str(data.get("title") or ""), min_chars=min_chars,
    ):
        return description, f"browser_use_{kind}", ""
    return "", "", "browser-use não forneceu descrição verificável"
