# -*- coding: utf-8 -*-
"""Public listings requested on 2026-09-16."""
from . import quickin
from ._common import is_brazil_location, iso_date, job, strip_html, work_model_label
from ._http import get_json
from .ats_boards import PER_COMPANY


JOBGETHER_API = (
    "https://api.lever.co/v0/postings/jobgether"
    "?mode=json&location=Brazil"
)


def fetch_blacklion():
    """Collect Black Lion's published openings from its Quickin company board."""
    return quickin.fetch_company(
        "blacklion",
        source="blacklion",
        company="Black Lion",
    )


def fetch_jobgether():
    """Collect public Jobgether postings whose Lever location is Brazil."""
    payload = get_json(JOBGETHER_API)
    if not isinstance(payload, list):
        raise RuntimeError("Jobgether Lever returned an unexpected payload")

    rows = []
    for posting in payload:
        categories = posting.get("categories") or {}
        location = str(categories.get("location") or "").strip()
        if not is_brazil_location(location):
            continue

        native_id = posting.get("id")
        title = str(posting.get("text") or "").strip()
        url = str(posting.get("hostedUrl") or "").strip()
        if not native_id or not title or not url:
            continue

        rows.append(job(
            "jobgether",
            native_id,
            title=title,
            company="Jobgether",
            url=url,
            work_model=work_model_label(
                raw=f"{categories.get('commitment') or ''} {location}"
            ),
            city=location,
            country="BR",
            market="BR",
            published_date=iso_date(posting.get("createdAt")),
            description=strip_html(
                posting.get("descriptionPlain")
                or posting.get("description")
                or ""
            ),
            categories=[
                str(categories.get("department") or categories.get("team") or "")
            ],
        ))
        if len(rows) >= PER_COMPANY:
            break

    if not rows:
        raise RuntimeError("Jobgether Lever returned no Brazilian vacancies")
    return rows
