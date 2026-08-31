# -*- coding: utf-8 -*-
"""Validate the requested dynamic career feeds without writing the catalogue.

This command is intentionally independent from ``pipeline_fit.py``.  It makes
one live request to each repaired adapter, checks that the
response contains usable vacancy records, and exits non-zero on an empty or
malformed source.  The isolated workflow can therefore be run while the main
catalogue remains untouched.
"""
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources import (  # noqa: E402
    bradesco,
    digisystem,
    experian,
    geekhunter,
    quickin,
    levva,
    requested_careers,
    requested_portals_27082026,
    requested_portals_28082026,
    requested_portals_29082026,
    sankhya_senior,
    spassu,
)


SOURCES = (("levva", levva.fetch),) + requested_portals_29082026.TARGETS + (
    ("bradesco", bradesco.fetch),
    ("nttdata", geekhunter.fetch_ntt_data),
) + requested_portals_28082026.TARGETS + (
    ("digisystem", digisystem.fetch),
    ("docusign", requested_careers.fetch_docusign),
    ("dbccompany", requested_careers.fetch_dbccompany),
    ("sankhya", sankhya_senior.fetch_sankhya),
    ("senior", sankhya_senior.fetch_senior),
    ("experian", experian.fetch),
    ("spassu", spassu.fetch),
    ("infovagas", quickin.fetch),
) + requested_portals_27082026.TARGETS


def _validate_rows(name, rows):
    if not rows:
        raise RuntimeError("a fonte retornou zero vagas")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("a fonte retornou um registro que não é objeto")
        native_id = str(row.get("native_id") or "").strip()
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not native_id or not title or not url:
            raise RuntimeError("há vaga sem native_id, título ou URL")
        if native_id in seen:
            raise RuntimeError(f"native_id duplicado: {native_id}")
        seen.add(native_id)
        if row.get("source") != name:
            raise RuntimeError(f"registro {native_id} está marcado como {row.get('source')!r}")
    return len(seen)


def main():
    failures = []
    for name, fetch in SOURCES:
        started = time.monotonic()
        try:
            count = _validate_rows(name, fetch())
        except Exception as error:  # keep every diagnostic in one run
            failures.append((name, error))
            print(f"[{name}] FALHA: {error}", flush=True)
            continue
        elapsed = time.monotonic() - started
        print(f"[{name}] ok       {count} vagas ({elapsed:.1f}s)", flush=True)

    if failures:
        print(f"{len(failures)} fonte(s) falharam; nenhuma coleta geral foi executada.", flush=True)
        return 1
    print("Todos os portais dinâmicos foram validados isoladamente.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
