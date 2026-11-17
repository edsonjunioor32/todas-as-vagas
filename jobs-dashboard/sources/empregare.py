# -*- coding: utf-8 -*-
"""Empregare — catálogo público via servidor MCP oficial (sem chave).

Endpoint oficial (anunciado em https://www.empregare.com/pt-br/llms.txt):
  POST https://www.empregare.com/api/mcp  (Streamable HTTP, ferramenta ``buscar_vagas``)

Desde 07/11/2026 o endpoint REST ``/api/pt-br/vagas/buscar-novo`` fica atrás de
um limite do Cloudflare: devolve HTTP 429 já na sexta requisição (Retry-After
de 83 s a 600 s) e aceita no máximo 30 itens por página (~151 páginas). Com 4
workers em paralelo a coleta esgotava as retentativas e a fonte inteira falhava.

O MCP aceita 50 itens por página (~91 páginas) e não bloqueou chamadas
sequenciais a ~1/s. A coleta é sequencial, com pausa entre páginas e
retentativa que respeita ``Retry-After``. O MCP não informa data de publicação;
o armazenamento preserva a data já conhecida e usa o primeiro avistamento como
fallback para vagas novas.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from ._common import job, split_location, work_model_label
from ._errors import SourceFormatError, exhausted
from ._http import DEFAULT_HEADERS, retry_delay

ENDPOINT = "https://www.empregare.com/api/mcp"
PROTOCOL = "2025-06-18"
TOOL = "buscar_vagas"
PAGE_SIZE = 50  # máximo aceito pela ferramenta
RETRIES = 4


def _parse_body(text):
    """Aceita resposta JSON direta ou Server-Sent Events (último ``data:``)."""
    text = text.strip()
    if not text.startswith("{"):
        data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        if not data:
            raise SourceFormatError("Empregare MCP returned no JSON-RPC payload")
        text = data[-1]
    return json.loads(text)


def _rpc(arguments, request_id):
    headers = dict(DEFAULT_HEADERS)
    headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL,
    })
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": TOOL, "arguments": arguments},
    }).encode("utf-8")
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=40) as resp:
                return _parse_body(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            last_err = error
            if error.code < 500 and error.code != 429:
                raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            last_err = error
        if attempt < RETRIES:
            time.sleep(retry_delay(attempt, 2.0, last_err))
    raise exhausted(f"Empregare MCP failed after {RETRIES} attempts: {last_err}", last_err) from last_err


def _page(page):
    envelope = _rpc({"pagina": page, "itensPagina": PAGE_SIZE}, page)
    if envelope.get("error"):
        raise SourceFormatError(f"Empregare MCP error on page {page}: {envelope['error']}")
    result = envelope.get("result") or {}
    if result.get("isError"):
        raise SourceFormatError(f"Empregare MCP tool error on page {page}")
    content = result.get("content") or []
    text = next((c.get("text") for c in content if c.get("type") == "text"), None)
    if not text:
        raise SourceFormatError(f"Empregare MCP returned no content on page {page}")
    payload = json.loads(text)
    if not payload.get("sucesso"):
        raise SourceFormatError(f"Empregare returned sucesso=false on page {page}")
    return payload, payload.get("vagas") or []


def _money(value):
    text = str(value or "")
    numbers = re.findall(r"\d[\d.]*,\d{2}|\d+(?:[.,]\d+)?", text)
    parsed = []
    for raw in numbers:
        try:
            if "," in raw:
                parsed.append(float(raw.replace(".", "").replace(",", ".")))
            else:
                parsed.append(float(raw))
        except ValueError:
            continue
    if not parsed:
        return None, None, None
    currency = "BRL" if "R$" in text else None
    return min(parsed), max(parsed) if len(parsed) > 1 else None, currency


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "sim", "yes"}


def _normalize(item):
    locations = [str(x).strip() for x in (item.get("cidades") or []) if str(x).strip()]
    city, state, country = split_location(locations[0] if locations else "")
    salary_min, salary_max, salary_currency = _money(item.get("salario"))
    vacancy_id = item.get("id")
    return job(
        "empregare",
        vacancy_id,
        title=item.get("cargo", ""),
        company=item.get("empresa", ""),
        url=f"https://www.empregare.com/v{vacancy_id}",
        work_model=work_model_label(raw=item.get("remoto") or ""),
        city=" · ".join(locations[:3]) or city,
        state=state,
        country=country,
        # Empregare é um portal brasileiro; a ausência de cidade estruturada não
        # transforma a vaga em oportunidade global.
        market="BR",
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        pcd=_bool(item.get("pcd")),
    )


def fetch():
    first, rows = _page(1)
    total_pages = max(1, int(float(first.get("totalPaginas") or 1)))
    page_cap = int(os.environ.get("EMPREGARE_MAX_PAGES") or total_pages)
    total_pages = min(total_pages, max(1, page_cap))
    delay = max(0.0, float(os.environ.get("EMPREGARE_PAGE_DELAY") or 0.5))

    items = list(rows)
    for page in range(2, total_pages + 1):
        time.sleep(delay)
        _, rows = _page(page)
        items.extend(rows)

    unique = {}
    for item in items:
        vacancy_id = item.get("id")
        if vacancy_id is not None:
            unique[str(vacancy_id)] = _normalize(item)
    return list(unique.values())
