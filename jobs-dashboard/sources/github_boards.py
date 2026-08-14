# -*- coding: utf-8 -*-
"""Public Brazilian job boards maintained as GitHub Issues.

Each repository below is a community board where an open issue represents an
active vacancy. The GitHub REST endpoint is public and stable; failures in an
individual board are isolated so the full collection remains available.
"""
from ._common import iso_date, strip_html, work_model_label, job
from ._http import get_json

REPOSITORIES = [
    "backend-br/vagas",
    "frontendbr/vagas",
    "react-brasil/vagas",
    "vuejs-br/vagas",
    "NestBR/vagas",
    "programadores-br/geral",
    "Empregos-dev/Vagas-dev",
    "techmagiccube/vagas",
    "seujobtech/vagas",
    "CangaceirosDevels/vagas_de_emprego",
    "devfsa/vagas",
    "developersRJ/vagas",
    "devmatogrosso/vagas",
]
API = "https://api.github.com/repos/{repo}/issues?state=open&sort=created&direction=desc&per_page=100"
HEADERS = {"Accept": "application/vnd.github+json"}


def _location(labels):
    values = [str(label.get("name") or "").strip() for label in labels or []]
    return " · ".join(value for value in values if value)


def fetch():
    rows = []
    for repository in REPOSITORIES:
        try:
            issues = get_json(API.format(repo=repository), headers=HEADERS, timeout=30, retries=2)
        except Exception as error:
            print(f"    [github:{repository}] {str(error)[:60]}")
            continue
        for issue in issues if isinstance(issues, list) else []:
            # The issues endpoint can also list pull requests; only vacancies count.
            if issue.get("pull_request"):
                continue
            labels = issue.get("labels") or []
            location = _location(labels)
            title = str(issue.get("title") or "").strip()
            rows.append(job(
                "github",
                f"{repository}#{issue.get('number') or issue.get('id')}",
                title=title,
                company=repository.split("/")[0],
                url=issue.get("html_url", ""),
                work_model=work_model_label(raw=f"{title} {location}"),
                city=location,
                country="BR",
                market="BR",
                published_date=iso_date(issue.get("created_at")),
                skills=[str(label.get("name") or "").strip() for label in labels
                        if str(label.get("name") or "").strip()][:20],
                description=strip_html(issue.get("body", "")),
                categories=["Vagas no GitHub"],
                contract_types=[str(label.get("name") or "").strip() for label in labels
                                if str(label.get("name") or "").strip()
                                and str(label.get("name") or "").strip().upper() in {"CLT", "PJ", "COOPERADO"}],
            ))
    return rows
