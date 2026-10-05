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


def validate_entry(url, entry, term_count):
    """Return the existing validation error for one fit entry, if any."""
    if not str(url).startswith("https://"):
        return f"URL inválida no índice: {url}"
    if not isinstance(entry, dict) or set(entry) - ALLOWED_ENTRY_KEYS:
        return f"estrutura de requisitos inválida: {url}"
    try:
        confidence = int(entry.get("q") or 0)
    except (TypeError, ValueError):
        return f"confiança inválida: {url}"
    if not 0 <= confidence <= 100:
        return f"confiança fora de 0-100: {url}"
    for key in ("m", "p", "c", "x"):
        values = entry.get(key) or []
        if not isinstance(values, list):
            return f"campo {key} inválido: {url}"
        for index in values:
            if not isinstance(index, int) or not 0 <= index < term_count:
                return f"índice de termo inválido em {url}"
    for key, limit in META_LIMITS.items():
        value = str(entry.get(key) or "")
        if len(value) > limit:
            return f"metadado {key} longo demais: {url}"
        if "description" in value.casefold() or len(value.split()) > 28:
            return f"metadado {key} parece conter texto indevido: {url}"
    return None


def quarantine_pii_terms(payload):
    """Remove PII-like vocabulary items and safely reindex every fit entry."""
    terms = payload.get("terms")
    jobs = payload.get("jobs")
    if not isinstance(terms, list) or not isinstance(jobs, dict):
        raise ValueError("terms/jobs inválidos antes da quarentena de PII")

    remap = []
    safe_terms = []
    removed_terms = 0
    for term in terms:
        value = str(term)
        if EMAIL.search(value) or PHONE.search(value):
            remap.append(None)
            removed_terms += 1
        else:
            remap.append(len(safe_terms))
            safe_terms.append(term)

    safe_jobs = {}
    removed_references = 0
    removed_entries = 0
    for url, entry in jobs.items():
        if not isinstance(entry, dict):
            safe_jobs[url] = entry
            continue
        clean_entry = dict(entry)
        entry_removed_references = 0
        for key in ("m", "p", "c", "x"):
            values = clean_entry.get(key)
            if not isinstance(values, list):
                continue
            clean_values = []
            for index in values:
                if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(remap):
                    replacement = remap[index]
                    if replacement is None:
                        removed_references += 1
                        entry_removed_references += 1
                        continue
                    clean_values.append(replacement)
                else:
                    # Preserve malformed references so validate_entry can
                    # quarantine the affected row instead of hiding the defect.
                    clean_values.append(index)
            clean_entry[key] = clean_values

        if entry_removed_references and not any(
            clean_entry.get(key) for key in ("m", "p", "c", "x")
        ):
            removed_entries += 1
            continue
        safe_jobs[url] = clean_entry

    updated = dict(payload)
    updated["terms"] = safe_terms
    updated["jobs"] = safe_jobs
    updated["count"] = len(safe_jobs)
    return updated, {
        "terms": removed_terms,
        "references": removed_references,
        "entries": removed_entries,
    }


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
        error = validate_entry(url, entry, len(terms))
        if error:
            fail(error)
    print(f"OK: índice de aderência com {len(jobs)} vagas, {len(terms)} termos, sem descrições/PII")


if __name__ == "__main__":
    main()
