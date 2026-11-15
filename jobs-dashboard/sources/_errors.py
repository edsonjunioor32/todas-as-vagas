# -*- coding: utf-8 -*-
"""Taxonomia de falhas das fontes de vagas.

As classes ``Source*`` herdam de ``RuntimeError`` para continuar compatíveis
com qualquer código que já capture ``RuntimeError``.  ``classify_error``
atribui uma categoria a qualquer exceção — tipada ou não — percorrendo a
cadeia ``__cause__``/``__context__``, para que o resumo do run diga *por que*
uma fonte falhou, e não apenas *que* falhou:

- ``bloqueio``: o portal recusou o coletor (401/403/407/429/451, desafio
  anti-robô).  Ajustar ritmo, cabeçalhos ou caminho alternativo.
- ``indisponivel``: o portal ou a rede falharam (5xx, DNS, conexão, TLS).
  Normalmente passa sozinho.
- ``timeout``: a resposta não chegou no prazo.
- ``formato``: a resposta não tem o formato esperado (JSON inválido, campo
  ausente, endpoint 404/410).  Quase sempre exige ajuste no adaptador.
- ``linhas_invalidas`` e ``vazio_inesperado``: o adaptador respondeu, mas
  com linhas malformadas ou sem vagas numa fonte que nunca fica vazia.
- ``outro``: sem evidência suficiente para classificar.
"""
import http.client
import json
import re
import socket
import ssl
import urllib.error

BLOCKED = "bloqueio"
UNAVAILABLE = "indisponivel"
TIMEOUT = "timeout"
FORMAT = "formato"
INVALID_ROWS = "linhas_invalidas"
UNEXPECTED_EMPTY = "vazio_inesperado"
OTHER = "outro"

LABELS = {
    BLOCKED: "bloqueio",
    UNAVAILABLE: "indisponibilidade",
    TIMEOUT: "tempo esgotado",
    FORMAT: "formato inesperado",
    INVALID_ROWS: "linhas inválidas",
    UNEXPECTED_EMPTY: "vazio inesperado",
    OTHER: "outro",
}

BLOCKED_HTTP_CODES = frozenset({401, 403, 407, 429, 451})
CHANGED_HTTP_CODES = frozenset({404, 410})

_HTTP_CODE_IN_MESSAGE = re.compile(r"\bHTTP(?:\s+Error)?\s*(\d{3})\b", re.IGNORECASE)
_BLOCK_MARKERS = ("cloudflare", "captcha", "just a moment", "error 1015", "access denied")


class SourceError(RuntimeError):
    """Falha de fonte sem categoria específica."""

    category = OTHER


class SourceBlocked(SourceError):
    category = BLOCKED


class SourceUnavailable(SourceError):
    category = UNAVAILABLE


class SourceTimeout(SourceUnavailable):
    category = TIMEOUT


class SourceFormatError(SourceError):
    category = FORMAT


_CLASS_BY_CATEGORY = {
    BLOCKED: SourceBlocked,
    UNAVAILABLE: SourceUnavailable,
    TIMEOUT: SourceTimeout,
    FORMAT: SourceFormatError,
}


def _category_for_http_code(code):
    if code in BLOCKED_HTTP_CODES:
        return BLOCKED
    if code in CHANGED_HTTP_CODES:
        return FORMAT
    if 500 <= code <= 599:
        return UNAVAILABLE
    return OTHER


def _direct_category(error):
    """Categoria de uma única exceção, sem olhar a cadeia."""
    if isinstance(error, SourceError) and error.category != OTHER:
        return error.category
    if isinstance(error, urllib.error.HTTPError):
        return _category_for_http_code(error.code)
    if isinstance(error, urllib.error.URLError):
        reason = getattr(error, "reason", None)
        if isinstance(reason, BaseException):
            nested = _direct_category(reason)
            if nested != OTHER:
                return nested
        return UNAVAILABLE
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.casefold():
        return TIMEOUT
    if isinstance(error, (ConnectionError, socket.gaierror, ssl.SSLError,
                          http.client.HTTPException)):
        return UNAVAILABLE
    if isinstance(error, (json.JSONDecodeError, KeyError, IndexError,
                          TypeError, AttributeError, ValueError)):
        return FORMAT
    message = str(error).casefold()
    if any(marker in message for marker in _BLOCK_MARKERS):
        return BLOCKED
    match = _HTTP_CODE_IN_MESSAGE.search(str(error))
    if match:
        return _category_for_http_code(int(match.group(1)))
    return OTHER


def classify_error(error):
    """Categoria de uma falha, seguindo ``__cause__``/``__context__``."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        category = _direct_category(current)
        if category != OTHER:
            return category
        current = current.__cause__ or current.__context__
    return OTHER


def exhausted(message, last_error):
    """Exceção tipada para retentativas esgotadas, preservando a mensagem."""
    cls = _CLASS_BY_CATEGORY.get(classify_error(last_error), SourceError)
    return cls(message)


def label(category):
    """Rótulo legível de uma categoria (ou a própria chave, se desconhecida)."""
    return LABELS.get(category, category or "")
