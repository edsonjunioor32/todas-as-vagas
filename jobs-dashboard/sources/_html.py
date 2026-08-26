# -*- coding: utf-8 -*-
"""Small parsers shared by public career pages with server-rendered HTML."""
import html
import json
import re
from html.parser import HTMLParser


JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
    re.I,
)


class PublicPageParser(HTMLParser):
    """Collect visible text, headings, links and useful meta values."""

    _SKIP_TAGS = {"script", "style", "noscript", "template"}
    _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.headings = []
        self.anchors = []
        self.meta = {}
        self._skip_depth = 0
        self._anchor_href = ""
        self._anchor_parts = []
        self._heading_tag = ""
        self._heading_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = dict(attrs)
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a" and attributes.get("href"):
            self._anchor_href = attributes["href"]
            self._anchor_parts = []
        if tag in self._HEADING_TAGS:
            self._heading_tag = tag
            self._heading_parts = []
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name") or ""
            value = attributes.get("content") or ""
            if key and value:
                self.meta[key.casefold()] = value.strip()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "a" and self._anchor_href:
            label = " ".join(self._anchor_parts).strip()
            self.anchors.append((self._anchor_href, label))
            self._anchor_href = ""
            self._anchor_parts = []
        if tag == self._heading_tag:
            heading = " ".join(self._heading_parts).strip()
            if heading:
                self.headings.append(heading)
            self._heading_tag = ""
            self._heading_parts = []

    def handle_data(self, data):
        if self._skip_depth:
            return
        value = re.sub(r"\s+", " ", data or "").strip()
        if not value:
            return
        self.parts.append(value)
        if self._anchor_href:
            self._anchor_parts.append(value)
        if self._heading_tag:
            self._heading_parts.append(value)

    @property
    def visible_text(self):
        return " ".join(self.parts).strip()


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def json_ld_objects(markup):
    """Yield valid JSON-LD dictionaries without trusting one fixed envelope."""
    for raw in JSON_LD_RE.findall(markup or ""):
        try:
            payload = json.loads(html.unescape(raw.strip()))
        except (TypeError, ValueError):
            continue
        yield from _walk(payload)


def job_posting(markup):
    """Return the first Schema.org JobPosting object, when available."""
    for value in json_ld_objects(markup):
        kind = value.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(str(item).casefold() == "jobposting" for item in kinds):
            return value
    return {}
