# -*- coding: utf-8 -*-
"""Quadros públicos Workday (myworkdayjobs/myworkdaysite) via API CXS.

Cada empresa é uma entrada em ``TENANTS``; ``TARGETS`` gera as fontes do
registro a partir dela.  Para incluir uma empresa nova, acrescente o tenant
(``host``, ``tenant``, ``site``, ``company``, ``url`` e, quando necessário,
``detail_base`` e ``brazil_facet``) — o nome da chave é o nome da fonte.

Migrado de ``requested_portals_27082026`` em 15/11/2026 sem mudança de
comportamento; aquele módulo mantém apelidos para compatibilidade.
"""
from urllib.parse import urljoin

from ._common import BRAZIL_WORDS, is_brazil_location, iso_date, job, strip_html, work_model_label
from ._http import post_json


TENANTS = {
    "avanade": {
        "host": "accenture.wd103.myworkdayjobs.com",
        "tenant": "accenture",
        "site": "AvanadeCareers",
        "company": "Avanade",
        "url": "https://accenture.wd103.myworkdayjobs.com/pt-BR/AvanadeCareers/",
    },
    "santander": {
        "host": "santander.wd3.myworkdayjobs.com",
        "tenant": "santander",
        "site": "SantanderCareers",
        "company": "Santander",
        "url": "https://santander.wd3.myworkdayjobs.com/pt-BR/SantanderCareers",
    },
    "iberdrola": {
        "host": "iberdrola.wd3.myworkdayjobs.com",
        "tenant": "iberdrola",
        "site": "Iberdrola",
        "company": "Iberdrola",
        "url": "https://iberdrola.wd3.myworkdayjobs.com/pt-BR/Iberdrola",
    },
    "iqvia": {
        "host": "iqvia.wd1.myworkdayjobs.com",
        "tenant": "iqvia",
        "site": "IQVIA",
        "company": "IQVIA",
        "url": "https://iqvia.wd1.myworkdayjobs.com/pt-BR/IQVIA",
    },
    "mdlz": {
        "host": "mdlz.wd3.myworkdayjobs.com",
        "tenant": "mdlz",
        "site": "External",
        "company": "Mondelēz International",
        "url": "https://mdlz.wd3.myworkdayjobs.com/pt-BR/External",
    },
    "edenred": {
        "host": "wd3.myworkdaysite.com",
        "tenant": "edenpeople",
        "site": "Edenred_Careers",
        "company": "Edenred",
        "url": "https://wd3.myworkdaysite.com/recruiting/edenpeople/Edenred_Careers/1/refreshFacet/318c8bb6f553100021d223d9780d30be",
        "detail_base": "https://wd3.myworkdaysite.com/recruiting/edenpeople/Edenred_Careers/1/",
    },
    "acciona": {
        "host": "acciona.wd3.myworkdayjobs.com",
        "tenant": "acciona",
        "site": "ACCIONA_Employment_Channel",
        "company": "ACCIONA",
        "url": "https://acciona.wd3.myworkdayjobs.com/en-US/ACCIONA_Employment_Channel/",
        "detail_base": "https://acciona.wd3.myworkdayjobs.com/en-US/ACCIONA_Employment_Channel/",
        "brazil_facet": {
            "Country": ["1a29bb1357b240ab99a2fa755cc87c0e"],
        },
    },
}

API = "https://{host}/wday/cxs/{tenant}/{site}/jobs"


def fetch_tenant(name):
    """Collect the Brazilian postings of one configured Workday tenant."""
    config = TENANTS[name]
    rows, seen = [], set()
    offset, limit = 0, 20
    while offset < 5000:
        payload = post_json(
            API.format(**config),
            {
                "appliedFacets": config.get("brazil_facet", {}),
                "limit": limit,
                "offset": offset,
                "searchText": "",
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=60,
            retries=3,
        )
        postings = payload.get("jobPostings") or []
        if not postings:
            break
        for item in postings:
            title = str(item.get("title") or "").strip()
            location = str(item.get("locationsText") or item.get("location") or "").strip()
            external = str(item.get("externalPath") or "").strip()
            native_id = str(item.get("bulletFields", [None])[0] or item.get("jobReqId") or external).strip()
            if not title or not external or not native_id or native_id in seen:
                continue
            if (
                not config.get("brazil_facet")
                and not BRAZIL_WORDS.search(location)
                and not is_brazil_location(location)
            ):
                continue
            seen.add(native_id)
            detail_base = str(config.get("detail_base") or "").strip()
            detail_url = (
                urljoin(detail_base.rstrip("/") + "/", external.lstrip("/"))
                if detail_base
                else urljoin(config["url"], external.lstrip("/"))
            )
            rows.append(job(
                name, native_id, title=title, company=config["company"],
                url=detail_url,
                work_model=work_model_label(raw=f"{title} {location}"),
                city=location or "Brasil", country="BR", market="BR",
                published_date=iso_date(item.get("postedOn") or item.get("postedDate")),
                description=strip_html(item.get("description") or ""),
            ))
        total = int(payload.get("total") or 0)
        offset += limit
        if total and offset >= total:
            break
        if len(postings) < limit:
            break
    if not rows:
        raise RuntimeError(f"Workday/{name} returned no Brazilian vacancies")
    return rows


def _fetcher(name):
    def fetch():
        return fetch_tenant(name)

    fetch.__name__ = fetch.__qualname__ = f"fetch_{name}"
    fetch.__doc__ = f"Collect {TENANTS[name]['company']} vacancies from Workday."
    return fetch


FETCHERS = {name: _fetcher(name) for name in TENANTS}
TARGETS = tuple(FETCHERS.items())
