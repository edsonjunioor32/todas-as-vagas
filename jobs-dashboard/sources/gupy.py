# -*- coding: utf-8 -*-
"""Gupy (Brazil) — public candidate MCP, no key.

Adapted from the user's fetch_gupy_jobs_lote4.py. The profile/adherence filtering
is intentionally dropped: this project keeps every job and only classifies it.
The public candidate search is consumed through Gupy's Streamable HTTP MCP.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from ._http import get_text
from ._common import strip_html, iso_date, work_model_label, job

MCP_ENDPOINT = os.environ.get(
    "GUPY_CANDIDATES_MCP_URL", "https://candidates.mcp.api.gupy.io/mcp"
)
MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "User-Agent": "todas-as-vagas/1.0 (public vacancy collector)",
}

# Complementary searches fill older active results beyond the MCP's first 10k
# broad matches. Keep a smaller, cross-functional set to respect rate limits.
TERMS = [
    "analista", "desenvolvedor", "vendas", "atendimento", "marketing",
    "financeiro", "administrativo", "logística", "operações",
    "recursos humanos", "estágio", "jovem aprendiz", "engenheiro",
    "suporte", "coordenador", "gerente", "produto", "customer success",
]

PAGE = 100
MAX_OFFSET = 400                 # bounded collection: at most 500 results per term
MCP_PAGE_DELAY_SECONDS = 0.25
MONITORED_CAREER_PAGES = (
    "https://voxtecnologia.gupy.io/",
    "https://creditas.gupy.io/",
)
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.I | re.S,
)
TALENT_POOL_RE = re.compile(
    r"\b(?:banco\s+(?:de\s+)?talentos?|talent\s+pool)\b",
    re.I,
)


class GupyMCPClient:
    """Small stdlib-only client for Gupy's public Streamable HTTP MCP."""

    def __init__(self, endpoint=None, timeout=35):
        self.endpoint = endpoint or MCP_ENDPOINT
        self.timeout = timeout
        self.session_id = ""
        self.protocol_version = ""
        self.request_id = 0

    @staticmethod
    def _retry_delay(status, retry_after, attempt, detail=""):
        delay = 0.5 * attempt
        if status != 429:
            return delay
        try:
            delay = max(delay, float(retry_after))
        except (TypeError, ValueError):
            delay = max(delay, 5 * (2 ** (attempt - 1)))
        if "1015" in str(detail):
            delay = max(delay, 30)
        return delay

    @staticmethod
    def _decode_response(raw, content_type):
        text = raw.decode("utf-8", "replace").strip()
        if not text:
            return None
        if "text/event-stream" in str(content_type).casefold():
            for event in reversed(text.split("\n\n")):
                data_lines = [
                    line[5:].lstrip()
                    for line in event.splitlines()
                    if line.startswith("data:")
                ]
                payload = "\n".join(data_lines).strip()
                if payload and payload != "[DONE]":
                    return json.loads(payload)
            raise RuntimeError("Gupy MCP respondeu SSE sem uma mensagem JSON")
        return json.loads(text)

    def _post(self, payload, include_version=True):
        headers = dict(MCP_HEADERS)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if include_version and self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        last_error = None
        for attempt in range(1, 4):
            retry_delay = 0.5 * attempt
            request = urllib.request.Request(
                self.endpoint, data=body, headers=headers, method="POST"
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self.session_id = (
                        response.headers.get("Mcp-Session-Id") or self.session_id
                    )
                    return self._decode_response(
                        response.read(), response.headers.get("Content-Type", "")
                    )
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:300]
                last_error = RuntimeError(
                    f"Gupy MCP HTTP {error.code}: {detail or error.reason}"
                )
                if error.code < 500 and error.code != 429:
                    raise last_error from error
                retry_delay = self._retry_delay(
                    error.code,
                    (error.headers or {}).get("Retry-After", ""),
                    attempt,
                    detail,
                )
            except Exception as error:
                last_error = error
            if attempt < 3:
                time.sleep(retry_delay)
        raise RuntimeError(
            f"Gupy MCP indisponível após 3 tentativas: {last_error}"
        ) from last_error

    def _rpc(self, method, params=None):
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        response = self._post(payload)
        if not isinstance(response, dict):
            raise RuntimeError(f"Gupy MCP não retornou resposta para {method}")
        if response.get("error"):
            error = response["error"]
            raise RuntimeError(
                f"Gupy MCP {method} falhou: {error.get('message', error)}"
            )
        return response.get("result") or {}

    def connect(self):
        result = self._rpc("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "todas-as-vagas", "version": "1.0.0"},
        })
        self.protocol_version = result.get(
            "protocolVersion", MCP_PROTOCOL_VERSION
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call_tool(self, name, arguments):
        if not self.protocol_version:
            self.connect()
        result = self._rpc("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if result.get("isError"):
            content = result.get("content") or []
            message = next(
                (item.get("text", "") for item in content if item.get("type") == "text"),
                "erro informado pela ferramenta",
            )
            raise RuntimeError(f"Gupy MCP {name}: {message[:300]}")
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        for item in result.get("content") or []:
            if item.get("type") != "text":
                continue
            try:
                return json.loads(item.get("text") or "")
            except json.JSONDecodeError:
                continue
        raise RuntimeError(f"Gupy MCP {name} não retornou dados JSON")

    def close(self):
        if not self.session_id:
            return
        headers = {"Mcp-Session-Id": self.session_id}
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        request = urllib.request.Request(
            self.endpoint, headers=headers, method="DELETE"
        )
        try:
            with urllib.request.urlopen(request, timeout=5):
                pass
        except Exception:
            # Session cleanup is best-effort; the server also expires idle sessions.
            pass


def is_talent_pool(item):
    job_type = str(item.get("type") or item.get("source_type") or "").strip().casefold()
    title = str(item.get("name") or item.get("title") or "")
    return (
        job_type == "vacancy_type_talent_pool"
        or bool(TALENT_POOL_RE.search(title))
    )


def is_verified_public_listing(item):
    """Accept explicit public API evidence or a public candidate MCP result."""
    status = str(item.get("status") or item.get("source_status") or "").strip().casefold()
    publication_type = str(
        item.get("publicationType") or item.get("source_publication_type") or ""
    ).strip().casefold()
    job_type = str(item.get("type") or item.get("source_type") or "").strip().casefold()
    explicit_public = status == "published" and publication_type == "external"
    candidate_mcp_public = (
        status == "public_search" and publication_type == "candidate_mcp"
    )
    return (
        (explicit_public or candidate_mcp_public)
        and bool(job_type)
        and not is_talent_pool(item)
    )


def _api_row(item):
    if not is_verified_public_listing(item):
        return None
    published_date = iso_date(item.get("publishedAt") or item.get("publishedDate"))
    if not published_date:
        return None
    jid = item.get("id")
    remote = bool(item.get("isRemoteWork"))
    skills = [
        value.get("name", "") if isinstance(value, dict) else str(value)
        for value in (item.get("skills") or [])
    ]
    return job(
        "gupy", jid,
        title=item.get("name", ""),
        company=item.get("careerPageName", ""),
        url=item.get("jobUrl", ""),
        work_model=work_model_label(remote, item.get("workplaceType")),
        city=item.get("city", "") or "",
        state=item.get("state", "") or "",
        country="BR", market="BR",
        published_date=published_date,
        expires_date=iso_date(item.get("applicationDeadline")),
        skills=[value for value in skills if value],
        description=strip_html(item.get("description", "")),
        source_status=str(
            item.get("status") or item.get("source_status") or ""
        ).strip().casefold(),
        source_type=str(item.get("type") or "").strip().casefold(),
        source_publication_type=str(
            item.get("publicationType") or item.get("source_publication_type") or ""
        ).strip().casefold(),
    )


def _candidate_mcp_row(item):
    """Map a result returned by Gupy's public candidate search tool."""
    if item.get("isConfidentialCareerPage") is True:
        return None
    public_item = dict(item)
    public_item["source_status"] = "public_search"
    public_item["source_publication_type"] = "candidate_mcp"
    return _api_row(public_item)


def _search_page(client, term, offset):
    arguments = {
        "country": "Brasil",
        "limit": PAGE,
        "offset": offset,
        "sortBy": "publishedDate",
        "sortOrder": "desc",
    }
    if term:
        arguments["term"] = term
    result = client.call_tool("search_jobs", arguments)
    payload = result.get("data") if isinstance(result, dict) else None
    if isinstance(payload, dict):
        rows = payload.get("data") or []
        pagination = payload.get("pagination") or {}
    elif isinstance(payload, list):
        rows = payload
        pagination = {}
    else:
        raise RuntimeError("Gupy MCP search_jobs retornou formato inesperado")
    return rows, pagination.get("total")


def _reached_reported_total(offset, row_count, total):
    """Ignore MCP totals that are clipped to the requested page size."""
    try:
        total = int(total)
    except (TypeError, ValueError):
        return False
    return total > PAGE and offset + row_count >= total


def _fetch_recent_catalog(client):
    """Collect the broad, newest-first public index within MCP offset limits."""
    max_pages = min(
        max(1, int(os.environ.get("GUPY_BROAD_MAX_PAGES") or 100)),
        (9999 // PAGE) + 1,
    )
    out = []
    for page_number in range(max_pages):
        offset = page_number * PAGE
        data, total = _search_page(client, None, offset)
        out.extend(
            row for item in data
            if isinstance(item, dict)
            and (row := _candidate_mcp_row(item)) is not None
        )
        if not data or len(data) < PAGE:
            break
        if _reached_reported_total(offset, len(data), total):
            break
        time.sleep(MCP_PAGE_DELAY_SECONDS)
    return out


def _fetch_term(term, client=None):
    owns_client = client is None
    client = client or GupyMCPClient()
    if owns_client:
        client.connect()
    out = []
    max_pages = min(
        max(1, int(os.environ.get("GUPY_MAX_PAGES_PER_TERM") or 5)),
        (9999 // PAGE) + 1,
    )
    try:
        for page_number in range(max_pages):
            offset = page_number * PAGE
            data, total = _search_page(client, term, offset)
            out.extend(
                row for item in data
                if isinstance(item, dict)
                and (row := _candidate_mcp_row(item)) is not None
            )
            if not data or len(data) < PAGE:
                break
            if _reached_reported_total(offset, len(data), total):
                break
            if offset >= MAX_OFFSET:
                break
            time.sleep(MCP_PAGE_DELAY_SECONDS)
    finally:
        if owns_client:
            client.close()
    return out


def _fetch_term_batch(terms):
    client = GupyMCPClient()
    client.connect()
    try:
        return [(term, _fetch_term(term, client)) for term in terms]
    finally:
        client.close()


def _career_page_rows(page_url):
    """Read the small active-job catalog embedded in a monitored Gupy page."""
    html = get_text(page_url, timeout=30)
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError(f"Gupy career page without __NEXT_DATA__: {page_url}")
    props = json.loads(match.group(1)).get("props", {}).get("pageProps", {})
    company = str((props.get("careerPage") or {}).get("name") or "").strip()
    base_url = page_url.rstrip("/")
    rows = []
    for item in props.get("jobs") or []:
        jid = item.get("id")
        if not jid:
            continue
        if is_talent_pool(item):
            continue
        status = str(item.get("status") or "").strip().casefold()
        publication_type = str(item.get("publicationType") or "").strip().casefold()
        if status and status != "published":
            continue
        if publication_type and publication_type != "external":
            continue
        workplace = item.get("workplace") or {}
        address = workplace.get("address") or {}
        rows.append(job(
            "gupy", jid,
            title=item.get("title", ""),
            company=company,
            url=f"{base_url}/jobs/{jid}?jobBoardSource=gupy_public_page",
            work_model=work_model_label(None, workplace.get("workplaceType")),
            city=address.get("city", "") or "",
            state=address.get("state", "") or "",
            country="BR", market="BR",
            categories=[str(item.get("department") or "").strip()],
        ))
    return rows


def _fetch_exact_job(row, client):
    """Enrich a monitored job through the public MCP detail tool."""
    native_id = str(row.get("native_id") or "")
    try:
        item = client.call_tool("get_job_by_id", {"id": int(native_id)})
    except (TypeError, ValueError):
        return None
    if not isinstance(item, dict):
        return None
    item = item.get("data") if isinstance(item.get("data"), dict) else item
    if str(item.get("id") or "") != native_id:
        return None
    return _candidate_mcp_row(item)


def _monitored_pages():
    configured = os.environ.get("GUPY_MONITORED_PAGES")
    if configured is None:
        return MONITORED_CAREER_PAGES
    return tuple(value.strip() for value in configured.split(",") if value.strip())


def fetch():
    # The broad query brings in the newest public jobs regardless of title.
    # Term searches then extend coverage beyond MCP's 10k-result offset ceiling.
    limit = int(os.environ.get("GUPY_MAX_TERMS") or len(TERMS))
    workers = min(max(1, int(os.environ.get("GUPY_WORKERS") or 1)), 2)
    client = GupyMCPClient()
    try:
        client.connect()
        recent_rows = _fetch_recent_catalog(client)
    finally:
        client.close()
    unique = {
        str(row.get("native_id") or row.get("url")): row
        for row in recent_rows
    }
    terms = TERMS[:limit]
    batches = [terms[index::workers] for index in range(workers)]
    batches = [batch for batch in batches if batch]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_fetch_term_batch, batch) for batch in batches]
        for future in as_completed(futures):
            for _, rows in future.result():
                for row in rows:
                    unique[str(row.get("native_id") or row.get("url"))] = row

    # Monitored boards catch vacancies outside the broad search's per-term cap.
    monitored_pages = _monitored_pages()
    if monitored_pages:
        client = GupyMCPClient()
        try:
            client.connect()
            for page_url in monitored_pages:
                try:
                    page_rows = _career_page_rows(page_url)
                except Exception as error:
                    print(f"    [gupy monitor] {page_url} indisponível: {str(error)[:100]}")
                    continue
                for row in page_rows:
                    key = str(row.get("native_id") or row.get("url"))
                    if key in unique:
                        continue
                    try:
                        row = _fetch_exact_job(row, client)
                        if row is None:
                            print(f"    [gupy monitor] vaga {key} sem confirmação no MCP público")
                            continue
                    except Exception as error:
                        print(f"    [gupy monitor] vaga {key} sem enriquecimento: {str(error)[:100]}")
                        continue
                    unique[key] = row
        finally:
            client.close()
    return list(unique.values())
