# -*- coding: utf-8 -*-
"""Small stdlib-only client for HasData's Glassdoor Streamable HTTP MCP."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable


DEFAULT_ENDPOINT = "https://mcp.hasdata.com/mcp?apis=glassdoor"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 2.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
SEARCH_TOOL = "hasdata_glassdoor_listing_getJobListings"
ALLOWED_ENDPOINT_HOST = "mcp.hasdata.com"


class HasDataGlassdoorMcpError(RuntimeError):
    """Non-fatal MCP transport or payload failure."""


class HasDataGlassdoorMcpConfigurationError(ValueError):
    """Invalid local MCP configuration."""


class HasDataGlassdoorMcpClient:
    """Call the read-only Glassdoor tools exposed by HasData's remote MCP."""

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF_SECONDS,
        opener: Callable = urllib.request.urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        clean_key = str(api_key or "").strip()
        if not clean_key:
            raise HasDataGlassdoorMcpConfigurationError("HASDATA_API_KEY ausente")
        parsed_endpoint = urllib.parse.urlsplit(str(endpoint or "").strip())
        if (
            parsed_endpoint.scheme.casefold() != "https"
            or parsed_endpoint.hostname != ALLOWED_ENDPOINT_HOST
            or parsed_endpoint.username
            or parsed_endpoint.password
            or parsed_endpoint.port
        ):
            raise HasDataGlassdoorMcpConfigurationError(
                "endpoint HasData deve ser o host HTTPS oficial mcp.hasdata.com"
            )
        self.api_key = clean_key
        self.endpoint = str(endpoint).strip()
        self.timeout = max(0.1, float(timeout))
        self.retries = min(5, max(0, int(retries)))
        self.backoff = max(0.0, float(backoff))
        self.opener = opener
        self.sleeper = sleeper
        self._request_id = 0
        self._session_id: str | None = None
        self._initialized = False
        self._tools: dict | None = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @staticmethod
    def _header(headers: object, name: str) -> str | None:
        if headers is None:
            return None
        getter = getattr(headers, "get", None)
        if getter is None:
            return None
        for candidate in (name, name.lower(), name.title()):
            value = getter(candidate)
            if value:
                return str(value)
        return None

    @staticmethod
    def _sse_messages(body: str):
        data_lines: list[str] = []
        for line in body.splitlines() + [""]:
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
                continue
            if not line.strip() and data_lines:
                value = "\n".join(data_lines).strip()
                data_lines = []
                if not value or value == "[DONE]":
                    continue
                try:
                    yield json.loads(value)
                except (TypeError, ValueError, json.JSONDecodeError) as error:
                    raise HasDataGlassdoorMcpError("resposta SSE do HasData não é JSON válido") from error

    @classmethod
    def _decode_response(
        cls,
        body: bytes,
        content_type: str = "",
        *,
        expected_id: int | None = None,
    ) -> dict | None:
        if not body:
            return None
        text = body.decode("utf-8", "replace")
        if "text/event-stream" in str(content_type).casefold() or text.lstrip().startswith("data:"):
            messages = list(cls._sse_messages(text))
            if not messages:
                return None
            if expected_id is None:
                return messages[-1]
            for message in messages:
                if isinstance(message, dict) and message.get("id") == expected_id:
                    return message
            raise HasDataGlassdoorMcpError(
                "resposta SSE do HasData não corresponde à requisição"
            )
        try:
            value = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise HasDataGlassdoorMcpError("resposta JSON do HasData é inválida") from error
        if not isinstance(value, dict):
            raise HasDataGlassdoorMcpError("resposta JSON do HasData não é um objeto")
        if expected_id is not None and value.get("id") != expected_id:
            raise HasDataGlassdoorMcpError(
                "resposta JSON do HasData não corresponde à requisição"
            )
        return value

    @classmethod
    def _result(cls, response: dict | None) -> dict:
        if response is None:
            return {}
        if response.get("error"):
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise HasDataGlassdoorMcpError(f"erro JSON-RPC do HasData: {message}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise HasDataGlassdoorMcpError("resposta JSON-RPC do HasData sem result")
        return result

    def _post(self, payload: dict, *, notification: bool = False) -> dict | None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "TodasAsVagasHasDataMcp/1.0",
            "x-api-key": self.api_key,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        attempts = self.retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    session_id = self._header(getattr(response, "headers", None), "Mcp-Session-Id")
                    if session_id:
                        self._session_id = session_id
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise HasDataGlassdoorMcpError("resposta do HasData excedeu o limite")
                    content_type = self._header(getattr(response, "headers", None), "Content-Type") or ""
                    expected_id = payload.get("id")
                    return self._decode_response(
                        raw,
                        content_type,
                        expected_id=expected_id if isinstance(expected_id, int) else None,
                    )
            except urllib.error.HTTPError as error:
                last_error = error
                retryable = error.code == 429 or error.code >= 500
                if not retryable:
                    raise HasDataGlassdoorMcpError(f"HasData respondeu HTTP {error.code}") from error
            except HasDataGlassdoorMcpError:
                raise
            except (OSError, TimeoutError, urllib.error.URLError) as error:
                last_error = error
            if attempt < attempts:
                self.sleeper(self.backoff * attempt)
        raise HasDataGlassdoorMcpError(
            f"consulta HasData falhou após {attempts} tentativas: {last_error}"
        ) from last_error

    def initialize(self) -> dict:
        if self._initialized:
            return {}
        response = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "todas-as-vagas", "version": "1.0"},
            },
        })
        result = self._result(response)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, notification=True)
        self._initialized = True
        return result

    def list_tools(self) -> dict:
        self.initialize()
        if self._tools is None:
            response = self._post({
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
                "params": {},
            })
            self._tools = self._result(response)
        return self._tools

    @staticmethod
    def _json_object_from_text(text: str) -> dict | None:
        """Decode JSON returned as plain text, fenced Markdown, or prefixed text."""
        cleaned = str(text or "").strip()
        if not cleaned:
            return None
        candidates = [cleaned]
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 3 and lines[0].lstrip().startswith("```") and lines[-1].strip() == "```":
                candidates.append("\n".join(lines[1:-1]).strip())
        decoder = json.JSONDecoder()
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except (TypeError, ValueError, json.JSONDecodeError):
                value = None
            if isinstance(value, dict):
                return value
            for position, char in enumerate(candidate):
                if char != "{":
                    continue
                try:
                    value, _end = decoder.raw_decode(candidate[position:])
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict):
                    return value
        return None

    @classmethod
    def _tool_payload(cls, result: dict) -> dict | None:
        """Read structuredContent first, then JSON-bearing MCP content."""
        for key in ("structuredContent", "structured_content"):
            value = result.get(key)
            if isinstance(value, dict):
                return value
        content = result.get("content")
        if not isinstance(content, list):
            return None
        for item in content:
            if not isinstance(item, dict):
                continue
            for key in ("json", "data", "structuredContent", "structured_content"):
                value = item.get(key)
                if isinstance(value, dict):
                    return value
            value = cls._json_object_from_text(item.get("text", ""))
            if value is not None:
                return value
        return None

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self.list_tools()
        response = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": str(name), "arguments": arguments or {}},
        })
        result = self._result(response)
        value = self._tool_payload(result)
        if value is None:
            if not result.get("content"):
                raise HasDataGlassdoorMcpError("resultado do HasData sem content ou structuredContent")
            raise HasDataGlassdoorMcpError("resultado estruturado do HasData não foi reconhecido")
        return value

    def search_jobs(
        self,
        *,
        keyword: str,
        location: str,
        domain: str = "www.glassdoor.com.br",
        sort: str = "recent",
    ) -> dict:
        return self.call_tool(
            SEARCH_TOOL,
            {
                "keyword": str(keyword),
                "location": str(location),
                "domain": str(domain),
                "sort": str(sort),
            },
        )
