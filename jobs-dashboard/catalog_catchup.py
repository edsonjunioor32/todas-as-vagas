#!/usr/bin/env python3
"""Monitor scheduled catalog publication and recover missed slots safely.

The hosted monitor only reads GitHub run state, maintains one idempotent issue,
and dispatches the existing self-hosted publisher. It never collects or writes
catalog data itself.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import os
import urllib.error
import urllib.parse
import urllib.request

UTC = timezone.utc
DAILY_SLOTS_UTC = ((11, 7), (14, 7), (18, 7), (23, 7))
WEEKLY_SLOT_UTC = (7, 47)  # Sunday Greenhouse + catalog refresh.
DEFAULT_GRACE_MINUTES = 30
DEFAULT_DISPATCH_COOLDOWN_MINUTES = 10
DEFAULT_QUEUE_GRACE_MINUTES = 15
DEFAULT_MAX_ACTIVE_MINUTES = 120
API_BASE = "https://api.github.com"
INCIDENT_LABEL = "catalog-schedule-delay"
INCIDENT_TITLE = "Atraso na atualização programada do catálogo"
INCIDENT_MARKER = "<!-- catalog-catchup-delay -->"


class GitHubAPIError(RuntimeError):
    """GitHub API failure that keeps response details and credentials private."""

    def __init__(self, status: int):
        self.status = status
        super().__init__(f"GitHub API respondeu HTTP {status}")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def _slots_for_day(day: date) -> list[datetime]:
    slots = [
        datetime.combine(day, time(hour=hour, minute=minute, tzinfo=UTC))
        for hour, minute in DAILY_SLOTS_UTC
    ]
    if day.weekday() == 6:
        slots.append(datetime.combine(
            day, time(hour=WEEKLY_SLOT_UTC[0], minute=WEEKLY_SLOT_UTC[1], tzinfo=UTC)
        ))
    return slots


def latest_slot(now: datetime) -> datetime:
    """Return the latest scheduled catalog slot at or before now."""
    current = _as_utc(now)
    candidates = []
    for day_offset in (-1, 0):
        day = current.date() + timedelta(days=day_offset)
        candidates.extend(_slots_for_day(day))
    return max(slot for slot in candidates if slot <= current)


def next_slot(slot: datetime) -> datetime:
    """Return the first scheduled slot strictly after slot."""
    current = _as_utc(slot)
    candidates = []
    for day_offset in range(0, 8):
        day = current.date() + timedelta(days=day_offset)
        candidates.extend(_slots_for_day(day))
    return min(candidate for candidate in candidates if candidate > current)


def _run_time(run: dict) -> datetime | None:
    value = str(run.get("created_at") or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def is_collection_run(run: dict) -> bool:
    event = str(run.get("event") or "")
    if event in {"schedule", "workflow_dispatch"}:
        return True
    if event == "push":
        message = str((run.get("head_commit") or {}).get("message") or "")
        return "[refresh-fit]" in message
    return False


def _in_slot(run: dict, slot: datetime) -> bool:
    created = _run_time(run)
    return created is not None and slot <= created < next_slot(slot)


def _recent_dispatch(run: dict, current: datetime, cooldown_minutes: int) -> bool:
    if str(run.get("event") or "") != "workflow_dispatch":
        return False
    created = _run_time(run)
    if created is None:
        return False
    return created >= current - timedelta(minutes=max(0, int(cooldown_minutes)))


def resume_key_for_slot(runs: list[dict], slot: datetime) -> str:
    """Reuse checkpoints from a failed run in this slot; otherwise use its key."""
    candidates = [
        run for run in runs
        if _in_slot(run, slot)
        and is_collection_run(run)
        and str(run.get("id") or "").strip()
    ]
    if candidates:
        latest = max(candidates, key=lambda run: _run_time(run) or slot)
        return f"run-{latest['id']}"
    return f"slot-{slot.isoformat()}"


def _oldest_by_status(runs: list[dict], statuses: str | set[str]) -> dict | None:
    expected = {statuses} if isinstance(statuses, str) else statuses
    matches = [
        run for run in runs
        if str(run.get("status") or "") in expected and _run_time(run) is not None
    ]
    return min(matches, key=lambda run: _run_time(run)) if matches else None


def decide(
    now: datetime,
    runs: list[dict],
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
    dispatch_cooldown_minutes: int = DEFAULT_DISPATCH_COOLDOWN_MINUTES,
    queue_grace_minutes: int = DEFAULT_QUEUE_GRACE_MINUTES,
    max_active_minutes: int = DEFAULT_MAX_ACTIVE_MINUTES,
) -> dict[str, object]:
    """Choose wait, alert, or dispatch without duplicating an active writer."""
    current = _as_utc(now)
    slot = latest_slot(current)
    grace_end = slot + timedelta(minutes=max(0, int(grace_minutes)))
    collection_runs = [run for run in runs if is_collection_run(run)]
    slot_runs = [
        run for run in collection_runs
        if _in_slot(run, slot)
    ]

    if any(
        str(run.get("status") or "") == "completed"
        and str(run.get("conclusion") or "") == "success"
        for run in slot_runs
    ):
        return {"action": "skip", "reason": "slot_succeeded", "slot": slot}

    queued = _oldest_by_status(collection_runs, {"queued", "waiting", "pending", "requested"})
    if queued:
        created = _run_time(queued)
        assert created is not None
        if current - created >= timedelta(minutes=max(0, int(queue_grace_minutes))):
            return {
                "action": "alert",
                "reason": "queued_too_long",
                "slot": slot,
                "run": queued,
            }
        return {
            "action": "skip",
            "reason": "collection_queued",
            "slot": slot,
            "run": queued,
        }

    running = _oldest_by_status(collection_runs, "in_progress")
    if running:
        created = _run_time(running)
        assert created is not None
        if current - created >= timedelta(minutes=max(0, int(max_active_minutes))):
            return {
                "action": "alert",
                "reason": "run_too_long",
                "slot": slot,
                "run": running,
            }
        return {
            "action": "skip",
            "reason": "collection_active",
            "slot": slot,
            "run": running,
        }

    if any(
        _recent_dispatch(run, current, dispatch_cooldown_minutes)
        for run in slot_runs
    ):
        return {"action": "skip", "reason": "dispatch_cooldown", "slot": slot}

    failed = [
        run for run in slot_runs
        if str(run.get("status") or "") == "completed"
        and str(run.get("conclusion") or "") != "success"
    ]
    latest_failed = max(failed, key=lambda run: _run_time(run) or slot) if failed else None
    if latest_failed:
        return {
            "action": "dispatch",
            "reason": "slot_failed",
            "slot": slot,
            "run": latest_failed,
        }

    if current < grace_end:
        return {"action": "grace", "reason": "within_grace", "slot": slot}

    return {"action": "dispatch", "reason": "slot_missing", "slot": slot}


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "todas-as-vagas-catalog-catchup",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _api_json(method: str, path: str, token: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = _headers(token)
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{API_BASE}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        raise GitHubAPIError(error.code) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"não foi possível acessar a API do GitHub: {error.reason}") from error
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError("GitHub API retornou JSON inválido") from error


def fetch_collection_runs(repository: str, token: str) -> list[dict]:
    """Fetch recent workflow runs so slot detection is not limited to page one."""
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
        payload = _api_json(
            "GET",
            f"/repos/{repository}/actions/workflows/pages.yml/runs?{query}",
            token,
        )
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
    payload = {"ref": "main"}
    if resume_key:
        payload["inputs"] = {"resume_key": str(resume_key)}
    request = urllib.request.Request(
        f"{API_BASE}/repos/{repository}/actions/workflows/pages.yml/dispatches",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={**_headers(token), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20):
            return
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise RuntimeError(f"não foi possível despachar a atualização do catálogo: {error}") from error


def _ensure_incident_label(repository: str, token: str) -> None:
    encoded_label = urllib.parse.quote(INCIDENT_LABEL, safe="")
    try:
        _api_json("GET", f"/repos/{repository}/labels/{encoded_label}", token)
        return
    except GitHubAPIError as error:
        if error.status != 404:
            raise
    try:
        _api_json(
            "POST",
            f"/repos/{repository}/labels",
            token,
            {
                "name": INCIDENT_LABEL,
                "color": "d93f0b",
                "description": "Atraso monitorado na atualização do catálogo",
            },
        )
    except GitHubAPIError as error:
        # A concurrent monitor may have created the same label first.
        if error.status != 422:
            raise


def _open_incidents(repository: str, token: str) -> list[dict]:
    query = urllib.parse.urlencode({
        "state": "open",
        "labels": INCIDENT_LABEL,
        "per_page": 100,
    })
    try:
        payload = _api_json("GET", f"/repos/{repository}/issues?{query}", token)
    except GitHubAPIError as error:
        if error.status == 404:
            return []
        raise
    return [
        issue for issue in payload
        if "pull_request" not in issue
        and INCIDENT_MARKER in str(issue.get("body") or "")
    ]


def _incident_body(slot: datetime, reason: str, run: dict | None) -> str:
    run_link = ""
    if run:
        run_id = str(run.get("id") or "desconhecido")
        url = str(run.get("html_url") or "")
        run_link = f"- Execução observada: [#{run_id}]({url})\n" if url else f"- Execução observada: #{run_id}\n"
    return (
        f"{INCIDENT_MARKER}\n"
        "## Atualização do catálogo atrasada\n\n"
        f"- Slot previsto (UTC): `{slot.isoformat()}`\n"
        f"- Situação: `{reason}`\n"
        f"{run_link}"
        "- O monitor não coleta nem publica dados; a publicação continua no runner self-hosted.\n"
        "- O aviso será encerrado após uma execução de catálogo confirmada com sucesso.\n"
    )


def upsert_delay_issue(
    repository: str,
    token: str,
    slot: datetime,
    reason: str,
    run: dict | None = None,
) -> dict:
    """Create or update one open delay issue, identified by a stable label/marker."""
    _ensure_incident_label(repository, token)
    issues = _open_incidents(repository, token)
    body = _incident_body(slot, reason, run)
    if issues:
        issue = min(issues, key=lambda item: int(item.get("number") or 0))
        return _api_json(
            "PATCH",
            f"/repos/{repository}/issues/{issue['number']}",
            token,
            {"body": body},
        )
    return _api_json(
        "POST",
        f"/repos/{repository}/issues",
        token,
        {"title": INCIDENT_TITLE, "body": body, "labels": [INCIDENT_LABEL]},
    )


def close_delay_issues(repository: str, token: str) -> int:
    """Close the open delay incident after the current slot succeeds."""
    issues = _open_incidents(repository, token)
    for issue in issues:
        _api_json(
            "PATCH",
            f"/repos/{repository}/issues/{issue['number']}",
            token,
            {"state": "closed"},
        )
    return len(issues)


def main() -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    if not repository or not token:
        raise SystemExit("GITHUB_REPOSITORY e GH_TOKEN são obrigatórios.")

    def env_minutes(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)))
        except ValueError:
            return default

    runs = fetch_collection_runs(repository, token)
    result = decide(
        datetime.now(UTC),
        runs,
        grace_minutes=env_minutes("CATCHUP_GRACE_MINUTES", DEFAULT_GRACE_MINUTES),
        dispatch_cooldown_minutes=env_minutes(
            "CATCHUP_DISPATCH_COOLDOWN_MINUTES", DEFAULT_DISPATCH_COOLDOWN_MINUTES
        ),
        queue_grace_minutes=env_minutes(
            "CATCHUP_QUEUE_GRACE_MINUTES", DEFAULT_QUEUE_GRACE_MINUTES
        ),
        max_active_minutes=env_minutes(
            "CATCHUP_MAX_ACTIVE_MINUTES", DEFAULT_MAX_ACTIVE_MINUTES
        ),
    )
    slot = result["slot"]
    run = result.get("run")
    print(
        f"CATCHUP_STATUS={result['action']} reason={result['reason']} "
        f"slot_utc={slot.isoformat()}",
        flush=True,
    )

    if result["action"] == "grace":
        return
    if result["reason"] == "slot_succeeded":
        closed = close_delay_issues(repository, token)
        print(f"CATCHUP_INCIDENTS_CLOSED={closed}", flush=True)
        return
    if result["action"] == "skip":
        return

    issue_error = None
    try:
        issue = upsert_delay_issue(
            repository, token, slot, str(result["reason"]), run if isinstance(run, dict) else None
        )
        print(f"CATCHUP_INCIDENT_URL={issue.get('html_url', '')}", flush=True)
    except (GitHubAPIError, RuntimeError) as error:
        issue_error = error
        print(
            f"CATCHUP_INCIDENT_ERROR={getattr(error, 'status', 'network')}",
            flush=True,
        )

    if result["action"] == "alert":
        if issue_error:
            raise RuntimeError("não foi possível registrar o incidente de atraso") from issue_error
        return

    resume_key = resume_key_for_slot(runs, slot)
    dispatch_collection(repository, token, resume_key)
    print(
        f"CATCHUP_DISPATCHED=true slot_utc={slot.isoformat()} resume_key={resume_key}",
        flush=True,
    )
    if issue_error:
        raise RuntimeError(
            "a recuperação foi despachada, mas o incidente não pôde ser registrado"
        ) from issue_error


if __name__ == "__main__":
    main()
