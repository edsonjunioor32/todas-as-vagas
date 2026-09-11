#!/usr/bin/env python3
"""Idempotent external scheduler for the public catalog workflow.

This module uses only Python's standard library so it can run on a small VPS.
It never edits repository data: it only observes pages.yml runs and, when a
slot is missing, requests an explicit workflow_dispatch for main.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time as time_module
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

UTC = timezone.utc
BRASILIA = ZoneInfo("America/Sao_Paulo")
COLLECTION_HOURS_UTC = (11, 14, 18, 23)
DEFAULT_GRACE_MINUTES = 30
DEFAULT_REPOSITORY = "edsonjunioor32/todas-as-vagas"
DEFAULT_STATE_PATH = "~/.local/state/todas-as-vagas/github-scheduler.json"
DEFAULT_LOCK_PATH = "~/.local/state/todas-as-vagas/github-scheduler.lock"
API_BASE = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 20
GET_RETRIES = 3
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def latest_slot(now: datetime) -> datetime:
    """Return the latest configured Brasília slot at or before now."""
    current = _as_utc(now)
    candidates = []
    for day_offset in (-1, 0):
        day = current.date() + timedelta(days=day_offset)
        candidates.extend(
            datetime.combine(day, time(hour=hour, tzinfo=UTC))
            for hour in COLLECTION_HOURS_UTC
        )
    return max(slot for slot in candidates if slot <= current)


def slot_key(slot: datetime) -> str:
    return _as_utc(slot).isoformat()


def _run_time(run: dict) -> datetime | None:
    value = str(run.get("created_at") or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def is_collection_run(run: dict) -> bool:
    event = str(run.get("event") or "")
    if event in {"schedule", "workflow_dispatch"}:
        return True
    if event == "push":
        message = str((run.get("head_commit") or {}).get("message") or "")
        return "[refresh-fit]" in message
    return False


def _state_has_slot(state: dict, key: str) -> bool:
    slots = state.get("dispatched_slots") if isinstance(state, dict) else None
    return isinstance(slots, dict) and key in slots


def decide(
    now: datetime,
    runs: list[dict],
    state: dict,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
) -> dict[str, str | datetime]:
    """Decide whether a dispatch is needed for the current slot.

    A confirmed local dispatch is authoritative for idempotency. A failed
    workflow_dispatch run is not considered successful, so a later invocation
    can retry it unless the local state already records a confirmed POST.
    """
    current = _as_utc(now)
    slot = latest_slot(current)
    key = slot_key(slot)
    grace_end = slot + timedelta(minutes=max(0, int(grace_minutes)))

    if current < grace_end:
        return {"action": "wait", "reason": "within_grace", "slot": slot}
    if _state_has_slot(state, key):
        return {"action": "skip", "reason": "already_dispatched", "slot": slot}

    collection_runs = [run for run in runs if is_collection_run(run)]
    if any(
        str(run.get("status") or "") in {"queued", "in_progress"}
        for run in collection_runs
    ):
        return {"action": "skip", "reason": "collection_active", "slot": slot}

    slot_runs = [
        run
        for run in collection_runs
        if (created := _run_time(run)) is not None and created >= slot
    ]
    if any(
        str(run.get("status") or "") == "completed"
        and str(run.get("conclusion") or "") == "success"
        for run in slot_runs
    ):
        return {"action": "skip", "reason": "slot_succeeded", "slot": slot}

    return {"action": "dispatch", "reason": "slot_missing", "slot": slot}


def load_state(path: str | os.PathLike[str]) -> dict:
    state_path = Path(path).expanduser()
    if not state_path.exists():
        return {}
    try:
        with state_path.open("r", encoding="utf-8") as source:
            state = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"estado do agendador inválido: {error}") from error
    if not isinstance(state, dict):
        raise RuntimeError("estado do agendador deve ser um objeto JSON")
    return state


def save_state(path: str | os.PathLike[str], state: dict) -> None:
    """Write state atomically and keep both directory and file private."""
    state_path = Path(path).expanduser()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(state_path.parent, 0o700)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=state_path.parent,
            prefix=f".{state_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as target:
            temporary_name = target.name
            json.dump(state, target, ensure_ascii=False, sort_keys=True, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, state_path)
        os.chmod(state_path, 0o600)
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


class SchedulerLock:
    """Non-blocking process lock backed by flock on Linux."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path).expanduser()
        self._handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self._handle = self.path.open("a+", encoding="utf-8")
        os.chmod(self.path, 0o600)
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._handle.close()
            self._handle = None
            return False
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> "SchedulerLock":
        if not self.acquire():
            raise RuntimeError("agendador já está em execução")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "todas-as-vagas-vps-scheduler",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _open_get(request: urllib.request.Request):
    for attempt in range(GET_RETRIES):
        try:
            return urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as error:
            if error.code not in RETRYABLE_HTTP_STATUS or attempt == GET_RETRIES - 1:
                raise RuntimeError(
                    f"consulta GitHub falhou com HTTP {error.code}"
                ) from error
        except urllib.error.URLError as error:
            if attempt == GET_RETRIES - 1:
                raise RuntimeError(f"consulta GitHub falhou: {error.reason}") from error
        time_module.sleep(2**attempt)
    raise RuntimeError("consulta GitHub falhou após retries")


def fetch_runs(repository: str, token: str) -> list[dict]:
    if not repository.strip() or not token.strip():
        raise ValueError("repository e token são obrigatórios")
    query = urllib.parse.urlencode({"branch": "main", "per_page": 100})
    request = urllib.request.Request(
        f"{API_BASE}/repos/{repository}/actions/workflows/pages.yml/runs?{query}",
        headers=_headers(token),
    )
    with _open_get(request) as response:
        try:
            payload = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("resposta de runs do GitHub não é JSON válido") from error
    return list(payload.get("workflow_runs") or [])


def dispatch_collection(repository: str, token: str) -> None:
    """Request one dispatch; do not blindly retry an ambiguous POST."""
    if not repository.strip() or not token.strip():
        raise ValueError("repository e token são obrigatórios")
    payload = json.dumps({"ref": "main"}).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}/repos/{repository}/actions/workflows/pages.yml/dispatches",
        data=payload,
        method="POST",
        headers={**_headers(token), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS):
            return
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"dispatch do catálogo falhou com HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"dispatch do catálogo falhou: {error.reason}") from error


def _state_path() -> Path:
    return Path(os.environ.get("GITHUB_SCHEDULER_STATE", DEFAULT_STATE_PATH)).expanduser()


def _lock_path() -> Path:
    return Path(os.environ.get("GITHUB_SCHEDULER_LOCK", DEFAULT_LOCK_PATH)).expanduser()


def _record_dispatch(state: dict, slot: datetime, posted_at: datetime) -> dict:
    updated = dict(state)
    slots = dict(updated.get("dispatched_slots") or {})
    slots[slot_key(slot)] = {"posted_at_utc": _as_utc(posted_at).isoformat()}
    updated["dispatched_slots"] = dict(sorted(slots.items())[-32:])
    return updated


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY).strip()
    token = os.environ.get("GITHUB_SCHEDULER_TOKEN", "").strip()
    if not token:
        print("GITHUB_SCHEDULER_TOKEN é obrigatório.", flush=True)
        return 2

    lock = SchedulerLock(_lock_path())
    if not lock.acquire():
        print("SCHEDULER_STATUS=locked", flush=True)
        return 0

    try:
        now = datetime.now(UTC)
        state = load_state(_state_path())
        runs = fetch_runs(repository, token)
        result = decide(
            now,
            runs,
            state,
            int(os.environ.get("CATCHUP_GRACE_MINUTES", DEFAULT_GRACE_MINUTES)),
        )
        slot = result["slot"]
        assert isinstance(slot, datetime)
        print(
            f"SCHEDULER_STATUS={result['action']} "
            f"reason={result['reason']} "
            f"slot_utc={slot.isoformat()} "
            f"slot_brt={slot.astimezone(BRASILIA).isoformat()}",
            flush=True,
        )
        if result["action"] != "dispatch":
            return 0

        dispatch_collection(repository, token)
        save_state(_state_path(), _record_dispatch(state, slot, now))
        print(
            f"SCHEDULER_DISPATCHED=true slot_utc={slot.isoformat()}",
            flush=True,
        )
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
