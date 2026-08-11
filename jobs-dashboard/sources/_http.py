# -*- coding: utf-8 -*-
"""Shared HTTP helper — stdlib only, with a bounded retry/backoff.

Mirrors the resilience of commodity-risk-dashboard/pipeline.py::_download: retry
transient failures (timeout, 5xx, JSON-decode) with linear backoff, then raise.
Kept dependency-free (urllib) so the daily pipeline has zero third-party surface.
"""
import json
import time
import urllib.request
import urllib.error

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; jobs-market-explorer/1.0)",
    "Accept": "application/json",
}


def get_json(url, headers=None, timeout=25, retries=3, backoff=2.0):
    """GET a URL and parse JSON, retrying transient errors. Raises on final failure."""
    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last_err = e
            # 4xx (except 429) are not worth retrying — the request is wrong.
            if e.code < 500 and e.code != 429:
                raise
        except Exception as e:  # timeout, URLError, JSONDecodeError
            last_err = e
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise RuntimeError(f"get_json failed after {retries} attempts: {last_err}") from last_err
