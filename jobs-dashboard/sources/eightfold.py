# -*- coding: utf-8 -*-
"""Public Eightfold career-site collectors."""
import re
from urllib.parse import urlencode, urljoin, urlsplit

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json


VALE_API = "https://vale.eightfold.ai/api/apply/v2/jobs"
VALE_DOMAIN = "vale.com"
VALE_LOCATION = "Brazil"
VALE_ORIGIN = "https://vale.eightfold.ai"
PAGE_SIZE = 10  # Vale's public endpoint caps responses at ten positions.
MAX_POSITIONS = 5000


def _page_url(start):
    query = urlencode({
        "domain": VALE_DOMAIN,
        "location": VALE_LOCATION,
        "start": start,
        "limit": PAGE_SIZE,
    })
    return f"{VALE_API}?{query}"


def _location_text(value):
    if isinstance(value, dict):
        return ", ".join(
            str(value.get(key) or "").strip()
            for key in ("city", "state", "country", "name")
            if str(value.get(key) or "").strip()
        )
    if isinstance(value, (list, tuple, set)):
        return ", ".join(
            text for item in value if (text := _location_text(item))
        )
    return str(value or "").strip()


def _position_location(position):
    """Prefer a specific city over the broad country-only search label."""
    values = position.get("locations") or []
    if not isinstance(values, (list, tuple)):
        values = [values]
    values = [_location_text(value) for value in values]
    values = [value for value in values if value]
    if not values:
        broad = _location_text(position.get("location"))
        values = [broad] if broad else []

    specific = [
        value for value in values
        if value.casefold() not in {"brazil", "brasil", "br"}
    ]
    return next(
        (
            value for value in specific
            if len([part for part in value.split(",") if part.strip()]) >= 3
        ),
        None,
    ) or next((value for value in specific if "," in value), None) or (
        specific[0] if specific else (values[0] if values else "")
    )


def _split_job_location(value):
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    if len(parts) >= 3:
        city = parts[0]
        state = ", ".join(parts[1:-1])
        state = re.sub(r"^(?:state|province) of\s+", "", state, flags=re.I)
        if len(state) <= 3:
            state = state.upper()
        return city, state
    if len(parts) == 2 and parts[-1].casefold() in {"brazil", "brasil", "br"}:
        return "", parts[0]
    if len(parts) == 2:
        return parts[0], parts[1].upper() if len(parts[1]) <= 3 else parts[1]
    return (parts[0], "") if parts else ("", "")


def _position_url(position, native_id):
    candidate = str(position.get("canonicalPositionUrl") or "").strip()
    url = urljoin(f"{VALE_ORIGIN}/", candidate)
    parsed = urlsplit(url)
    if (
        parsed.scheme == "https"
        and parsed.netloc.casefold() == "vale.eightfold.ai"
        and parsed.path.startswith("/careers/job/")
    ):
        return f"{VALE_ORIGIN}{parsed.path}"
    return f"{VALE_ORIGIN}/careers/job/{native_id}"


def _normalize_position(position):
    """Map a public Eightfold position into the shared vacancy schema."""
    if not isinstance(position, dict):
        return None

    native_id = str(position.get("id") or position.get("ats_job_id") or "").strip()
    title = str(position.get("posting_name") or position.get("name") or "").strip()
    if not native_id or not title:
        return None

    location = _position_location(position)
    city, state = _split_job_location(location)

    categories = list(dict.fromkeys(
        str(value).strip()
        for value in (position.get("department"), position.get("business_unit"))
        if str(value or "").strip()
    ))
    return job(
        "vale",
        native_id,
        title=title,
        company="Vale",
        url=_position_url(position, native_id),
        work_model=work_model_label(
            raw=" ".join((
                str(position.get("work_location_option") or ""),
                str(position.get("location_flexibility") or ""),
            ))
        ),
        city=city,
        state=state,
        country="BR",
        market="BR",
        published_date=iso_date(position.get("t_create")),
        description=strip_html(str(position.get("job_description") or ""), limit=12000),
        categories=categories,
    )


def fetch_vale():
    """Fetch all public Brazil-filtered Vale postings with bounded pagination.

    The public endpoint returns ten entries per request and reports the total
    count. A short/repeated page before that count is reached is treated as an
    incomplete source failure so a partial catalogue is never presented as a
    successful refresh.
    """
    rows = []
    seen = set()
    expected_count = None
    offset = 0

    while expected_count is None or offset < expected_count:
        if offset >= MAX_POSITIONS:
            if expected_count and expected_count > MAX_POSITIONS:
                raise RuntimeError(
                    f"Vale reports {expected_count} positions, above the "
                    f"safe limit of {MAX_POSITIONS}"
                )
            break

        payload = get_json(_page_url(offset), timeout=40, retries=3)
        if not isinstance(payload, dict):
            raise RuntimeError("Vale Eightfold returned an unexpected payload")

        positions = payload.get("positions")
        if not isinstance(positions, list):
            raise RuntimeError("Vale Eightfold response has no positions list")

        try:
            count = int(payload.get("count"))
        except (TypeError, ValueError) as error:
            raise RuntimeError("Vale Eightfold returned an invalid count") from error
        if count < 0 or (count == 0 and positions):
            raise RuntimeError("Vale Eightfold returned an inconsistent count")
        if expected_count is None:
            expected_count = count
            if expected_count > MAX_POSITIONS:
                raise RuntimeError(
                    f"Vale reports {expected_count} positions, above the "
                    f"safe limit of {MAX_POSITIONS}"
                )
        elif count != expected_count:
            raise RuntimeError(
                "Vale Eightfold result count changed during pagination"
            )

        if not positions:
            if offset < expected_count:
                raise RuntimeError(
                    "Vale Eightfold pagination ended before its reported count"
                )
            break

        page_ids = [
            str(item.get("id") or item.get("ats_job_id") or "").strip()
            for item in positions
            if isinstance(item, dict)
        ]
        new_ids = {identifier for identifier in page_ids if identifier} - seen
        if not new_ids:
            raise RuntimeError(
                "Vale Eightfold pagination returned no new positions"
            )

        for position in positions:
            row = _normalize_position(position)
            if row and row["native_id"] not in seen:
                seen.add(row["native_id"])
                rows.append(row)

        returned = len(positions)
        if returned < PAGE_SIZE and offset + returned < expected_count:
            raise RuntimeError(
                "Vale Eightfold returned an incomplete pagination page"
            )
        offset += returned

    if not rows:
        raise RuntimeError("Vale Eightfold returned no public Brazil vacancies")
    if expected_count and len(seen) < expected_count:
        raise RuntimeError(
            f"Vale Eightfold returned {len(seen)} distinct positions out of "
            f"{expected_count} reported"
        )
    return rows
