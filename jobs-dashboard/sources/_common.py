# -*- coding: utf-8 -*-
"""Helpers shared by every portal adapter.

Every source returns the same public-safe shape. Portal-specific descriptions
are used only in memory for classification and are never exported to the site.
"""
import re
import html as ihtml
from datetime import datetime, timezone


def strip_html(s, limit=6000):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = ihtml.unescape(s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s[:limit]


def iso_date(value):
    """Best-effort normalization of a portal's date field to 'YYYY-MM-DD'.
    Accepts ISO strings, epoch seconds (int/str), or None."""
    if value is None or value == "":
        return ""
    # epoch seconds?
    try:
        n = int(value)
        if n > 10_000_000:  # plausibly a unix timestamp, not a year
            return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    s = str(value).strip()
    # take the leading YYYY-MM-DD if present
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else ""


def work_model_label(remote_flag=None, raw=None):
    """Normalize a work-model to remote / hybrid / on-site / '' (unknown).

    The labels are English (the dashboard renders them as-is); the strings we
    match against stay bilingual, since BR portals describe it in Portuguese."""
    if remote_flag is True:
        return "remote"
    t = (raw or "").lower()
    if any(k in t for k in ("remote", "remoto", "anywhere", "home office", "home-office")):
        return "remote"
    if any(k in t for k in ("hybrid", "híbrido", "hibrido")):
        return "hybrid"
    if any(k in t for k in ("on-site", "onsite", "presencial", "in office", "in-office")):
        return "on-site"
    return ""


def split_location(value):
    """Best-effort split of strings such as ``Cidade, UF, BR``."""
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    city = parts[0] if parts else ""
    state = parts[-2] if len(parts) >= 3 and len(parts[-2]) <= 3 else ""
    country = parts[-1] if len(parts) >= 2 and len(parts[-1]) <= 3 else ""
    return city, state, country


def job(source, native_id, title, company, url, **extra):
    """Build one normalized job dict. `extra` may set any of the optional fields."""
    d = {
        "source": source,
        "native_id": str(native_id) if native_id is not None else "",
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "url": url or "",
        "work_model": "",
        "city": "",
        "state": "",
        "country": "",
        "market": "",          # "BR" | "Global remote"
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "published_date": "",
        "expires_date": "",
        "skills": [],
        "description": "",
        "levels": [],          # structured seniority hints (The Muse)
        "categories": [],      # structured area hints (The Muse / Adzuna)
        "contract_types": [],
        "pcd": False,
        "blind_selection": False,
    }
    d.update(extra)
    return d
