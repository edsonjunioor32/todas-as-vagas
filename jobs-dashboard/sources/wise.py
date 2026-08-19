# -*- coding: utf-8 -*-
"""Public Brazil job listings from Wise Careers."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from ._common import job
from ._http import get_text


BASE_URL = "https://wise.jobs"
LIST_URL = "https://wise.jobs/jobs?options=296&page={page}"
MAX_PAGES = 20


class WiseListParser(HTMLParser):
    """Collect the public job links exposed in a Wise search-results page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._seen = set()
        self._href = ""
        self._depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if self._href:
            self._depth += 1
            return
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        parsed = urlparse(href)
        if not parsed.path.startswith("/job/"):
            return
        self._href = urljoin(BASE_URL, href)
        self._depth = 1
        self._parts = []

    def handle_data(self, data):
        if self._href and data.strip():
            self._parts.append(data.strip())

    def handle_endtag(self, tag):
        if not self._href:
            return
        self._depth -= 1
        if self._depth:
            return
        native_id = urlparse(self._href).path.rsplit("-jid-", 1)[-1]
        title = " ".join(self._parts).strip()
        if native_id and native_id not in self._seen and title and title.lower() != "read more":
            self._seen.add(native_id)
            self.rows.append(
                job(
                    "wise",
                    native_id,
                    title=title,
                    company="Wise",
                    url=self._href,
                    city="São Paulo",
                    state="SP",
                    country="BR",
                    market="BR",
                )
            )
        self._href = ""
        self._parts = []


def fetch():
    rows = []
    known = set()
    for page in range(1, MAX_PAGES + 1):
        parser = WiseListParser()
        parser.feed(get_text(LIST_URL.format(page=page), timeout=45, retries=3))
        page_rows = [row for row in parser.rows if row["native_id"] not in known]
        if not page_rows:
            break
        rows.extend(page_rows)
        known.update(row["native_id"] for row in page_rows)
    if not rows:
        raise RuntimeError("Wise returned no public Brazil job links")
    return rows
