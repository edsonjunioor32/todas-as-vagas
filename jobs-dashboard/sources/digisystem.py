# -*- coding: utf-8 -*-
"""Digisystem careers hosted on the public Recrutei listing."""
from . import recrutei


def fetch():
    """Read Digisystem from Recrutei's current public feed.

    The former jobs.recrutei.com.br/digisystem endpoint no longer renders
    vacancy cards. Recrutei now publishes active listings at
    empregos.recrutei.com.br/vaga/digisystem/<id>-<title>.
    """
    rows = []
    for row in recrutei._public_rows():
        if str(row.get("company") or "").casefold() != "digisystem":
            continue
        row = dict(row)
        row["source"] = "digisystem"
        row["native_id"] = f"recrutei:{row['native_id']}"
        rows.append(row)
    if not rows:
        raise RuntimeError("Digisystem has no active cards in Recrutei's public feed")
    return rows
