# -*- coding: utf-8 -*-
"""InHire adapter over the concurrent tenant collector already used by the site.

The Node collector writes a temporary public-safe JSON file. This adapter maps
that file into the same schema as every other portal without copying job
descriptions into the multi-portal dataset.
"""
import json
import os
from pathlib import Path

from ._common import iso_date, job, split_location, work_model_label

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "inhire" / "vagas.json"


def fetch():
    source_path = Path(os.environ.get("INHIRE_JSON") or DEFAULT_PATH)
    if not source_path.exists():
        raise FileNotFoundError(f"InHire staging file not found: {source_path}")

    rows = json.loads(source_path.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list):
        raise ValueError("InHire staging file must contain a JSON array")

    out = []
    for item in rows:
        location = str(item.get("location") or "")
        _, state, country = split_location(location)
        if not country and any(token in location.lower() for token in ("brasil", "brazil", " - br")):
            country = "BR"
        out.append(job(
            "inhire",
            item.get("id") or item.get("url"),
            title=item.get("title", ""),
            company=item.get("company", ""),
            url=item.get("url", ""),
            work_model=work_model_label(raw=item.get("workplaceType")),
            city=location,
            state=state,
            country=country or "BR",
            market="BR",
            published_date=iso_date(item.get("lastPublishedAt") or item.get("publishedAt") or item.get("updatedAt")),
            contract_types=[str(x) for x in (item.get("contractTypes") or []) if x],
            levels=[item.get("seniority", "")] if item.get("seniority") else [],
            categories=[item.get("category", "")] if item.get("category") else [],
        ))
    return out
