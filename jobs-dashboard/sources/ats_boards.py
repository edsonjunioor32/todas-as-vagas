# -*- coding: utf-8 -*-
"""ATS job boards — Greenhouse, Lever and Ashby all expose a public, key-free
JSON board per company. We pull from a curated list of companies (each slug
verified to respond), capped per company so no single board floods the dataset.

Adds named-company variety and depth on top of the aggregators. Extend the lists
below with any company slug that returns jobs on its ATS.
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from ._http import get_json
from ._common import strip_html, iso_date, work_model_label, is_brazil_location, job

PER_COMPANY = 120   # cap for global Lever/Ashby boards

# Boards explicitly requested by the project owner.  The generic downstream
# two-month cutoff applies to their publication dates as well.
LEVER = ["spotify", "veeva", "ciandt"]
ASHBY = ["openai", "ramp", "notion", "replit", "watershed", "linear", "nubank"]

HERE = Path(__file__).resolve().parent
GREENHOUSE_BR_CATALOG = HERE.parent / "data" / "greenhouse_br_companies.json"
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=false"
GREENHOUSE_API_FALLBACK = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
GREENHOUSE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
    "Cache-Control": "no-cache",
    "Referer": "https://boards.greenhouse.io/",
}
GREENHOUSE_BROWSER_HEADERS = {
    **GREENHOUSE_HEADERS,
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}
# Boards requested explicitly by the project owner must not depend on the
# external discovery catalog. ``brazil_only`` is limited to boards whose live
# catalog was verified to contain only Brazilian locations; it lets values such
# as "Remoto", "Barueri/SP" and "Paraná" pass the country filter.
# iFood (ifoodcarreiras) is guaranteed separately as a named source in
# company_careers.py, avoiding duplicate rows under the generic Greenhouse tag.
REQUIRED_GREENHOUSE_BOARDS = {
    "c6bank": {"company": "C6 Bank"},
    "bees": {"company": "BEES"},
    "abinbev": {"company": "AB InBev | Growth Group"},
    "clara": {"company": "Clara"},
    "exame": {"company": "EXAME", "brazil_only": True},
    "xpinc": {"company": "XP Inc.", "brazil_only": True},
    "sertradingsa": {"company": "SERTRADING", "brazil_only": True},
    "elo": {"company": "Elo", "brazil_only": True},
    "arcoeducacao": {"company": "Arco Educação", "brazil_only": True},
    "gympass": {"company": "Wellhub"},
    "ilia": {"company": "ília", "brazil_only": True},
    "jusbrasil": {"company": "Jusbrasil", "brazil_only": True},
    "getnet": {"company": "Getnet"},
    "agilize": {"company": "Agilize", "brazil_only": True},
    "inter": {"company": "Inter"},
}
# Keep these boards under continuous observation even when the strict catalog
# correctly contains no Brazilian vacancy today. If they open a Brazil
# position later, the normal collector will include it automatically.
MONITORED_GREENHOUSE_BOARDS = {
    "accenturefederalservices": {"company": "Accenture Federal Services"},
    "actpowerservices": {"company": "ACT Power Services"},
    "abiologics": {"company": "Abiologics"},
    "abclegalservices": {"company": "ABC Legal Services"},
    "abarca": {"company": "Abarca Health"},
    "1910genetics": {"company": "1910"},
}
PCD_PATTERN = re.compile(r"\bpcd\b|pessoa(?:s)?\s+com\s+defici", re.I)


class GreenhouseCollectionError(RuntimeError):
    """A partial Greenhouse result that must preserve the prior snapshot."""

    def __init__(self, message, rows=None, failed_boards=None):
        super().__init__(message)
        self.rows = list(rows or [])
        self.failed_boards = list(failed_boards or [])


def _market(loc):
    t = (loc or "").lower()
    if any(k in t for k in ("bras", "brazil", "são paulo", "sao paulo", "rio de janeiro",
                            "belo horizonte", "curitiba", "porto alegre")):
        return "BR", "BR"
    if any(k in t for k in ("remote", "anywhere", "distributed")):
        return loc, "Global remote"
    return loc, "Global"


def fetch_greenhouse():
    with open(GREENHOUSE_BR_CATALOG, encoding="utf-8") as handle:
        configs = json.load(handle).get("companies") or []
    configured = {
        str(config.get("board") or "").strip(): config
        for config in configs
        if str(config.get("board") or "").strip()
    }
    for board, required in REQUIRED_GREENHOUSE_BOARDS.items():
        config = configured.get(board)
        if config is None:
            config = {"board": board}
            configs.append(config)
            configured[board] = config
        for name, value in required.items():
            config.setdefault(name, value)
    for board, monitored in MONITORED_GREENHOUSE_BOARDS.items():
        config = configured.get(board)
        if config is None:
            config = {"board": board}
            configs.append(config)
            configured[board] = config
        for name, value in monitored.items():
            config.setdefault(name, value)

    def request_board(board):
        """Use two public URL forms and browser-like negotiation headers."""
        attempts = (
            (GREENHOUSE_API, GREENHOUSE_HEADERS),
            (GREENHOUSE_API_FALLBACK, GREENHOUSE_HEADERS),
            (GREENHOUSE_API, GREENHOUSE_BROWSER_HEADERS),
        )
        last_error = None
        for endpoint, headers in attempts:
            try:
                return get_json(
                    endpoint.format(board=board),
                    headers=headers,
                    timeout=35,
                    retries=2,
                    backoff=1.0,
                    retry_http_codes={406},
                )
            except Exception as error:
                last_error = error
        raise last_error or RuntimeError("Greenhouse returned no response")

    def accepts_location(loc, config):
        if is_brazil_location(loc):
            return True
        # A small, explicit exception is retained for known Brazil-only boards
        # whose API reports only a generic nationwide location. It does not
        # allow arbitrary foreign locations through the filter.
        return config.get("brazil_only") and str(loc or "").strip().casefold() in {
            "brasil", "brazil", "remoto", "remote", "todo brasil", "nationwide - brazil",
        }

    def fetch_board(config):
        board = config["board"]
        payload = request_board(board)
        rows = []
        for item in payload.get("jobs") or []:
            loc = str((item.get("location") or {}).get("name") or "").strip()
            if not accepts_location(loc, config):
                continue
            depts = [d.get("name", "") for d in (item.get("departments") or [])]
            metadata = item.get("metadata") or []
            contracts = []
            for field in metadata:
                name = str(field.get("name") or "").strip().rstrip(":").casefold()
                if name not in {"tipo de contrato", "employment type", "contract type"}:
                    continue
                value = field.get("value")
                contracts.extend(value if isinstance(value, list) else [value])
            title = item.get("title", "")
            rows.append(job(
                "greenhouse", item.get("id") or item.get("internal_job_id"),
                title=title,
                company=item.get("company_name") or config.get("company") or board,
                url=item.get("absolute_url", ""),
                work_model=work_model_label(raw=f"{title} {loc}"),
                city=loc,
                country="BR",
                market="BR",
                published_date=iso_date(item.get("first_published") or item.get("updated_at")),
                expires_date=iso_date(item.get("application_deadline")),
                categories=[d for d in depts if d],
                contract_types=[str(value).strip() for value in contracts if str(value or "").strip()],
                pcd=bool(PCD_PATTERN.search(title)),
            ))
        return board, rows

    out = []
    failed_boards = []
    empty_required_boards = []
    workers = min(8, max(1, int(os.environ.get("GREENHOUSE_WORKERS", "4"))))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_board, config): config for config in configs}
        for future in as_completed(futures):
            config = futures[future]
            try:
                board, rows = future.result()
                if board in REQUIRED_GREENHOUSE_BOARDS and not rows:
                    empty_required_boards.append(board)
                    print(f"    [gh:{board}] required board returned zero Brazilian vacancies")
                else:
                    out.extend(rows)
            except Exception as error:
                board = config.get("board")
                failed_boards.append(board)
                print(f"    [gh:{board}] {str(error)[:100]}")
    failed_boards.extend(empty_required_boards)
    if failed_boards:
        failed_boards.sort()
        sample = ", ".join(failed_boards[:12])
        suffix = "..." if len(failed_boards) > 12 else ""
        raise GreenhouseCollectionError(
            f"{len(failed_boards)} Greenhouse boards failed; "
            f"successful rows were retained ({sample}{suffix})",
            rows=out,
            failed_boards=failed_boards,
        )
    return out


def fetch_lever():
    out = []
    for c in LEVER:
        try:
            jobs = get_json(f"https://api.lever.co/v0/postings/{c}?mode=json")
        except Exception as e:
            print(f"    [lever:{c}] {str(e)[:40]}"); continue
        for j in (jobs if isinstance(jobs, list) else [])[:PER_COMPANY]:
            cats = j.get("categories", {}) or {}
            loc = cats.get("location", "")
            country, market = _market(loc)
            out.append(job("lever", j.get("id"),
                title=j.get("text", ""), company={"ciandt": "CI&T"}.get(c, c.title()),
                url=j.get("hostedUrl", ""), work_model=work_model_label(raw=cats.get("commitment", "") + " " + loc),
                city=loc, country=country, market=market,
                published_date=iso_date(j.get("createdAt")),
                categories=[cats.get("department") or cats.get("team") or ""]))
        time.sleep(0.2)
    return out


def fetch_ashby():
    out = []
    for c in ASHBY:
        try:
            jobs = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{c}").get("jobs", [])
        except Exception as e:
            print(f"    [ashby:{c}] {str(e)[:40]}"); continue
        for j in jobs[:PER_COMPANY]:
            loc = j.get("location", "") or j.get("locationName", "")
            country, market = _market(loc)
            remote = bool(j.get("isRemote"))
            out.append(job("ashby", j.get("id") or j.get("jobId"),
                title=j.get("title", ""), company={"nubank": "Nubank"}.get(c, c.title()),
                url=j.get("jobUrl") or j.get("applyUrl", ""),
                work_model="remote" if remote else work_model_label(raw=loc),
                city=loc, country=country, market="Global remote" if remote else market,
                published_date=iso_date(j.get("publishedAt")),
                categories=[j.get("department", "") or j.get("teamName", "")]))
        time.sleep(0.2)
    return out
