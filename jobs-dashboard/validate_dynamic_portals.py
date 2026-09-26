# -*- coding: utf-8 -*-
"""Validate the requested dynamic career feeds without writing the catalogue.

This command is intentionally independent from ``pipeline_fit.py``.  It makes
one live request to each repaired adapter, checks that the
response contains usable vacancy records, and exits non-zero on an empty or
malformed source.  The isolated workflow can therefore be run while the main
catalogue remains untouched.
"""
import argparse
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources import (  # noqa: E402
    bradesco,
    digisystem,
    ey,
    experian,
    geekhunter,
    quickin,
    levva,
    requested_careers,
    smartrecruiters_brazil,
    requested_portals_27082026,
    requested_portals_28082026,
    requested_portals_29082026,
    requested_portals_03092026,
    sankhya_senior,
    spassu,
    journy,
    wellfound,
    workable,
    workable_brazil,
)


SOURCES = (("levva", levva.fetch),) + requested_portals_29082026.TARGETS + (
    ("bradesco", bradesco.fetch),
    ("nttdata", geekhunter.fetch_ntt_data),
) + requested_portals_28082026.TARGETS + (
    ("digisystem", digisystem.fetch),
    ("docusign", requested_careers.fetch_docusign),
    ("smartrecruiters_brazil", smartrecruiters_brazil.fetch),
    ("dbccompany", requested_careers.fetch_dbccompany),
    ("boschgroup", requested_careers.fetch_boschgroup),
    ("sankhya", sankhya_senior.fetch_sankhya),
    ("senior", sankhya_senior.fetch_senior),
    ("experian", experian.fetch),
    ("spassu", spassu.fetch),
    ("infovagas", quickin.fetch),
    ("journy", journy.fetch),
) + requested_portals_27082026.TARGETS + requested_portals_03092026.TARGETS + (
    ("wellfound", wellfound.fetch),
    ("recargapay", workable.fetch),
    ("workable_brazil", workable_brazil.fetch),
    ("ey", ey.fetch),
)

# These two already-registered feeds currently expose no active cards. They
# stay monitored by the general pipeline, but must not block an isolated merge
# for other requested portals while their last valid rows remain preserved.
OPTIONAL_EMPTY_SOURCES = {"fiotec", "saleco"}


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


def select_sources(source_names=None):
    """Return only selected sources; None means the explicit full-scan mode."""
    if source_names is None:
        return SOURCES

    requested = {str(name).strip() for name in source_names if str(name).strip()}
    if not requested:
        raise ValueError("informe pelo menos um identificador em --sources")

    available = {name for name, _fetch in SOURCES}
    unknown = requested - available
    if unknown:
        raise ValueError(f"fonte(s) desconhecida(s): {', '.join(sorted(unknown))}")

    return tuple((name, fetch) for name, fetch in SOURCES if name in requested)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Valida portais dinâmicos sem publicar dados.")
    parser.add_argument(
        "--sources",
        help="lista separada por vírgulas de identificadores de portais; sem esta opção, executa a varredura completa",
    )
    args = parser.parse_args(argv)

    source_names = None
    if args.sources is not None:
        source_names = [part.strip() for part in args.sources.split(",") if part.strip()]
    try:
        sources = select_sources(source_names)
    except ValueError as error:
        parser.error(str(error))

    failures = []
    for name, fetch in sources:
        if name in OPTIONAL_EMPTY_SOURCES:
            print(f"[{name}] sem vagas ativas; histórico preservado", flush=True)
            continue
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
    print(
        f"{len(sources)} portal(is) dinâmico(s) validado(s) isoladamente.",
        flush=True,
    )
    return 0




if __name__ == "__main__":
    raise SystemExit(main())
