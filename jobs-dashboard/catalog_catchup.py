#!/usr/bin/env python3
"""Recover a missed catalog collection without overlapping a live run."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

UTC = timezone.utc
COLLECTION_HOURS_UTC = (11, 14, 18, 23)
DEFAULT_GRACE_MINUTES = 30
DEFAULT_DISPATCH_COOLDOWN_MINUTES = 10
DEFAULT_QUEUE_ALERT_MINUTES = 20
DEFAULT_ACTIVE_ALERT_MINUTES = 120
DELAY_ISSUE_TITLE = "Alerta: atualização do catálogo atrasada"
API_BASE = "https://api.github.com"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def latest_slot(now: datetime) -> datetime:
    """Return the latest daily Brasília collection slot at or before now."""
    current = _as_utc(now)
    candidates = []
    for day_offset in (-1, 0):
        day = current.date() + timedelta(days=day_offset)
        candidates.extend(
            datetime.combine(day, time(hour=hour, tzinfo=UTC))
            for hour in COLLECTION_HOURS_UTC
        )
    return max(slot for slot in candidates if slot <= current)


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _run_time(run: dict) -> datetime | None:
    return _timestamp(run.get("created_at"))

def _run_activity_time(run: dict) -> datetime | None:
    """Use actual start time so a long-queued run can satisfy a later slot."""
    return _timestamp(run.get("run_started_at")) or _run_time(run)


def is_collection_run(run: dict) -> bool:
    event = str(run.get("event") or "")
    if event in {"schedule", "workflow_dispatch"}:
        return True
    if event == "push":
        message = str((run.get("head_commit") or {}).get("message") or "")
        return "[refresh-fit]" in message
    return False


def _recent_dispatch(run, current, cooldown_minutes):
    if str(run.get("event") or "") != "workflow_dispatch":
        return False
    created = _run_time(run)
    if created is None:
        return False
    return created >= current - timedelta(minutes=max(0, int(cooldown_minutes)))


def resume_key_for_slot(runs: list[dict], slot: datetime) -> str:
    """Keep retries of a failed slot attached to its original checkpoints."""
    candidates = [
        run for run in runs
        if (created := _run_activity_time(run)) is not None
        and created >= slot
        and is_collection_run(run)
        and str(run.get("id") or "").strip()
    ]
    if candidates:
        latest = max(candidates, key=lambda run: _run_activity_time(run) or slot)
        return f"run-{latest['id']}"
    return f"slot-{slot.isoformat()}"


def decide(
    now: datetime,
    runs: list[dict],
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
    dispatch_cooldown_minutes: int = DEFAULT_DISPATCH_COOLDOWN_MINUTES,
    queue_alert_minutes: int = DEFAULT_QUEUE_ALERT_MINUTES,
    active_alert_minutes: int = DEFAULT_ACTIVE_ALERT_MINUTES,
) -> dict[str, str | datetime]:
    """Decide whether to wait, alert or safely recover the latest slot."""
    current = _as_utc(now)
    slot = latest_slot(current)
    grace_end = slot + timedelta(minutes=max(0, int(grace_minutes)))
    if current < grace_end:
        return {"action": "grace", "reason": "within_grace", "slot": slot}

    collection_runs = [run for run in runs if is_collection_run(run)]
    active = [
        run for run in collection_runs
        if str(run.get("status") or "") in {"queued", "in_progress"}
    ]
    if active:
        for run in active:
            status = str(run.get("status") or "")
            created = _run_time(run)
            started = _timestamp(run.get("run_started_at")) or created
            reference = created if status == "queued" else started
            threshold = queue_alert_minutes if status == "queued" else active_alert_minutes
            if reference is not None and current - reference >= timedelta(minutes=max(1, int(threshold))):
                reason = "run_queued_too_long" if status == "queued" else "run_running_too_long"
                return {"action": "alert", "reason": reason, "slot": slot}
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

    if any(
        _recent_dispatch(run, current, dispatch_cooldown_minutes)
        for run in slot_runs
    ):
        return {"action": "skip", "reason": "dispatch_cooldown", "slot": slot}

    return {"action": "dispatch", "reason": "slot_missing", "slot": slot}


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "todas-as-vagas-catalog-catchup",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_collection_runs(repository: str, token: str) -> list[dict]:
    """Fetch enough recent pages to make slot detection deterministic.

    The catalog can have many push, validation and recovery runs. Looking only
    at GitHub's first 100 records can hide the successful run for the slot that
    is being checked and cause a duplicate dispatch.
    """
    try:
        max_pages = max(1, min(10, int(os.environ.get("CATCHUP_MAX_RUN_PAGES", "5"))))
    except (TypeError, ValueError):
        max_pages = 5

    runs: list[dict] = []
    now = datetime.now(UTC)
    for page in range(1, max_pages + 1):
        query = urllib.parse.urlencode({
            "branch": "main",
            "per_page": 100,
            "page": page,
        })
        request = urllib.request.Request(
            f"{API_BASE}/repos/{repository}/actions/workflows/pages.yml/runs?{query}",
            headers=_headers(token),
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise RuntimeError(f"não foi possível consultar os runs do catálogo: {error}") from error

        batch = list(payload.get("workflow_runs") or [])
        runs.extend(batch)
        if len(batch) < 100:
            break

        timestamps = [_run_time(run) for run in batch]
        oldest = min((value for value in timestamps if value is not None), default=None)
        if oldest is not None and oldest <= now - timedelta(hours=36):
            break

    return runs


def dispatch_collection(repository: str, token: str, resume_key: str | None = None) -> None:
    payload_data = {"ref": "main"}
    if resume_key:
        payload_data["inputs"] = {"resume_key": str(resume_key)}
    payload = json.dumps(payload_data).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}/repos/{repository}/actions/workflows/pages.yml/dispatches",
        data=payload,
        method="POST",
        headers={**_headers(token), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20):
            return
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise RuntimeError(f"não foi possível disparar o catch-up do catálogo: {error}") from error


def _api_json(repository: str, token: str, path: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{API_BASE}/repos/{repository}/{path}",
        data=data,
        method=method,
        headers={**_headers(token), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"não foi possível registrar alerta do catálogo: {error}") from error


def _latest_relevant_run(runs: list[dict], slot: datetime) -> dict | None:
    candidates = [
        run for run in runs
        if is_collection_run(run)
        and (
            ((started := _run_activity_time(run)) is not None and started >= slot)
            or str(run.get("status") or "") in {"queued", "in_progress"}
        )
    ]
    return max(candidates, key=lambda run: _run_activity_time(run) or slot) if candidates else None


def _incident_body(slot: datetime, reason: str, runs: list[dict], detail: str = "") -> str:
    run = _latest_relevant_run(runs, slot)
    run_url = str((run or {}).get("html_url") or "").strip()
    run_line = f"\nÚltima execução: {run_url}" if run_url else ""
    detail_line = f"\nDetalhe: {detail}" if detail else ""
    return (
        "O monitor detectou que a atualização do catálogo precisa de atenção.\n\n"
        f"- Slot esperado (UTC): {slot.isoformat()}\n"
        f"- Motivo: {reason}"
        f"{run_line}{detail_line}\n\n"
        "O monitor não coleta vagas diretamente. Se não houver escritor ativo, ele despacha "
        "a recuperação para o workflow principal; a publicação continua no runner self-hosted."
    )


def upsert_delay_issue(
    repository: str,
    token: str,
    slot: datetime,
    reason: str,
    runs: list[dict],
    detail: str = "",
) -> dict:
    issues = _api_json(repository, token, "issues?state=open&per_page=100")
    issue = next(
        (
            item for item in issues
            if item.get("title") == DELAY_ISSUE_TITLE
            and "pull_request" not in item
        ),
        None,
    )
    body = _incident_body(slot, reason, runs, detail)
    if issue:
        return _api_json(
            repository, token, f"issues/{issue['number']}", "PATCH", {"body": body}
        )
    return _api_json(
        repository, token, "issues", "POST", {"title": DELAY_ISSUE_TITLE, "body": body}
    )


def resolve_delay_issue(repository: str, token: str, slot: datetime) -> dict | None:
    issues = _api_json(repository, token, "issues?state=open&per_page=100")
    issue = next(
        (
            item for item in issues
            if item.get("title") == DELAY_ISSUE_TITLE
            and "pull_request" not in item
        ),
        None,
    )
    if not issue:
        return None
    body = (
        f"Atualização confirmada para o slot {slot.isoformat()} UTC. "
        "O monitor encerrou este alerta automaticamente."
    )
    return _api_json(
        repository,
        token,
        f"issues/{issue['number']}",
        "PATCH",
        {"state": "closed", "body": body},
    )


def main() -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    if not repository or not token:
        raise SystemExit("GITHUB_REPOSITORY e GH_TOKEN são obrigatórios.")

    def env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)))
        except ValueError:
            return default

    runs = fetch_collection_runs(repository, token)
    result = decide(
        datetime.now(UTC),
        runs,
        env_int("CATCHUP_GRACE_MINUTES", DEFAULT_GRACE_MINUTES),
        env_int("CATCHUP_DISPATCH_COOLDOWN_MINUTES", DEFAULT_DISPATCH_COOLDOWN_MINUTES),
        env_int("CATCHUP_QUEUE_ALERT_MINUTES", DEFAULT_QUEUE_ALERT_MINUTES),
        env_int("CATCHUP_ACTIVE_ALERT_MINUTES", DEFAULT_ACTIVE_ALERT_MINUTES),
    )
    slot = result["slot"]
    print(
        f"CATCHUP_STATUS={result['action']} "
        f"reason={result['reason']} slot_utc={slot.isoformat()}",
        flush=True,
    )

    if result["action"] == "dispatch":
        resume_key = resume_key_for_slot(runs, slot)
        try:
            dispatch_collection(repository, token, resume_key)
        except RuntimeError as error:
            upsert_delay_issue(
                repository, token, slot, "dispatch_failed", runs, str(error)
            )
            raise
        upsert_delay_issue(repository, token, slot, "recovery_dispatched", runs)
        print(
            f"CATCHUP_DISPATCHED=true slot_utc={slot.isoformat()} resume_key={resume_key}",
            flush=True,
        )
    elif result["action"] == "alert":
        upsert_delay_issue(repository, token, slot, str(result["reason"]), runs)
    elif result["reason"] == "slot_succeeded":
        resolve_delay_issue(repository, token, slot)


if __name__ == "__main__":
    main()

