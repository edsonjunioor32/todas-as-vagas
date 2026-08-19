# -*- coding: utf-8 -*-
"""Public career portals hosted on the TOTVS Atração de Talentos platform.

The main Vem Pra TOTVS catalog and the requested customer career pages share
the same public card/detail markup. Individual customer pages can be retired
without affecting the remaining companies or the regular portal update.
"""
import concurrent.futures
import os
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from ._common import job, strip_html, work_model_label
from ._http import get_text


BASE_URL = "https://atracaodetalentos.totvs.app"
MIN_EXPECTED_TOTVS_JOBS = 20
MAX_WORKERS = max(1, int(os.environ.get("TOTVS_WORKERS", "10")))

# The first entry is the primary, official TOTVS board. The remaining pages
# were explicitly requested and are retried on every general update.
BOARDS = {
    "vempratotvs": {"company": "TOTVS", "catalog": "extended", "required": True},
    "universoecommerce": {"company": "Universo E-commerce", "catalog": "extended"},
    "vidya": {"company": "Vidya", "catalog": "extended"},
    "grupobridger": {"company": "Grupo Bridger", "catalog": "extended"},
    "vagasolor": {"company": "Solor Tecnologia", "catalog": "extended"},
    "cesed": {"company": "CESED", "catalog": "extended"},
    "oncomed": {"company": "Oncomed", "catalog": "extended"},
    "bramoffshore": {"company": "Bram Offshore", "catalog": "extended"},
    "vagashtri": {"company": "HTRI", "catalog": "extended"},
    "trabalhenagnatus": {"company": "Gnatus", "catalog": "extended"},
    "einscricao": {"company": "eInscrição", "catalog": "extended"},
    "afin": {"company": "AFIN Assessoria Fiscal e Contábil", "catalog": "extended"},
    "vempratechfin": {"company": "Techfin", "catalog": "extended"},
    "estuda": {"company": "Estuda", "catalog": "extended"},
    "om30": {"company": "OM30", "catalog": "extended"},
    "vagaconfidencialbrasil": {"company": "Empresa confidencial", "catalog": "extended"},
    "facapartedogrupoconsulth": {"company": "Grupo Consulth", "catalog": "extended"},
    "concremat": {"company": "Concremat", "catalog": "extended"},
    "vagasavaeducacao": {"company": "AVA Educação", "catalog": "extended"},
    "selbetti": {"company": "Selbetti", "catalog": "extended"},
    "netratecnologia": {"company": "Netra Tecnologia", "catalog": "extended"},
    "vagasecomex": {"company": "eCOMEX", "catalog": "extended"},
}


class CatalogParser(HTMLParser):
    """Read only public job cards from one configured TOTVS board."""

    def __init__(self, board, company):
        super().__init__(convert_charrefs=True)
        self.board = board
        self.company = company
        self.rows = []
        self.item = None
        self.depth = 0
        self.in_job_link = False
        self.link_parts = []
        self.job_url_re = re.compile(
            rf"^https://atracaodetalentos\.totvs\.app/{re.escape(board)}/(\d+)/[^/?#]+/?$",
            re.I,
        )

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = values.get("class", "")
        if tag == "div" and self.item is None and "index__job-opportunities__grid__item" in classes:
            self.item = values
            self.depth = 1
            self.in_job_link = False
            self.link_parts = []
            return
        if self.item is None:
            return
        if tag == "div":
            self.depth += 1
        elif tag == "a" and values.get("data-cy") == "job-opportunity-link":
            href = urljoin(BASE_URL, values.get("href", ""))
            if self.job_url_re.match(href):
                self.item["job_url"] = href
                self.item["link_title"] = values.get("data-title", "")
                self.in_job_link = True

    def handle_endtag(self, tag):
        if self.item is None:
            return
        if tag == "a":
            self.in_job_link = False
        elif tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self._finish_item()

    def handle_data(self, data):
        if self.in_job_link and data.strip():
            self.link_parts.append(data.strip())

    def _finish_item(self):
        href = self.item.get("job_url", "")
        match = self.job_url_re.match(href)
        title = self.item.get("data-title") or self.item.get("link_title") or " ".join(self.link_parts)
        if match and title.strip():
            remote = self.item.get("data-hide-location", "").lower() == "true"
            city = "" if remote else self.item.get("data-city-name", "").strip()
            state = "" if remote else self.item.get("data-state-small-name", "").strip().upper()
            self.rows.append(
                job(
                    "totvs",
                    f"{self.board}:{match.group(1)}",
                    title=title.strip(),
                    company=self.company,
                    url=href,
                    work_model=work_model_label(
                        remote_flag=True if remote else None,
                        raw=title,
                    ),
                    city=city,
                    state=state,
                    country="BR",
                    market="BR",
                    pcd="pcd" in title.lower() or "pessoa com defici" in title.lower(),
                )
            )
        self.item = None
        self.depth = 0
        self.in_job_link = False
        self.link_parts = []


def _tag_text(markup, attribute_pattern):
    match = re.search(
        rf"<(?:p|div)\b(?=[^>]*{attribute_pattern})[^>]*>(.*?)</(?:p|div)>",
        markup or "",
        re.I | re.S,
    )
    return strip_html(match.group(1)) if match else ""


def _contracts(regime):
    values = []
    patterns = (
        ("CLT", r"\bclt\b"),
        ("PJ", r"\bpj\b|pessoa jur[ií]dica"),
        ("Cooperado", r"cooperad"),
        ("Freelancer", r"freelanc"),
        ("Temporário", r"tempor[aá]ri"),
        ("Estágio", r"est[aá]gio"),
        ("Aprendiz", r"aprendiz"),
    )
    for label, pattern in patterns:
        if re.search(pattern, regime or "", re.I):
            values.append(label)
    return values


def parse_detail(markup):
    subtitle = _tag_text(markup, r'class=["\'][^"\']*job-opportunity__subtitle[^"\']*["\']')
    regime = _tag_text(markup, r'data-cy=["\']mobile-regime["\']')
    work_model = work_model_label(raw=subtitle)
    city = state = ""
    for part in [value.strip() for value in subtitle.split("|")]:
        match = re.match(r"^(.+?)\s*-\s*([A-Z]{2})$", part)
        if match:
            city, state = match.group(1).strip(), match.group(2)
            break
    return {
        "work_model": work_model,
        "city": city,
        "state": state,
        "contract_types": _contracts(regime),
    }


def _enrich(row):
    try:
        details = parse_detail(get_text(row["url"], timeout=25, retries=2))
    except Exception:
        return row, False
    if details["work_model"]:
        row["work_model"] = details["work_model"]
    if details["city"]:
        row["city"] = details["city"]
        row["state"] = details["state"]
    if details["contract_types"]:
        row["contract_types"] = details["contract_types"]
    return row, bool(details["work_model"] or details["city"] or details["contract_types"])


def _catalog_url(board, config):
    suffix = config.get("catalog")
    return f"{BASE_URL}/{board}/{suffix}" if suffix else f"{BASE_URL}/{board}/"


def _fetch_board(board, config):
    parser = CatalogParser(board, config["company"])
    parser.feed(get_text(_catalog_url(board, config), timeout=45, retries=3))
    return parser.rows


def fetch():
    rows = []
    primary_rows = None

    for board, config in BOARDS.items():
        try:
            board_rows = _fetch_board(board, config)
        except Exception as error:
            if config.get("required"):
                raise RuntimeError(f"TOTVS primary catalog failed: {error}") from error
            print(f"    [totvs:{board}] {str(error)[:80]}")
            continue

        if config.get("required"):
            primary_rows = board_rows
        elif not board_rows:
            print(f"    [totvs:{board}] no active public jobs")

        rows.extend(board_rows)

    if primary_rows is None or len(primary_rows) < MIN_EXPECTED_TOTVS_JOBS:
        count = len(primary_rows or [])
        raise RuntimeError(
            f"TOTVS returned only {count} official job links; refusing a partial primary catalog"
        )

    enriched = []
    details_ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_enrich, row) for row in rows]
        for future in concurrent.futures.as_completed(futures):
            row, parsed = future.result()
            enriched.append(row)
            details_ok += int(parsed)

    if not details_ok:
        raise RuntimeError("TOTVS job details did not expose location, modality or contract type")

    return sorted(enriched, key=lambda row: (row["company"].casefold(), row["native_id"]))
