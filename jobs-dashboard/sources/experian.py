# -*- coding: utf-8 -*-
"""Public Brazil job listings from Experian Careers."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

from ._common import job, work_model_label
from ._http import get_text
from ._html import PublicPageParser, job_posting


BASE_URL = "https://jobs.experian.com"
LIST_URL = (
    "https://jobs.experian.com/jobs?options=765&page={page}"
    "&ln=&la=0&lo=0&lr=48&li="
)
MAX_PAGES = 20
ROLE_TYPE_RE = re.compile(
    r"(?:Role\s+Type|opt-Role\s+Type__)\s*(?:__\s*)?(?:[:\-]\s*)?"
    r"(Home|Remote|Hybrid|On[- ]?site|Onsite|Presencial|"
    r"Remot[oa]|H[ií]brido|H[ií]brida)\b",
    re.I,
)
ROLE_MARKER_RE = re.compile(r"#LI-(HYBRID|REMOTE|HOME|ON[-_]?SITE)\b", re.I)


def _role_type_label(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    if text in {"home", "remote", "remoto", "remota", "home office", "telecommute"}:
        return "remote"
    if text in {"hybrid", "h\u00edbrido", "h\u00edbrida"}:
        return "hybrid"
    if text in {"on-site", "on site", "onsite", "presencial"}:
        return "on-site"
    return work_model_label(raw=text)


def _parse_work_model(markup):
    """Read Experian's Role Type field before using its legacy hash marker."""
    parser = PublicPageParser()
    parser.feed(markup or "")
    posting = job_posting(markup or "")
    for key in ("roleType", "role_type", "workModel", "work_model"):
        value = _role_type_label(posting.get(key))
        if value:
            return value

    text = parser.visible_text
    match = ROLE_TYPE_RE.search(text)
    if match:
        value = _role_type_label(match.group(1))
        if value:
            return value

    for index, token in enumerate(parser.parts):
        normalized = re.sub(
            r"^__vacancyopjusttionswidget\.", "", token, flags=re.I
        ).strip("_ :").casefold()
        if normalized not in {"opt-role type", "role type"}:
            continue
        for candidate in parser.parts[index + 1:index + 4]:
            value = _role_type_label(candidate)
            if value:
                return value

    marker = ROLE_MARKER_RE.search(text)
    if marker:
        return _role_type_label(marker.group(1))
    return ""


def _fetch_detail_model(url):
    markup = get_text(url, timeout=35, retries=2)
    return _parse_work_model(markup)


class ResultsParser(HTMLParser):
    """Collect title and canonical URL from the public Brazil results."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._seen = set()
        self._href = ""
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if self._href or tag != "a":
            return
        href = dict(attrs).get("href", "")
        if not urlparse(href).path.startswith("/job/"):
            return
        self._href = urljoin(BASE_URL, href)
        self._parts = []

    def handle_data(self, data):
        if self._href and data.strip():
            self._parts.append(data.strip())

    def handle_endtag(self, tag):
        if tag != "a" or not self._href:
            return
        native_id = urlparse(self._href).path.rsplit("-jid-", 1)[-1]
        title = " ".join(self._parts).strip()
        if native_id and native_id not in self._seen and title and title.lower() != "more info":
            self._seen.add(native_id)
            self.rows.append(
                job(
                    "experian",
                    native_id,
                    title=title,
                    company="Experian",
                    url=self._href,
                    country="BR",
                    market="BR",
                    contract_types=["CLT"],
                )
            )
        self._href = ""
        self._parts = []


def fetch():
    rows, known = [], set()
    for page in range(1, MAX_PAGES + 1):
        parser = ResultsParser()
        parser.feed(get_text(LIST_URL.format(page=page), timeout=45, retries=3))
        page_rows = [row for row in parser.rows if row["native_id"] not in known]
        if not page_rows:
            break
        rows.extend(page_rows)
        known.update(row["native_id"] for row in page_rows)
    if not rows:
        raise RuntimeError("Experian returned no public Brazil job links")

    with ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
        futures = {
            pool.submit(_fetch_detail_model, row["url"]): row
            for row in rows
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                model = future.result()
            except Exception:
                continue
            if model:
                row["work_model"] = model
    return rows
