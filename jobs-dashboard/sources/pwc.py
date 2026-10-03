# -*- coding: utf-8 -*-
"""Brazilian experienced-career vacancies from PwC's public results page."""
import json
import re
from urllib.parse import urlencode, urlparse

from ._common import job, work_model_label
from ._http import get_text

LISTING = (
    "https://www.pwc.com/gx/en/careers/job-results.html"
    "?wdcountry=BRA&wdjobsite=Global_Experienced_Careers"
    "&flds=jobreqid,title,location,los,specialism,grade,industry,region,apply,jobsite,iso"
)
JOB_SITE = "Global_Experienced_Careers"
WORKDAY_HOST = "pwc.wd3.myworkdayjobs.com"


def _records(markup):
    """Decode the complete jsondata array embedded in the official HTML."""
    match = re.search(r"\bvar\s+jsondata\s*=\s*", markup)
    if not match:
        raise RuntimeError("PwC listing did not contain jsondata")
    try:
        records, _end = json.JSONDecoder().raw_decode(markup[match.end():])
    except ValueError as error:
        raise RuntimeError("PwC listing contained invalid jsondata") from error
    if not isinstance(records, list):
        raise RuntimeError("PwC jsondata was not a list")
    return records


def _detail_url(record, native_id, title):
    """Prefer the direct vacancy page over the Workday application form."""
    apply_url = str(record.get("apply") or "").strip()
    parsed = urlparse(apply_url)
    if (
        parsed.scheme == "https"
        and parsed.netloc.lower() == WORKDAY_HOST
        and f"/{JOB_SITE}/job/" in parsed.path
        and parsed.path.rstrip("/").endswith("/apply")
    ):
        return apply_url.rsplit("/apply", 1)[0]
    query = urlencode({
        "wdjobreqid": native_id,
        "wdcountry": "BRA",
        "jobtitle": title,
        "wdjobsite": JOB_SITE,
        "wdjd": "simple",
    })
    return f"https://www.pwc.com/gx/en/careers/job-results/description.html?{query}"


def fetch():
    """Collect every currently listed Brazilian vacancy, not only page one."""
    markup = get_text(LISTING, timeout=45, retries=3)
    rows, seen = [], set()
    for record in _records(markup):
        if not isinstance(record, dict):
            continue
        if record.get("iso") != "BRA" or record.get("jobsite") != JOB_SITE:
            continue
        native_id = str(record.get("jobreqid") or "").strip()
        title = str(record.get("title") or "").strip()
        if not native_id or not title or native_id in seen:
            continue
        seen.add(native_id)
        location = str(record.get("location") or "").strip()
        city = location if location and location.casefold() not in {"remote", "remoto"} else "Brasil"
        categories = [
            str(record[key]).strip()
            for key in ("los", "specialism")
            if record.get(key) and str(record[key]).strip() != "Not Applicable"
        ]
        grade = str(record.get("grade") or "").strip()
        rows.append(job(
            "pwc", native_id, title=title, company="PwC",
            url=_detail_url(record, native_id, title),
            work_model=work_model_label(raw=f"{title} {location}"),
            city=city, country="BR", market="BR",
            levels=[grade] if grade else [],
            categories=categories or ["Carreiras PwC"],
        ))
    if not rows:
        raise RuntimeError("PwC listing returned no recognizable Brazil vacancies")
    return rows
