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
import urllib.parse

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; jobs-market-explorer/1.0)",
    "Accept": "application/json",
}


def get_text(url, headers=None, timeout=25, retries=3, backoff=2.0):
    """GET a URL as UTF-8 text, retrying transient failures."""
    h = dict(DEFAULT_HEADERS)
    h["Accept"] = "text/html,application/xhtml+xml"
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            last_err = error
            if error.code < 500 and error.code != 429:
                raise
        except Exception as error:  # timeout and URLError
            last_err = error
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise RuntimeError(f"get_text failed after {retries} attempts: {last_err}") from last_err


def get_json(url, headers=None, timeout=25, retries=3, backoff=2.0,
             retry_http_codes=None):
    """GET JSON with bounded retries.

    ``406`` is normally a permanent negotiation error, but some public ATS
    edges return it transiently when many boards are requested from one
    runner.  Callers such as Greenhouse can opt into retrying that code without
    changing the behavior of every other source.
    """
    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    retry_http_codes = set(retry_http_codes or ()) | {429}
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last_err = e
            # Most 4xx responses are permanent; selected codes can be
            # retried by a source that knows the endpoint is intermittently
            # blocked by an edge or content-negotiation layer.
            if e.code < 500 and e.code not in retry_http_codes:
                raise
        except Exception as e:  # timeout, URLError, JSONDecodeError
            last_err = e
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise RuntimeError(f"get_json failed after {retries} attempts: {last_err}") from last_err


def post_form_json(url, data, headers=None, timeout=25, retries=3, backoff=2.0):
    """POST URL-encoded form data and parse JSON, retrying transient failures."""
    h = dict(DEFAULT_HEADERS)
    h["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    if headers:
        h.update(headers)
    body = urllib.parse.urlencode(data).encode("utf-8")
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=h, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            last_err = error
            if error.code < 500 and error.code != 429:
                raise
        except Exception as error:
            last_err = error
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise RuntimeError(f"post_form_json failed after {retries} attempts: {last_err}") from last_err
