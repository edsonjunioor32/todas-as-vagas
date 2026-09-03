# -*- coding: utf-8 -*-
"""Adapters for the career portals requested on 2026-08-29."""
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from ._common import iso_date, job, strip_html, work_model_label
from ._http import get_json, get_text
from . import quickin as quickin_source
from . import sankhya_senior


QUARK_SITE = "https://vagas.quarkrh.com.br"
QUARK_API = "https://rh-rs-portal-back.quark.tec.br/api/processos-seletivos"
QUARK_SLUG = "esig"

YELLOW_SITE = "https://www.yellowipe.io"
YELLOW_LIST = f"{YELLOW_SITE}/pt/jobs"
YELLOWIPE_MARKET = "Global - Portugal"
TIVIT_SITE = "https://web.tivit.com/talent"
TIVIT_API = "https://api.tivit.com/talent/api/job"

LEVEL_RE = re.compile(
    r"\b(j[uú]nior|jr\.?|pleno|mid(?:[- ]level)?|s[eê]nior|sr\.?|"
    r"especialista|lead|gerente|coordenador|trainee)\b",
    re.I,
)


def _levels(title):
    return list(dict.fromkeys(
        match.group(1).title() for match in LEVEL_RE.finditer(title or "")
    ))


def _quark_rows(payload):
    entries = []
    if isinstance(payload, dict):
        for key in ("processosSeletivos", "processos", "jobs", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                entries = value
                break
    if not entries:
        raise RuntimeError("QuarkRH/ESIG returned no active vacancy records")

    rows, seen = [], set()
    for data in entries:
        if not isinstance(data, dict):
            continue
        native_id = str(data.get("id") or "").strip()
        title = str(
            data.get("tituloProcesso")
            or data.get("nomeCargo")
            or data.get("nome")
            or ""
        ).strip()
        if not native_id or not title or native_id in seen:
            continue
        seen.add(native_id)
        location = str(data.get("localidade") or "").strip()
        parts = [
            item.strip() for item in re.split(r"\s*[-–—,]\s*", location)
            if item.strip()
        ]
        city = parts[0] if parts else ""
        state = parts[1] if len(parts) >= 3 and len(parts[1]) <= 40 else ""
        model = work_model_label(raw=location)
        row = job(
            "esig",
            native_id,
            title=title,
            company="ESIG Group",
            url=f"{QUARK_SITE}/{QUARK_SLUG}/{native_id}",
            work_model=model,
            city=city,
            state=state,
            country="BR",
            market="BR",
            published_date=iso_date(
                data.get("dataPublicacao")
                or data.get("date_created")
                or data.get("dateCreated")
            ),
            description=strip_html(data.get("descricao") or ""),
            levels=_levels(title),
            categories=[
                str(data.get("setor") or "").strip() or "ESIG Group"
            ],
            contract_types=(
                [str(data.get("vinculo")).strip()]
                if str(data.get("vinculo") or "").strip()
                else []
            ),
        )
        rows.append(row)
    if not rows:
        raise RuntimeError("QuarkRH/ESIG returned no recognizable vacancy records")
    return rows


def fetch_esig():
    payload = get_json(
        f"{QUARK_API}/instituicao/{QUARK_SLUG}",
        headers={
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (compatible; todas-as-vagas/1.0)",
        },
        timeout=45,
        retries=3,
    )
    return _quark_rows(payload)


_RSC_PUSH_RE = re.compile(
    r'self\.__next_f\.push\(\[1,"((?:\\.|[^"\\])*)"\]\)', re.S
)
_YELLOW_DATA_RE = re.compile(r'"data":(\[.*?\]),"technologies":', re.S)
_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>',
    re.I,
)


def _yellow_entries(markup):
    for match in _RSC_PUSH_RE.finditer(markup or ""):
        try:
            payload = json.loads('"' + match.group(1) + '"')
        except (TypeError, ValueError):
            continue
        data_match = _YELLOW_DATA_RE.search(payload)
        if not data_match:
            continue
        try:
            entries = json.loads(data_match.group(1))
        except (TypeError, ValueError):
            continue
        if isinstance(entries, list):
            return entries

    match = _NEXT_DATA_RE.search(markup or "")
    if match:
        try:
            payload = json.loads(html.unescape(match.group(1)))
        except (TypeError, ValueError):
            payload = {}
        entries = (
            ((payload.get("props") or {}).get("pageProps") or {}).get("jobs")
        )
        if isinstance(entries, list):
            return entries
    return []


def _yellow_location(value):
    if isinstance(value, (list, tuple)):
        values = [str(item or "").strip() for item in value if str(item or "").strip()]
        text = values[0] if values else ""
    elif isinstance(value, dict):
        text = str(
            value.get("name")
            or value.get("label")
            or value.get("city")
            or ""
        ).strip()
    else:
        text = str(value or "").strip()
    parts = [
        item.strip() for item in re.split(r"\s+-\s+", text) if item.strip()
    ]
    country = parts[0] if parts else ""
    state = parts[1] if len(parts) >= 3 else ""
    city = parts[-1] if len(parts) >= 2 else ""
    return text, city, state, country


def _yellow_rows(markup):
    entries = _yellow_entries(markup)
    if not entries:
        raise RuntimeError("YellowIpe returned no active vacancy records")
    rows, seen = [], set()
    for data in entries:
        if not isinstance(data, dict):
            continue
        native_id = str(data.get("id") or "").strip()
        title = str(data.get("title") or "").strip()
        if not native_id or not title or native_id in seen:
            continue
        seen.add(native_id)
        location_text, city, state, country_raw = _yellow_location(
            data.get("location")
        )
        country_key = country_raw.casefold()
        # YellowIpe is intentionally classified in the portal's Portugal
        # market, even when an individual card lists a Brazilian location.
        market = YELLOWIPE_MARKET
        country = "BR" if country_key in {"br", "brasil", "brazil"} else country_raw
        workplace = data.get("workplacePolicy") or []
        workplace_text = (
            " ".join(str(item or "") for item in workplace)
            if isinstance(workplace, (list, tuple))
            else str(workplace or "")
        )
        rows.append(job(
            "yellowipe",
            native_id,
            title=title,
            company="YellowIpe",
            url=f"{YELLOW_SITE}/pt/jobs/{native_id}",
            work_model=work_model_label(raw=workplace_text),
            city=city,
            state=state,
            country=country,
            market=market,
            published_date=iso_date(data.get("updatedAt")),
            description=strip_html(data.get("positionDescription") or ""),
            levels=_levels(title),
            categories=["YellowIpe"],
        ))
    if not rows:
        raise RuntimeError("YellowIpe returned no recognizable vacancy records")
    return rows


def fetch_yellowipe():
    markup = get_text(
        YELLOW_LIST,
        headers={
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (compatible; todas-as-vagas/1.0)",
        },
        timeout=45,
        retries=3,
    )
    return _yellow_rows(markup)


def _tivit_page(page):
    query = urlencode({
        "Page": page,
        "RecordsByPage": 100,
        "OrderByDesc": "true",
        "Timestamp": str(int(time.time() * 1000)),
        "Language": "pt",
    })
    return get_json(
        f"{TIVIT_API}?{query}",
        headers={
            "Origin": "https://web.tivit.com",
            "Referer": "https://web.tivit.com/talent/job-search",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=45,
        retries=3,
    )


def _tivit_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("jobs", "data", "results", "content", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _tivit_location(value, work_model):
    text = str(value or "").strip()
    if not text:
        return ("Brasil" if work_model == "remote" else ""), ""
    parts = [
        item.strip() for item in re.split(r"\s*[,|]\s*", text) if item.strip()
    ]
    return parts[0] if parts else text, parts[1] if len(parts) >= 3 else ""


def fetch_tivit():
    first = _tivit_page(1)
    first_items = _tivit_items(first)
    if not first_items:
        raise RuntimeError("TIVIT returned no active vacancy records")
    try:
        total_pages = max(
            1, int(first_items[0].get("totalPages") or 1)
        )
    except (AttributeError, TypeError, ValueError):
        total_pages = 1
    if total_pages > 50:
        raise RuntimeError(f"TIVIT returned an unexpected page count: {total_pages}")

    payloads = [first]
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=min(6, total_pages - 1)) as pool:
            futures = [
                pool.submit(_tivit_page, page)
                for page in range(2, total_pages + 1)
            ]
            for future in futures:
                payloads.append(future.result())

    rows, seen = [], set()
    for payload in payloads:
        for data in _tivit_items(payload):
            if not isinstance(data, dict):
                continue
            native_id = str(data.get("jobId") or data.get("id") or "").strip()
            title = str(data.get("title") or "").strip()
            if not native_id or not title or native_id in seen:
                continue
            seen.add(native_id)
            work_model = work_model_label(raw=data.get("workMode"))
            city, state = _tivit_location(data.get("officeLocation"), work_model)
            employment = str(data.get("employmentType") or "").strip()
            rows.append(job(
                "tivit",
                native_id,
                title=title,
                company=str(data.get("companyName") or "TIVIT").strip(),
                url=f"{TIVIT_SITE}/job-detail?jobid={native_id}",
                work_model=work_model,
                city=city,
                state=state,
                country="BR",
                market="BR",
                published_date=iso_date(data.get("publicationDate")),
                expires_date=iso_date(data.get("registrationUntil")),
                levels=_levels(title),
                categories=[employment] if employment else ["TIVIT"],
            ))
    if not rows:
        raise RuntimeError("TIVIT returned no recognizable vacancy records")
    return rows


TARGETS = (
    ("esig", fetch_esig),
    ("azify", sankhya_senior.fetch_azify),
    ("pontotel", sankhya_senior.fetch_pontotel),
    ("grupolev", sankhya_senior.fetch_grupolev),
    ("fiotec", sankhya_senior.fetch_fiotec),
    ("pessoaepessoa", sankhya_senior.fetch_pessoaepessoa),
    ("grupokothe", sankhya_senior.fetch_grupokothe),
    ("jb3investimentos", sankhya_senior.fetch_jb3investimentos),
    ("osklen", sankhya_senior.fetch_osklen),
    ("finayatech", quickin_source.fetch_finayatech),
    ("yellowipe", fetch_yellowipe),
    ("somosglobal", sankhya_senior.fetch_somosglobal),
    ("revemar", sankhya_senior.fetch_revemar),
    ("insper", sankhya_senior.fetch_insper),
    ("guaranamineiro", sankhya_senior.fetch_guaranamineiro),
    ("tivit", fetch_tivit),
    ("overlabs", sankhya_senior.fetch_overlabs),
    ("sicoobcocred", sankhya_senior.fetch_sicoobcocred),
    ("liquidz", sankhya_senior.fetch_liquidz),
    ("btcreditos", sankhya_senior.fetch_btcreditos),
    ("glcapital", sankhya_senior.fetch_glcapital),
    ("grupoamigao", sankhya_senior.fetch_grupoamigao),
    ("true", sankhya_senior.fetch_true),
)
