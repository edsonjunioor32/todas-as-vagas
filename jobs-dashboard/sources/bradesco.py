# -*- coding: utf-8 -*-
"""Public career listings from Banco Bradesco's CSOD careers site."""
import json
import re
import time
import urllib.error
import urllib.request

from ._common import (
    is_brazil_location,
    iso_date,
    job,
    split_location,
    strip_html,
    work_model_label,
)
from ._http import get_text


COMPANY = "Bradesco"
TENANT = "bradesco"
SITE_ID = 1
CAREERS_URL = (
    "https://bradesco.csod.com/ux/ats/careersite/1/home?c=bradesco"
)
PAGE_SIZE = 50
API_REGIONS = (
    "https://us.api.csod.com",
    "https://eu.api.csod.com",
    "https://uk.api.csod.com",
    "https://au.api.csod.com",
)


def _bootstrap():
    markup = get_text(CAREERS_URL, timeout=45, retries=3)
    context_match = re.search(
        r"csod\.context\s*=\s*(\{.*?\})\s*;",
        markup,
        re.DOTALL,
    )
    if not context_match:
        raise RuntimeError("CSOD did not expose the public careers context")

    try:
        context = json.loads(context_match.group(1))
    except (json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("CSOD exposed an invalid public careers context") from error
    if not isinstance(context, dict):
        raise RuntimeError("CSOD public careers context is not an object")

    token = context.get("token")
    culture_id = context.get("cultureID")
    culture_name = str(context.get("cultureName") or "en-US").strip() or "en-US"
    endpoint = str((context.get("endpoints") or {}).get("cloud") or "").rstrip("/")
    if not token:
        raise RuntimeError("CSOD public careers context did not include a token")
    if culture_id is None:
        raise RuntimeError("CSOD public careers context did not include cultureID")
    if endpoint and not re.fullmatch(
        r"https://(?:[a-z0-9-]+\.)?api\.csod\.com",
        endpoint,
        re.I,
    ):
        raise RuntimeError(f"CSOD exposed an unexpected cloud endpoint: {endpoint}")

    normalized = markup.replace(r"\/", "/")
    discovered_regions = re.findall(
        r"https://(?:[a-z0-9-]+\.)?api\.csod\.com",
        normalized,
        re.I,
    )
    discovered_regions = list(dict.fromkeys(value.rstrip("/") for value in discovered_regions))
    return token, endpoint, discovered_regions, culture_id, culture_name


def _post_json(url, payload, headers, retries=3):
    body = json.dumps(payload).encode("utf-8")
    error = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
            error = exc
        if attempt < retries:
            time.sleep(2 * attempt)
    raise RuntimeError(f"CSOD job search failed: {error}") from error


def _location_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(
            str(value.get(key) or "")
            for key in ("locationName", "name", "city", "state", "country", "countryName")
        ).strip()
    if isinstance(value, list):
        return " | ".join(_location_text(item) for item in value if _location_text(item))
    return ""


def _field(item, *names):
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return value
    return ""


def _row(item):
    native_id = _field(item, "requisitionId", "requisitionID", "id", "jobId")
    title = _field(
        item,
        "displayJobTitle",
        "postingTitle",
        "title",
        "requisitionTitle",
        "jobTitle",
    )
    if not native_id or not title:
        return None

    description = strip_html(_field(item, "externalDescription", "description", "jobDescription"))
    location = _location_text(_field(item, "locations", "location", "locationName"))
    if location and not is_brazil_location(location):
        return None
    city, state, _country = split_location(location)
    url = (
        f"https://bradesco.csod.com/ux/ats/careersite/{SITE_ID}"
        f"/home/requisition/{native_id}?c={TENANT}"
    )
    raw = " ".join((str(title), description, location))
    return job(
        "bradesco",
        native_id,
        title=str(title),
        company=COMPANY,
        url=url,
        work_model=work_model_label(raw=raw),
        city=city,
        state=state,
        country="BR",
        market="BR",
        published_date=iso_date(
            _field(item, "postingEffectiveDate", "postedDate", "postingDate", "datePosted")
        ),
        expires_date=iso_date(
            _field(item, "postingExpirationDate", "closingDate", "expirationDate", "endDate")
        ),
        description=description,
        categories=[str(_field(item, "category", "jobCategory", "jobFamily"))] if _field(item, "category", "jobCategory", "jobFamily") else [],
        pcd=bool(re.search(r"\b(?:pcd|pessoa com defici)", raw, re.I)),
    )


def fetch():
    token, preferred_cloud, discovered_regions, culture_id, culture_name = _bootstrap()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://bradesco.csod.com",
        "Referer": CAREERS_URL,
        "Csod-Accept-Language": culture_name,
    }
    rows, seen = [], set()
    regions = []
    for region in (preferred_cloud, *discovered_regions, *API_REGIONS):
        if region and region not in regions:
            regions.append(region)

    last_error = None
    for cloud in regions:
        try:
            for page in range(1, 100):
                payload = {
                    "careerSiteId": SITE_ID,
                    "careerSitePageId": 1,
                    "pageNumber": page,
                    "pageSize": PAGE_SIZE,
                    "cultureId": culture_id,
                    "cultureName": culture_name,
                    "searchText": "",
                    "states": [],
                    "countryCodes": [],
                    "cities": [],
                    "placeID": "",
                    "radius": "",
                    "postingsWithinDays": "",
                    "customFieldCheckboxKeys": [],
                    "customFieldDropdowns": [],
                    "customFieldRadios": [],
                }
                response = _post_json(f"{cloud}/rec-job-search/external/jobs", payload, headers)
                if response.get("status") != "Success":
                    raise RuntimeError(f"CSOD search returned {response.get('status') or 'an invalid response'}")
                data = response.get("data", {})
                requisitions = data.get("requisitions", [])
                if not requisitions:
                    break
                for item in requisitions:
                    row = _row(item)
                    if row and row["native_id"] not in seen:
                        seen.add(row["native_id"])
                        rows.append(row)
                total = int(data.get("totalCount") or 0)
                if page * PAGE_SIZE >= total:
                    break
            if rows:
                break
        except Exception as error:
            last_error = error
            continue
    if not rows:
        detail = f": {last_error}" if last_error else ""
        raise RuntimeError(f"Bradesco CSOD returned no public Brazil requisitions{detail}")
    return rows
