# -*- coding: utf-8 -*-
"""Public Trakstar Hire feed for the Sensedia careers page."""

from datetime import datetime
from email.utils import parsedate_to_datetime
import re
import xml.etree.ElementTree as ET

from ._common import is_brazil_location, iso_date, job, strip_html, work_model_label
from ._http import get_text


FEED_URL = "https://sensedia.hire.trakstar.com/jobfeeds/sensedia"
CAREERS_URL = "https://sensedia.hire.trakstar.com/"
COMPANY = "Sensedia"

TITLE_NAMES = {"title", "jobtitle", "positiontitle"}
LINK_NAMES = {"link", "url", "hostedurl", "applyurl", "applicationurl"}
ID_NAMES = {"guid", "id", "jobid", "openingid", "reference"}
DESCRIPTION_NAMES = {"description", "summary", "content", "encoded"}
LOCATION_NAMES = {"location", "joblocation", "locationname", "citystatecountry"}
CITY_NAMES = {"city", "locality", "addresslocality"}
STATE_NAMES = {"state", "region", "addressregion", "province"}
COUNTRY_NAMES = {"country", "countrycode", "addresscountry"}
REMOTE_NAMES = {"remote", "isremote", "allowsremote", "joblocationtype", "workmode"}
CONTRACT_NAMES = {"employmenttype", "positiontype", "jobtype", "contracttype"}
CATEGORY_NAMES = {"category", "department", "team", "function"}
LEVEL_PATTERN = re.compile(
    r"\b(junior|jr\.?|pleno|mid[- ]?level|senior|sr\.?|lead|principal|"
    r"especialista|coordenador|gerente|manager|director)\b",
    re.I,
)
PCD_PATTERN = re.compile(r"\bpcd\b|pessoas?\s+com\s+defici", re.I)


def _local_name(tag):
    return str(tag or "").rsplit("}", 1)[-1].casefold().replace("-", "").replace("_", "")


def _node_text(node):
    return " ".join(" ".join(node.itertext()).split()).strip()


def _first(item, names):
    wanted = {_local_name(name) for name in names}
    for node in item.iter():
        if node is item or _local_name(node.tag) not in wanted:
            continue
        value = _node_text(node)
        if value:
            return value
    return ""


def _all(item, names):
    wanted = {_local_name(name) for name in names}
    values = []
    for node in item.iter():
        if node is item or _local_name(node.tag) not in wanted:
            continue
        value = _node_text(node)
        if value and value not in values:
            values.append(value)
    return values


def _link(item):
    wanted = {_local_name(name) for name in LINK_NAMES}
    for node in item.iter():
        if node is item or _local_name(node.tag) not in wanted:
            continue
        value = _node_text(node) or str(node.attrib.get("href") or "").strip()
        if value.startswith(("http://", "https://")):
            return value
    return ""


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return iso_date(text)


def _location(item, description):
    city = _first(item, CITY_NAMES)
    state = _first(item, STATE_NAMES)
    country = _first(item, COUNTRY_NAMES)
    raw = _first(item, LOCATION_NAMES)
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not city and parts:
        city = parts[0]
    if not state and len(parts) >= 3:
        state = parts[-2]
    if not country and len(parts) >= 2:
        country = parts[-1]
    if not country and is_brazil_location(" ".join((raw, description))):
        country = "BR"
    return city, state, country, raw


def _work_model(item, title, raw_location, description):
    remote_value = _first(item, REMOTE_NAMES).casefold()
    if remote_value in {"true", "yes", "sim", "1", "remote", "remoto", "fully remote"}:
        return "remote"
    return work_model_label(raw=" ".join((title, raw_location, description, remote_value)))


def _items(payload):
    root = ET.fromstring(payload)
    return [
        node
        for node in root.iter()
        if _local_name(node.tag) in {"item", "job", "opening", "position"}
    ]


def fetch():
    payload = get_text(
        FEED_URL,
        headers={"Accept": "application/rss+xml, application/xml, text/xml"},
        timeout=45,
        retries=3,
    )
    rows = []
    seen = set()
    for item in _items(payload):
        title = _first(item, TITLE_NAMES)
        url = _link(item)
        if not title or not url or url in seen:
            continue
        seen.add(url)
        description = strip_html(_first(item, DESCRIPTION_NAMES))
        city, state, country, raw_location = _location(item, description)
        published = _parse_date(
            _first(item, {"pubdate", "published", "dateposted", "created", "updated"})
        )
        categories = _all(item, CATEGORY_NAMES)
        contracts = _all(item, CONTRACT_NAMES)
        levels = []
        level_match = LEVEL_PATTERN.search(title)
        if level_match:
            levels.append(level_match.group(1))
        native_id = _first(item, ID_NAMES) or url
        rows.append(
            job(
                "sensedia",
                native_id,
                title=title,
                company=COMPANY,
                url=url,
                work_model=_work_model(item, title, raw_location, description),
                city=city or "Brasil",
                state=state,
                country=country or "BR",
                market="BR",
                published_date=published,
                description=description,
                skills=[],
                levels=levels,
                categories=categories,
                contract_types=contracts,
                pcd=bool(PCD_PATTERN.search(" ".join((title, description)))),
            )
        )
    if not rows:
        raise RuntimeError("Sensedia Trakstar feed returned no recognizable vacancies")
    return rows
