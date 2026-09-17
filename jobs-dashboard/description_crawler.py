# -*- coding: utf-8 -*-
"""Fetch public vacancy details into the private VPS description store.

The crawler is intentionally conservative:
- it reads only the current public catalogue;
- it uses one request at a time by default;
- it obeys robots.txt when the portal publishes a rule;
- it checkpoints every result in SQLite, so an interruption is resumable;
- it never writes descriptions to the repository or the public snapshot.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.robotparser
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import description_store


DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/edsonjunioor32/"
    "todas-as-vagas/public-data/data/vagas.json"
)
DEFAULT_USER_AGENT = "TodasAsVagasDescriptionIndexer/1.0 (+public-job-index)"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_MIN_DESCRIPTION_CHARS = 120
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
JOB_MARKERS = (
    "description", "job-description", "jobdescription", "position-description",
    "vacancy-description", "job-details", "jobdetails", "posting", "opening",
    "responsibilities", "requirements", "content-job",
)


def clean_text(value: object, limit: int = 60000) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


class PageParser(HTMLParser):
    """Capture structured job text while excluding navigation and scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.main_depth = 0
        self.job_depth = 0
        self.body_parts: list[str] = []
        self.main_parts: list[str] = []
        self.job_parts: list[str] = []
        self.meta_description = ""
        self._stack: list[tuple[str, bool, bool, bool]] = []
        self._jsonld_depth = 0
        self._jsonld_parts: list[str] = []
        self.jsonld_payloads: list[object] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(key).lower(): str(value or "") for key, value in attrs}

    def _is_job_container(self, attrs: dict[str, str]) -> bool:
        value = " ".join(
            (attrs.get("id", ""), attrs.get("class", ""), attrs.get("itemprop", ""))
        ).casefold()
        return any(marker in value for marker in JOB_MARKERS)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = self._attrs(attrs)
        if tag == "meta":
            name = (values.get("name") or values.get("property") or "").casefold()
            if name in {"description", "og:description", "twitter:description"}:
                self.meta_description = values.get("content", "")
            return
        if tag == "script":
            script_type = values.get("type", "").casefold()
            self._jsonld_depth = 1 if "ld+json" in script_type else 0
            self._jsonld_parts = []
            self.skip_depth += 1
            self._stack.append((tag, False, False, True))
            return

        is_skip = tag in SKIP_TAGS
        is_main = tag in {"main", "article"}
        is_job = self._is_job_container(values)
        if is_skip:
            self.skip_depth += 1
        if is_main:
            self.main_depth += 1
        if is_job:
            self.job_depth += 1
        if tag not in VOID_TAGS:
            self._stack.append((tag, is_main, is_job, is_skip))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "script":
            if self._jsonld_depth and self._jsonld_parts:
                raw = "".join(self._jsonld_parts).strip()
                try:
                    self.jsonld_payloads.append(json.loads(raw))
                except (ValueError, TypeError):
                    pass
            self._jsonld_depth = 0
            self._jsonld_parts = []
            if self.skip_depth:
                self.skip_depth -= 1
        for index in range(len(self._stack) - 1, -1, -1):
            current, is_main, is_job, is_skip = self._stack[index]
            if current != tag:
                continue
            self._stack.pop(index)
            if is_main:
                self.main_depth = max(0, self.main_depth - 1)
            if is_job:
                self.job_depth = max(0, self.job_depth - 1)
            if is_skip:
                self.skip_depth = max(0, self.skip_depth - 1)
            break

    def handle_data(self, data: str) -> None:
        if self._jsonld_depth:
            self._jsonld_parts.append(data)
            return
        if self.skip_depth:
            return
        value = data.strip()
        if not value:
            return
        self.body_parts.append(value)
        if self.main_depth:
            self.main_parts.append(value)
        if self.job_depth:
            self.job_parts.append(value)


def _description_values(value: object) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        kind = str(value.get("@type") or "").casefold()
        if "jobposting" in kind and value.get("description"):
            values.append(str(value["description"]))
        for key, child in value.items():
            if key.casefold() in {"description", "jobdescription", "job_description"}:
                if isinstance(child, str):
                    values.append(child)
                elif isinstance(child, (dict, list)):
                    values.extend(_description_values(child))
            elif key in {"@graph", "mainEntity", "mainEntityOfPage", "item"}:
                values.extend(_description_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_description_values(child))
    return values


def extract_description(
    payload: bytes,
    content_type: str = "",
    *,
    min_chars: int = DEFAULT_MIN_DESCRIPTION_CHARS,
) -> tuple[str, str]:
    """Return the best description and its extraction source."""
    text = payload.decode("utf-8", "replace")
    if "json" in content_type.casefold() or text.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            data = None
        candidates = [
            clean_text(value)
            for value in _description_values(data)
            if len(clean_text(value)) >= min_chars
        ]
        if candidates:
            return max(candidates, key=len), "json"

    parser = PageParser()
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, TypeError):
        return "", "parse_error"

    structured = [
        clean_text(value)
        for payload_item in parser.jsonld_payloads
        for value in _description_values(payload_item)
    ]
    structured = [value for value in structured if len(value) >= min_chars]
    if structured:
        return max(structured, key=len), "jsonld"

    candidates = [
        ("job_container", clean_text(" ".join(parser.job_parts))),
        ("main", clean_text(" ".join(parser.main_parts))),
        ("body", clean_text(" ".join(parser.body_parts))),
        ("summary", clean_text(parser.meta_description)),
    ]
    for kind, value in candidates:
        if len(value) >= min_chars:
            return value, kind
    return "", "no_description"


class FetchError(RuntimeError):
    def __init__(
        self,
        status: str,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.http_status = http_status
        self.retryable = retryable


def fetch_page(
    url: str,
    *,
    timeout: float,
    user_agent: str,
) -> tuple[bytes, str, int]:
    request = urllib.request.Request(
        url.replace("http://", "https://", 1),
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise FetchError(
                    "response_too_large",
                    f"resposta maior que {MAX_RESPONSE_BYTES} bytes",
                    retryable=False,
                )
            return body, response.headers.get("Content-Type", ""), response.status
    except urllib.error.HTTPError as error:
        retryable = error.code in {408, 425, 429} or error.code >= 500
        raise FetchError(
            f"http_{error.code}",
            f"HTTP {error.code}",
            http_status=error.code,
            retryable=retryable,
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FetchError("network_error", str(error)[:200]) from error


class RobotsCache:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._cache: dict[str, bool] = {}

    def allowed(self, url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._cache:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(f"{origin}/robots.txt")
            try:
                parser.read()
                allowed = parser.can_fetch(self.user_agent, url)
            except (OSError, ValueError, urllib.error.URLError):
                # An unavailable robots file is not treated as a denial.
                allowed = True
            self._cache[origin] = bool(allowed)
        return self._cache[origin]


def _catalog_value(dictionaries: dict, name: str, code: object) -> str:
    values = dictionaries.get(name) or []
    try:
        return str(values[int(code)] or "")
    except (TypeError, ValueError, IndexError):
        return ""


def _column_value(columns: dict, name: str, index: int) -> object:
    values = columns.get(name) or []
    return values[index] if index < len(values) else ""


def decode_catalog(payload: dict) -> list[dict]:
    """Decode the compact public snapshot into crawler manifest rows."""
    dictionaries = payload.get("dict") or {}
    columns = payload.get("jobs") or {}
    count = int(payload.get("count") or 0)
    rows = []
    for index in range(count):
        source = _catalog_value(
            dictionaries, "source", _column_value(columns, "src", index)
        )
        title = str(_column_value(columns, "title", index) or "").strip()
        url = str(_column_value(columns, "url", index) or "").strip()
        if not source or not title or not url:
            continue
        native_id = url
        rows.append(
            {
                "source": source,
                "native_id": native_id,
                "title": title,
                "company": _catalog_value(
                    dictionaries, "company", _column_value(columns, "cmp", index)
                ),
                "url": url.replace("http://", "https://", 1),
            }
        )
    return rows


def load_catalog(path: str, url: str, *, timeout: float, user_agent: str) -> list[dict]:
    if path:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    else:
        body, _, _ = fetch_page(url, timeout=timeout, user_agent=user_agent)
        payload = json.loads(body.decode("utf-8"))
    rows = decode_catalog(payload)
    if not rows:
        raise SystemExit("o catálogo público não contém vagas utilizáveis")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=os.environ.get(
            "PRIVATE_DESCRIPTIONS_DB",
            str(Path.home() / "todas-as-vagas-private" / "descriptions.sqlite3"),
        ),
        help="arquivo SQLite privado; fora do checkout por padrão",
    )
    parser.add_argument("--catalog", default="", help="snapshot local opcional")
    parser.add_argument(
        "--catalog-url",
        default=os.environ.get("DESCRIPTION_CATALOG_URL", DEFAULT_CATALOG_URL),
    )
    parser.add_argument("--source", default="", help="limitar a um portal")
    parser.add_argument("--limit", type=int, default=0, help="máximo de páginas nesta execução")
    parser.add_argument(
        "--max-seconds",
        type=int,
        default=int(os.environ.get("DESCRIPTION_MAX_SECONDS", "21600")),
        help="tempo máximo da execução; 0 significa sem limite",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=float(os.environ.get("DESCRIPTION_MIN_INTERVAL", "1.0")),
        help="intervalo mínimo entre páginas, em segundos",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("DESCRIPTION_PAGE_TIMEOUT", "25")),
    )
    parser.add_argument(
        "--refresh-after-days",
        type=int,
        default=int(os.environ.get("DESCRIPTION_REFRESH_DAYS", "30")),
    )
    parser.add_argument(
        "--min-description-chars",
        type=int,
        default=int(os.environ.get("DESCRIPTION_MIN_CHARS", str(DEFAULT_MIN_DESCRIPTION_CHARS))),
    )
    parser.add_argument("--force", action="store_true", help="reconsultar também descrições já coletadas")
    parser.add_argument("--ignore-robots", action="store_true", help="não recomendado; ignora robots.txt")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.min_interval < 0:
        raise SystemExit("--min-interval não pode ser negativo")
    jobs = load_catalog(
        args.catalog,
        args.catalog_url,
        timeout=args.timeout,
        user_agent=args.user_agent,
    )
    connection = description_store.connect(args.db)
    seen_at, manifest_count = description_store.sync_manifest(connection, jobs=jobs)
    pending = description_store.pending_jobs(
        connection,
        seen_at=seen_at,
        refresh_after_days=max(0, args.refresh_after_days),
        force=args.force,
        source=args.source.strip(),
    )
    robots = RobotsCache(args.user_agent)
    started = time.monotonic()
    last_request = 0.0
    processed = 0
    fetched = 0
    failed = 0
    denied = 0

    for job in pending:
        if args.limit and processed >= args.limit:
            break
        if args.max_seconds and time.monotonic() - started >= args.max_seconds:
            break
        wait = args.min_interval - (time.monotonic() - last_request)
        if last_request and wait > 0:
            time.sleep(wait)
        if not args.ignore_robots and not robots.allowed(job["url"]):
            description_store.record_failure(
                connection,
                job,
                status="robots_denied",
                error="robots.txt não autoriza a coleta",
                permanent=True,
            )
            denied += 1
            processed += 1
            continue
        try:
            body, content_type, http_status = fetch_page(
                job["url"], timeout=args.timeout, user_agent=args.user_agent
            )
            last_request = time.monotonic()
            description, kind = extract_description(
                body, content_type, min_chars=max(1, args.min_description_chars)
            )
            if not description:
                description_store.record_failure(
                    connection,
                    job,
                    status="no_description",
                    error="página sem descrição extraível; pode exigir JavaScript",
                    http_status=http_status,
                    retry_after_seconds=7 * 86400,
                )
                failed += 1
            else:
                description_store.record_success(
                    connection,
                    job,
                    description,
                    content_kind=kind,
                    http_status=http_status,
                    refresh_after_days=max(1, args.refresh_after_days),
                )
                fetched += 1
        except FetchError as error:
            last_request = time.monotonic()
            description_store.record_failure(
                connection,
                job,
                status=error.status,
                error=str(error),
                http_status=error.http_status,
                retry_after_seconds=3600 if error.retryable else 7 * 86400,
                permanent=not error.retryable,
            )
            failed += 1
        except (ValueError, TypeError, UnicodeError) as error:
            description_store.record_failure(
                connection,
                job,
                status="parse_error",
                error=str(error)[:300],
                retry_after_seconds=7 * 86400,
            )
            failed += 1
        processed += 1

    summary = description_store.stats(connection)
    connection.close()
    elapsed = time.monotonic() - started
    print(
        "Manifesto: %d vagas · candidatas: %d · processadas: %d · "
        "descrições: %d · falhas/sem descrição: %d · robots negados: %d · "
        "armazenado: %.1f MB · tempo: %.1fs"
        % (
            manifest_count,
            len(pending),
            processed,
            fetched,
            failed,
            denied,
            summary["bytes"] / (1024 * 1024),
            elapsed,
        )
    )


if __name__ == "__main__":
    main()
