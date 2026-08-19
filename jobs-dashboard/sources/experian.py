# -*- coding: utf-8 -*-
"""Public Brazil job listings from Experian Careers."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from ._common import job
from ._http import get_text


BASE_URL = "https://jobs.experian.com"
LIST_URL = (
    "https://jobs.experian.com/jobs?options=765&page={page}"
    "&ln=&la=0&lo=0&lr=48&li="
)
MAX_PAGES = 20


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
    return rows
