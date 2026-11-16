# -*- coding: utf-8 -*-
"""Reaproveita campos de detalhe de vagas já conhecidas entre execuções.

Algumas fontes só entregam modalidade, regime ou local numa requisição por
vaga.  Este cache guarda esses campos — nunca descrições — por fonte e
identificador nativo na tabela ``detail_cache`` do ``jobs.db``, para que a
coleta seguinte peça o detalhe apenas das vagas novas ou cujo dado venceu.

O cache fica inativo até o pipeline chamar ``start``.  Fora dele (testes,
validadores, coletas parciais) ``get`` devolve ``None`` e ``put`` não grava.
``JOBS_DETAIL_CACHE_TTL_DAYS=0`` desliga o reaproveitamento sem deploy.

Cada entrada vale ``TTL × fator``, com fator determinístico entre 0,5 e 1,5
por vaga, para que as renovações se espalhem entre execuções em vez de
vencerem todas juntas.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import threading
import zlib

TTL_ENV = "JOBS_DETAIL_CACHE_TTL_DAYS"
DEFAULT_TTL_DAYS = 3.0
MAX_TTL_DAYS = 30.0
RETENTION_DAYS = 30

_lock = threading.Lock()
_state = {"active": False, "ttl": timedelta(0), "now": None}
_entries = {}
_updates = {}
_stats = {}


def ttl_days():
    """TTL configurado em dias (0 desliga), limitado a ``MAX_TTL_DAYS``."""
    raw = os.environ.get(TTL_ENV, "").strip()
    if not raw:
        return DEFAULT_TTL_DAYS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TTL_DAYS
    if value != value:  # NaN
        return DEFAULT_TTL_DAYS
    return max(0.0, min(value, MAX_TTL_DAYS))


def _spread(source, native_id):
    checksum = zlib.crc32(f"{source}:{native_id}".encode("utf-8"))
    return 0.5 + (checksum % 1000) / 1000


def _parse_time(value):
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _without_text(payload):
    """Remove qualquer campo de descrição: o cache vai para um ramo público."""
    return {
        str(key): value
        for key, value in payload.items()
        if "description" not in str(key).casefold()
    }


def _counter(source):
    return _stats.setdefault(source, Counter())


def is_active():
    return _state["active"]


def start(db_path, now=None):
    """Ativa o cache nesta execução e carrega as entradas ainda válidas.

    Abre o banco somente para leitura; um banco ausente, antigo ou sem a
    tabela resulta num cache vazio, nunca numa falha da coleta.
    """
    with _lock:
        _entries.clear()
        _updates.clear()
        _stats.clear()
        days = ttl_days()
        _state["now"] = now or datetime.now(timezone.utc)
        _state["ttl"] = timedelta(days=days)
        _state["active"] = days > 0
        if not _state["active"] or not db_path or not Path(db_path).is_file():
            return 0
        try:
            uri = Path(db_path).resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            try:
                records = connection.execute(
                    "SELECT source, native_id, payload, fetched_at FROM detail_cache"
                ).fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            return 0
        for source, native_id, payload, fetched_at in records:
            fetched = _parse_time(fetched_at)
            if fetched is None:
                continue
            if _state["now"] - fetched >= _state["ttl"] * _spread(source, native_id):
                continue
            try:
                value = json.loads(payload)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                _entries[(str(source), str(native_id))] = value
        return len(_entries)


def get(source, native_id):
    """Campos guardados de uma vaga, ou ``None`` se ausentes, vencidos ou inativo."""
    if not _state["active"]:
        return None
    key = (str(source), str(native_id))
    with _lock:
        value = _entries.get(key)
        _counter(key[0])["hits" if value is not None else "misses"] += 1
    return dict(value) if value is not None else None


def put(source, native_id, payload):
    """Guarda campos recém-buscados de uma vaga (sem descrições)."""
    if not _state["active"] or not isinstance(payload, dict):
        return
    cleaned = _without_text(payload)
    if not cleaned:
        return
    key = (str(source), str(native_id))
    with _lock:
        _entries[key] = cleaned
        _updates[key] = cleaned
        _counter(key[0])["stored"] += 1


def persist(connection):
    """Grava as entradas novas no banco aberto pelo pipeline e poda as antigas."""
    if not _state["active"]:
        return 0
    fetched_at = _state["now"].isoformat()
    with _lock:
        updates = [
            (source, native_id, json.dumps(payload, ensure_ascii=False, sort_keys=True),
             fetched_at)
            for (source, native_id), payload in _updates.items()
        ]
    connection.executemany(
        "INSERT OR REPLACE INTO detail_cache (source, native_id, payload, fetched_at) "
        "VALUES (?, ?, ?, ?)",
        updates,
    )
    cutoff = (_state["now"] - timedelta(days=RETENTION_DAYS)).isoformat()
    connection.execute("DELETE FROM detail_cache WHERE fetched_at < ?", (cutoff,))
    connection.commit()
    return len(updates)


def summary():
    """``{fonte: {"hits": n, "misses": n, "stored": n}}`` desta execução."""
    with _lock:
        return {source: dict(counter) for source, counter in sorted(_stats.items())}


def stop():
    """Desativa o cache e descarta o estado em memória."""
    with _lock:
        _state["active"] = False
        _entries.clear()
        _updates.clear()
        _stats.clear()
