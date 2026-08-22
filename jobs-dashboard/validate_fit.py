# -*- coding: utf-8 -*-
"""Valida o índice público de aderência sem permitir vazamento de descrição ou PII."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIT = ROOT / "docs" / "data" / "fit.json"
TAXONOMY = ROOT / "docs" / "data" / "fit-taxonomy.json"
ALLOWED_ENTRY_KEYS = {"m", "p", "c", "x", "q", "t", "e", "l", "w", "d"}
META_LIMITS = {"t": 180, "e": 140, "l": 120, "w": 40, "d": 40}
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE = re.compile(r"(?:\+?\d[\s().-]*){9,}")


def fail(message):
    print(f"ERRO: {message}", file=sys.stderr)
    raise SystemExit(1)


def main():
    if not FIT.exists() or not TAXONOMY.exists():
        fail("fit.json ou fit-taxonomy.json ausente")
    data = json.loads(FIT.read_text(encoding="utf-8"))
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        fail("schema_version do fit.json inválido")
    if taxonomy.get("schema_version") != 1 or not isinstance(taxonomy.get("entries"), list):
        fail("taxonomia inválida")
    terms = data.get("terms")
    jobs = data.get("jobs")
    if not isinstance(terms, list) or not isinstance(jobs, dict):
        fail("terms/jobs inválidos")
    if int(data.get("count") or 0) != len(jobs):
        fail("count divergente no fit.json")
    for term in terms:
        text = str(term)
        if len(text) > 80:
            fail(f"termo longo demais: {text[:30]}")
        if EMAIL.search(text) or PHONE.search(text):
            fail("termo parece conter PII")
        if len(text.split()) > 12:
            fail("termo se parece com trecho de descrição")
    for url, entry in jobs.items():
        if not str(url).startswith("https://"):
            fail(f"URL inválida no índice: {url}")
        if not isinstance(entry, dict) or set(entry) - ALLOWED_ENTRY_KEYS:
            fail(f"estrutura de requisitos inválida: {url}")
        confidence = int(entry.get("q") or 0)
        if not 0 <= confidence <= 100:
            fail(f"confiança fora de 0-100: {url}")
        for key in ("m", "p", "c", "x"):
            values = entry.get(key) or []
            if not isinstance(values, list):
                fail(f"campo {key} inválido: {url}")
            for index in values:
                if not isinstance(index, int) or not 0 <= index < len(terms):
                    fail(f"índice de termo inválido em {url}")
        for key, limit in META_LIMITS.items():
            value = str(entry.get(key) or "")
            if len(value) > limit:
                fail(f"metadado {key} longo demais: {url}")
            if "description" in value.casefold() or len(value.split()) > 28:
                fail(f"metadado {key} parece conter texto indevido: {url}")
    print(f"OK: índice de aderência com {len(jobs)} vagas, {len(terms)} termos, sem descrições/PII")


if __name__ == "__main__":
    main()
