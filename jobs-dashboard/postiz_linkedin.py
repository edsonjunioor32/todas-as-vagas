"""Create one idempotent daily vacancy digest for a LinkedIn Page via Postiz."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


BRASILIA = ZoneInfo("America/Sao_Paulo")
DEFAULT_SITE_URL = "https://edsonjunioor32.github.io/todas-as-vagas/"
DEFAULT_MAX_ITEMS = 5
MAX_POST_CHARS = 2_800
STATE_RETENTION_DAYS = 90


class PostizError(RuntimeError):
    """A safe-to-display error from configuration or the Postiz API."""


def _parse_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _lookup_dictionary(snapshot, index_key, dictionary_key, row_index):
    columns = snapshot.get("jobs") or {}
    indexes = columns.get(index_key) or []
    if row_index >= len(indexes):
        return ""
    value = indexes[row_index]
    if isinstance(value, bool) or not isinstance(value, int):
        return ""
    options = (snapshot.get("dict") or {}).get(dictionary_key) or []
    return options[value] if 0 <= value < len(options) else ""


def _column_value(columns, name, row_index):
    values = columns.get(name) or []
    if row_index >= len(values):
        return ""
    value = values[row_index]
    return value if isinstance(value, str) else ""


def decode_snapshot(snapshot):
    """Expand the compact public snapshot's column arrays into job records."""
    columns = snapshot.get("jobs")
    if not isinstance(columns, dict):
        raise PostizError("O snapshot público não contém a lista compacta de vagas esperada.")
    titles = columns.get("title")
    urls = columns.get("url")
    if not isinstance(titles, list) or not isinstance(urls, list) or len(titles) != len(urls):
        raise PostizError("O snapshot público está incompleto ou inconsistente.")

    index_fields = {
        "source": ("src", "source"),
        "company": ("cmp", "company"),
        "area": ("area", "area"),
        "seniority": ("sen", "seniority"),
        "work_model": ("wm", "work_model"),
        "market": ("mk", "market"),
        "country": ("co", "country"),
    }
    rows = []
    for index, title in enumerate(titles):
        url = urls[index]
        if not isinstance(title, str) or not title.strip() or not isinstance(url, str):
            continue
        row = {
            "title": title.strip(),
            "city": _column_value(columns, "city", index),
            "published_date": _column_value(columns, "pub", index),
            "seen_date": _column_value(columns, "seen", index),
            "expires_date": _column_value(columns, "exp", index),
            "url": url.strip(),
        }
        for field, (index_key, dictionary_key) in index_fields.items():
            row[field] = _lookup_dictionary(snapshot, index_key, dictionary_key, index)
        rows.append(row)
    return rows


def canonical_job_key(url):
    """Normalize tracking noise while retaining query parameters that identify a job."""
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    query = [
        (key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid"}
    ]
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(("https", parsed.netloc.casefold(), path, urllib.parse.urlencode(query), ""))


def select_vacancies(snapshot, posted_keys=(), max_items=DEFAULT_MAX_ITEMS, today=None):
    """Pick distinct jobs seen in today's successful collection, newest first."""
    today = today or _parse_date(snapshot.get("generated_date"))
    if not isinstance(today, date):
        raise PostizError("A data de geração do snapshot está ausente ou inválida.")
    cutoff = _parse_date(snapshot.get("publication_cutoff"))
    if cutoff is None:
        try:
            age_days = max(1, min(120, int(snapshot.get("max_age_days") or 63)))
        except (TypeError, ValueError):
            age_days = 63
        cutoff = today - timedelta(days=age_days)

    already_posted = set(posted_keys)
    candidates = []
    seen_keys = set()
    for row in decode_snapshot(snapshot):
        if _parse_date(row["seen_date"]) != today:
            continue
        expires = _parse_date(row["expires_date"])
        if expires and expires < today:
            continue
        published = _parse_date(row["published_date"])
        if published and (published < cutoff or published > today):
            continue
        key = canonical_job_key(row["url"])
        if not key or key in already_posted or key in seen_keys:
            continue
        row["job_key"] = key
        row["sort_date"] = published or today
        seen_keys.add(key)
        candidates.append(row)

    candidates.sort(
        key=lambda row: (row["sort_date"], row["company"].casefold(), row["title"].casefold()),
        reverse=True,
    )
    selected = []
    selected_keys = set()
    selected_companies = set()
    selected_sources = set()
    limit = max(1, min(10, int(max_items)))
    for distinct_company in (True, False):
        for distinct_source in (True, False):
            for row in candidates:
                if len(selected) >= limit:
                    return selected
                if row["job_key"] in selected_keys:
                    continue
                company = row["company"].strip().casefold()
                source = row["source"].strip().casefold()
                if distinct_company and company and company in selected_companies:
                    continue
                if distinct_source and source and source in selected_sources:
                    continue
                selected.append(row)
                selected_keys.add(row["job_key"])
                if company:
                    selected_companies.add(company)
                if source:
                    selected_sources.add(source)
    return selected


def _daily_site_url(site_url, day):
    parsed = urllib.parse.urlsplit(site_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend([
        ("utm_source", "linkedin"),
        ("utm_medium", "social"),
        ("utm_campaign", f"todas-as-vagas-{day:%Y%m%d}"),
    ])
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment))


def _friendly_work_model(value):
    return {
        "remote": "Remoto",
        "fully remote": "Remoto",
        "hybrid": "Híbrido",
        "on-site": "Presencial",
        "onsite": "Presencial",
    }.get(str(value or "").strip().casefold(), str(value or "").strip())


def compose_digest(vacancies, day, site_url=DEFAULT_SITE_URL):
    marker_url = _daily_site_url(site_url, day)
    heading = f"💼 Oportunidades coletadas hoje — {day:%d/%m/%Y}\n\n"
    footer = f"\n🔎 Veja e filtre todas as vagas: {marker_url}\n\n#Vagas #Emprego #Carreira"
    blocks = []
    for row in vacancies:
        company = row.get("company", "").strip() or "Empresa não informada"
        location = row.get("city", "").strip()
        model = _friendly_work_model(row.get("work_model"))
        details = [part for part in (company, location, model) if part]
        block = f"🔹 {row['title'].strip()[:180]}\n🏢 {' · '.join(details)}\n🔗 {row['url'].strip()}"
        candidate = heading + "\n\n".join([*blocks, block]) + footer
        if len(candidate) <= MAX_POST_CHARS:
            blocks.append(block)
    if not blocks:
        return ""
    return heading + "\n\n".join(blocks) + footer


def build_post_payload(integration_id, content, now=None):
    now = now or datetime.now(timezone.utc)
    return {
        "type": "now",
        "date": now.astimezone(timezone.utc).isoformat(),
        "shortLink": False,
        "tags": [],
        "posts": [{
            "integration": {"id": integration_id},
            "value": [{"content": content, "image": []}],
            "settings": {"__type": "linkedin-page"},
        }],
    }


def _utc_day_range(day):
    start = datetime.combine(day, time.min, BRASILIA).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, BRASILIA).astimezone(timezone.utc)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


class PostizClient:
    def __init__(self, base_url, api_key, timeout=25):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PostizError("Configure POSTIZ_API_BASE_URL com a URL completa da API do Postiz.")
        if not self.api_key:
            raise PostizError("O secret POSTIZ_API_KEY não está configurado.")

    def request(self, method, path, payload=None):
        url = f"{self.base_url}/{path.lstrip('/')}"
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": self.api_key, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read(500).decode("utf-8", errors="replace")
            raise PostizError(f"Postiz respondeu HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise PostizError(f"Não foi possível alcançar o Postiz: {error}") from error
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PostizError("O Postiz retornou uma resposta que não é JSON válido.") from error

    def already_has_marker(self, marker, day):
        start, end = _utc_day_range(day)
        query = urllib.parse.urlencode({"startDate": start, "endDate": end})
        result = self.request("GET", f"posts?{query}")
        return marker in json.dumps(result, ensure_ascii=False)


def _default_state_path():
    configured = os.environ.get("POSTIZ_STATE_FILE")
    if configured:
        return Path(configured)
    return Path.home() / ".local" / "state" / "todas-as-vagas" / "postiz-linkedin.json"


def _load_state(path):
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": 1, "posted_days": {}, "posted_vacancies": {}}
    except (OSError, json.JSONDecodeError) as error:
        raise PostizError("O arquivo persistente de controle do LinkedIn está ilegível; postagem cancelada para evitar duplicidade.") from error
    if not isinstance(state, dict) or not isinstance(state.get("posted_days", {}), dict) or not isinstance(state.get("posted_vacancies", {}), dict):
        raise PostizError("O arquivo de controle do LinkedIn tem estrutura inválida; postagem cancelada para evitar duplicidade.")
    return state


def _save_state(path, state, day, marker, vacancies):
    oldest = day - timedelta(days=STATE_RETENTION_DAYS)
    state["posted_vacancies"] = {
        key: value for key, value in state.setdefault("posted_vacancies", {}).items()
        if (_parse_date(value) or date.min) >= oldest
    }
    state["posted_days"] = {
        key: value for key, value in state.setdefault("posted_days", {}).items()
        if (_parse_date(key) or date.min) >= oldest
    }
    state["posted_days"][day.isoformat()] = marker
    for row in vacancies:
        state["posted_vacancies"][row["job_key"]] = day.isoformat()
    state["schema_version"] = 1
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish(snapshot, env=None, state_path=None, dry_run=False, today=None, now=None):
    env = os.environ if env is None else env
    today = today or _parse_date(snapshot.get("generated_date"))
    if not isinstance(today, date):
        raise PostizError("A data de geração do snapshot está ausente ou inválida.")
    site_url = env.get("POSTIZ_SITE_URL", DEFAULT_SITE_URL)
    state_path = Path(state_path or _default_state_path())
    state = _load_state(state_path)
    if not dry_run and today.isoformat() in state.get("posted_days", {}):
        return {"status": "skipped", "reason": "already_posted_today", "count": 0}

    vacancies = select_vacancies(snapshot, state.get("posted_vacancies", {}).keys(), today=today)
    content = compose_digest(vacancies, today, site_url=site_url)
    if not content:
        return {"status": "skipped", "reason": "no_eligible_vacancies", "count": 0}
    marker = f"todas-as-vagas-{today:%Y%m%d}"
    if dry_run:
        return {"status": "preview", "count": len(vacancies), "characters": len(content), "content": content}

    api = PostizClient(env.get("POSTIZ_API_BASE_URL"), env.get("POSTIZ_API_KEY"))
    integration_id = str(env.get("POSTIZ_LINKEDIN_INTEGRATION_ID") or "").strip()
    if not integration_id:
        raise PostizError("O secret POSTIZ_LINKEDIN_INTEGRATION_ID não está configurado.")
    if api.already_has_marker(marker, today):
        _save_state(state_path, state, today, marker, vacancies)
        return {"status": "skipped", "reason": "marker_found_in_postiz", "count": 0}

    payload = build_post_payload(integration_id, content, now=now)
    api.request("POST", "posts", payload)
    _save_state(state_path, state, today, marker, vacancies)
    return {"status": "posted", "count": len(vacancies), "characters": len(content)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Arquivo compactado data/vagas.json")
    parser.add_argument("--dry-run", action="store_true", help="Exibe o rascunho sem chamar o Postiz")
    args = parser.parse_args(argv)
    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        result = publish(snapshot, dry_run=args.dry_run)
    except (OSError, json.JSONDecodeError, PostizError) as error:
        print(f"Erro na publicação LinkedIn/Postiz: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
