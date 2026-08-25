# -*- coding: utf-8 -*-
"""Run an isolated Sólides cache benchmark without touching the catalogue.

The command calls only the Sólides adapter.  Running it twice in the same
workspace makes the second pass conditional (304) for pages already cached;
no database, public JSON, or Telegram notification is produced.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources import solides  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--pages", type=int, default=24)
    args = parser.parse_args()
    if args.runs < 1 or args.pages < 1:
        raise SystemExit("--runs e --pages devem ser positivos")

    os.environ["SOLIDES_MAX_PAGES"] = str(args.pages)
    results = []
    for run in range(1, args.runs + 1):
        started = time.monotonic()
        rows = solides.fetch()
        elapsed = time.monotonic() - started
        result = {"run": run, "pages": args.pages, "jobs": len(rows), "seconds": round(elapsed, 2)}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    if len(results) >= 2 and results[-1]["seconds"] > results[0]["seconds"] * 1.5:
        print(
            "Aviso: a segunda passagem não ficou mais rápida; "
            "o endpoint pode ter ignorado os validadores nesta execução.",
            flush=True,
        )
    print("Benchmark isolado concluído; nenhum catálogo foi escrito.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
