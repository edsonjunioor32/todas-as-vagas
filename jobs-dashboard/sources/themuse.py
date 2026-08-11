# -*- coding: utf-8 -*-
"""The Muse — public API (key optional). Valuable because it ships STRUCTURED
seniority (`levels[]`) and area (`categories[]`), which the classifier prefers
over title regexes. Docs: https://www.themuse.com/developers/api/v2
"""
import time
from ._http import get_json
from ._common import strip_html, iso_date, work_model_label, job

BASE = "https://www.themuse.com/api/public/jobs"
MAX_PAGES = 45   # the feed exposes ~20k pages; 45 × 20 ≈ 900 recent jobs


def fetch():
    out = []
    for page in range(0, MAX_PAGES):
        d = get_json(f"{BASE}?page={page}&descending=true")
        results = d.get("results", [])
        for j in results:
            locs = [l.get("name", "") for l in (j.get("locations") or [])]
            loc_txt = ", ".join(locs)
            company = (j.get("company", {}) or {}).get("name", "")
            levels = [l.get("name", "") for l in (j.get("levels") or [])]
            cats = [c.get("name", "") for c in (j.get("categories") or [])]
            remote = any("remote" in l.lower() or "flexible" in l.lower() for l in locs)
            out.append(job(
                "themuse", j.get("id"),
                title=j.get("name", ""), company=company,
                url=(j.get("refs", {}) or {}).get("landing_page", ""),
                work_model=work_model_label(remote, loc_txt),
                city=locs[0] if locs else "",
                country=("Remote" if remote else (locs[0] if locs else "")),
                market="Global remote" if remote else "Global",
                published_date=iso_date(j.get("publication_date")),
                description=strip_html(j.get("contents", "")),
                levels=[l for l in levels if l],
                categories=[c for c in cats if c],
            ))
        if not results or (d.get("page_count") and page >= d["page_count"] - 1):
            break
        time.sleep(0.4)
    return out
