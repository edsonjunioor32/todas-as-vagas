# -*- coding: utf-8 -*-
"""Helpers shared by every portal adapter."""
import html as ihtml
import re
from datetime import datetime, timezone

def strip_html(value, limit=6000):
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = ihtml.unescape(text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:limit]

def iso_date(value):
    """Normalize a portal date while preserving a supplied publication time."""
    if value is None or value == "":
        return ""
    try:
        seconds = int(value)
        if seconds > 10_000_000:
            if seconds > 10_000_000_000:
                seconds /= 1000
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    text = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:T|\s)\d{2}:\d{2}", text):
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat(timespec="seconds")
        except ValueError:
            pass
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else ""

def work_model_label(remote_flag=None, raw=None):
    if remote_flag is True:
        return "remote"
    text = (raw or "").lower()
    if any(k in text for k in ("remote", "remoto", "anywhere", "home office", "home-office")):
        return "remote"
    if any(k in text for k in ("hybrid", "híbrido", "hibrido")):
        return "hybrid"
    if any(k in text for k in ("on-site", "onsite", "presencial", "in office", "in-office")):
        return "on-site"
    return ""

def split_location(value):
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    city = parts[0] if parts else ""
    state = parts[-2] if len(parts) >= 3 and len(parts[-2]) <= 3 else ""
    country = parts[-1] if len(parts) >= 2 and len(parts[-1]) <= 3 else ""
    return city, state, country

def job(source, native_id, title, company, url, **extra):
    data = {"source":source,"native_id":str(native_id) if native_id is not None else "","title":(title or "").strip(),"company":(company or "").strip(),"url":url or "","work_model":"","city":"","state":"","country":"","market":"","salary_min":None,"salary_max":None,"salary_currency":None,"published_date":"","expires_date":"","skills":[],"description":"","levels":[],"categories":[],"contract_types":[],"pcd":False,"blind_selection":False}
    data.update(extra)
    return data
