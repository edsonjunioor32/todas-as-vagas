# -*- coding: utf-8 -*-
"""Extrai um índice compacto de requisitos sem publicar descrições completas."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "docs" / "data" / "fit-taxonomy.json"
MIN_DESCRIPTION_CHARS = 120

MANDATORY_MARKERS = (
    "requisitos e qualificacoes", "requisitos", "qualificacoes", "requirements", "must have", "must-have",
    "voce precisa ter", "para se juntar", "esperamos que voce tenha", "o que buscamos", "perfil desejado",
    "requisitos obrigatorios", "obrigatorio",
)
PREFERRED_MARKERS = (
    "diferenciais", "diferencial", "sera um diferencial", "seria muito legal se tivesse", "desejavel",
    "desejaveis", "nice to have", "nice-to-have", "preferred", "seria um plus", "e um plus", "bonus",
)
STOP_MARKERS = (
    "beneficios", "informacoes adicionais", "o que oferecemos", "what we offer", "benefits", "sobre a empresa", "about us",
)
MANDATORY_CUES = (
    "experiencia com", "experiencia em", "conhecimento em", "conhecimentos em", "dominio de", "vivencia com",
    "vivencia em", "familiaridade com", "proficiencia em", "experience with", "experience in", "knowledge of",
    "proficiency in", "required",
)
PREFERRED_CUES = ("diferencial", "desejavel", "nice to have", "preferred", "plus", "seria legal", "seria muito legal")
GENERIC_STOP = {
    "experiencia", "conhecimento", "conhecimentos", "dominio", "vivencia", "familiaridade", "boa", "bom", "forte",
    "capacidade", "habilidade", "perfil", "atuacao", "area", "sistemas", "sistema", "ferramentas", "ferramenta",
    "tecnologia", "tecnologias", "processos", "processo", "ambiente", "ambientes", "clientes", "cliente", "time",
    "equipe", "dados", "aplicacoes", "solucoes", "gestao", "suporte", "desenvolvimento", "trabalho", "uso", "nivel",
    "leitura", "interpretacao", "analise",
}


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def _pattern(token: str) -> re.Pattern:
    token = normalize(token)
    if len(token) <= 4 or any(ch in token for ch in ".#+/-"):
        left = r"(?<![a-z0-9/])" if token == "sql" else r"(?<![a-z0-9])"
        return re.compile(rf"{left}{re.escape(token)}(?![a-z0-9])")
    return re.compile(re.escape(token))


def _contains(text: str, alias: str) -> bool:
    token = normalize(alias)
    return bool(token and _pattern(token).search(normalize(text)))


def load_taxonomy(path=None) -> dict:
    target = Path(path) if path else DEFAULT_TAXONOMY_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if int(data.get("schema_version") or 0) != 1 or not isinstance(data.get("entries"), list):
        raise ValueError("fit taxonomy schema inválido")
    return data


def _first_marker(text: str, markers, start=0):
    found = []
    for marker in markers:
        match = _pattern(marker).search(text[start:])
        if match:
            found.append((start + match.start(), start + match.end()))
    return min(found, default=None, key=lambda item: item[0])


def split_sections(description: str) -> dict:
    text = normalize(description)
    mandatory_pos = _first_marker(text, MANDATORY_MARKERS)
    preferred_pos = _first_marker(text, PREFERRED_MARKERS)
    stop_positions = [pos[0] for marker in STOP_MARKERS if (pos := _first_marker(text, (marker,)))]
    mandatory_range = preferred_range = None
    if mandatory_pos:
        ends = [x for x in stop_positions if x > mandatory_pos[1]]
        if preferred_pos and preferred_pos[0] > mandatory_pos[1]:
            ends.append(preferred_pos[0])
        mandatory_range = (mandatory_pos[1], min(ends) if ends else len(text))
    if preferred_pos:
        ends = [x for x in stop_positions if x > preferred_pos[1]]
        preferred_range = (preferred_pos[1], min(ends) if ends else len(text))
    return {
        "all": text,
        "mandatory_range": mandatory_range,
        "preferred_range": preferred_range,
        "preferred_marker_start": preferred_pos[0] if preferred_pos else None,
        "has_mandatory_section": bool(mandatory_pos),
    }


def _context_kind(text: str, position: int) -> str:
    before = normalize(text[max(0, position - 520):position])
    preferred_section = max((before.rfind(normalize(x)) for x in PREFERRED_MARKERS), default=-1)
    mandatory_section = max((before.rfind(normalize(x)) for x in MANDATORY_MARKERS), default=-1)
    if preferred_section > mandatory_section and preferred_section >= 0:
        return "preferred"
    if mandatory_section >= 0:
        return "mandatory"
    preferred_cue = max((before.rfind(normalize(x)) for x in PREFERRED_CUES), default=-1)
    mandatory_cue = max((before.rfind(normalize(x)) for x in MANDATORY_CUES), default=-1)
    if preferred_cue > mandatory_cue and preferred_cue >= 0:
        return "preferred"
    return "mandatory" if mandatory_cue >= 0 else "context"


def _classify_entry(entry: dict, sections: dict, skills_text: str) -> str:
    aliases = entry.get("aliases") or []
    if entry.get("kind") == "manual":
        return "manual" if any(_contains(sections["all"], alias) for alias in aliases) else ""
    kinds = []
    for alias in aliases:
        for match in _pattern(alias).finditer(sections["all"]):
            pos = match.start()
            mr, pr = sections.get("mandatory_range"), sections.get("preferred_range")
            if pr and pr[0] <= pos < pr[1]:
                kinds.append("preferred")
            elif mr and mr[0] <= pos < mr[1]:
                marker = sections.get("preferred_marker_start")
                tail = sections["all"][match.end():marker] if marker and pos < marker else ""
                kinds.append("preferred" if tail and len(tail) <= 120 and not re.search(r"[.!?]", tail) else "mandatory")
            else:
                kinds.append(_context_kind(sections["all"], pos))
    if "mandatory" in kinds:
        return "mandatory"
    if "preferred" in kinds:
        return "preferred"
    if skills_text and any(_contains(skills_text, alias) for alias in aliases):
        return "mandatory"
    return "context" if kinds else ""


def _meaningful(fragment: str) -> bool:
    clean = normalize(fragment).strip(" -:/()")
    if not 2 <= len(clean) <= 72:
        return False
    words = re.findall(r"[a-z0-9+#./-]+", clean)
    informative = [word for word in words if word not in GENERIC_STOP and len(word) > 1]
    if not informative or len(words) > 7:
        return False
    return len(words) < 5 or any(re.search(r"[+#./0-9]", word) for word in words)


def _unknown_fragments(description: str, taxonomy: dict):
    pattern = re.compile(
        r"(?:experi[eê]ncia|conhecimento(?:s)?|dom[ií]nio|viv[eê]ncia|familiaridade|profici[eê]ncia)"
        r"\s+(?:com|em|de)\s+([^.;:\n]{2,170})", re.I,
    )
    entries = taxonomy.get("entries") or []
    found = []
    for match in pattern.finditer(description or ""):
        kind = _context_kind(description, match.start())
        kind = "mandatory" if kind == "context" else kind
        for part in re.split(r"\s*(?:,|;|\be\b|\band\b|\bou\b|\bor\b)\s*", match.group(1), flags=re.I):
            part = re.sub(r"^(?:bons?|boas?|forte|s[oó]lidos?|avançad[oa]s?|b[aá]sic[oa]s?)\s+", "", part.strip(), flags=re.I).strip(" -:/()")
            if not _meaningful(part):
                continue
            if any(any(_contains(part, alias) for alias in entry.get("aliases") or []) for entry in entries):
                continue
            if all(normalize(part) != normalize(existing[0]) for existing in found):
                found.append((part[:72], kind))
        if len(found) >= 10:
            break
    return found


def extract_requirements(job: dict, taxonomy: dict | None = None) -> dict:
    taxonomy = taxonomy or load_taxonomy()
    description = str(job.get("description") or "")
    skills = job.get("skills") or []
    skills_text = " ".join(str(x) for x in skills) if isinstance(skills, (list, tuple, set)) else str(skills)
    sections = split_sections(description)
    groups = {"mandatory": [], "preferred": [], "context": [], "manual": []}
    for entry in taxonomy.get("entries") or []:
        kind = _classify_entry(entry, sections, skills_text)
        label = entry.get("label") or entry.get("id")
        if kind and label and label not in groups[kind]:
            groups[kind].append(label)
    for label, kind in _unknown_fragments(description, taxonomy):
        if label not in groups[kind]:
            groups[kind].append(label)
    mandatory = {normalize(x) for x in groups["mandatory"]}
    groups["preferred"] = [x for x in groups["preferred"] if normalize(x) not in mandatory]
    known = mandatory | {normalize(x) for x in groups["preferred"]}
    groups["context"] = [x for x in groups["context"] if normalize(x) not in known]
    if "PL/SQL" in groups["mandatory"] and "SQL" in groups["mandatory"] and not _contains(description.replace("PL/SQL", ""), "SQL"):
        groups["mandatory"].remove("SQL")
    groups["mandatory"] = groups["mandatory"][:18]
    groups["preferred"] = groups["preferred"][:12]
    groups["context"] = groups["context"][:10]
    groups["manual"] = groups["manual"][:6]
    extracted = sum(len(groups[k]) for k in ("mandatory", "preferred", "context"))
    if sections["has_mandatory_section"] and len(groups["mandatory"]) >= 3:
        confidence = 95
    elif sections["has_mandatory_section"] and extracted >= 2:
        confidence = 85
    elif skills_text and extracted >= 2:
        confidence = 75
    elif extracted >= 3:
        confidence = 65
    elif extracted:
        confidence = 45
    else:
        confidence = 20
    return {**groups, "confidence": confidence}


def export_fit_index(rows, out_path, taxonomy_path=None, max_raw_mb=16.0):
    taxonomy = load_taxonomy(taxonomy_path)
    terms, term_index, jobs = [], {}, {}
    def code(label):
        key = normalize(label)
        if key not in term_index:
            term_index[key] = len(terms)
            terms.append(label)
        return term_index[key]
    for job in rows:
        url = str(job.get("url") or "").strip().replace("http://", "https://", 1)
        if not url:
            continue
        description = normalize(job.get("description") or "")
        if len(description) < MIN_DESCRIPTION_CHARS:
            continue
        result = extract_requirements(job, taxonomy)
        if not any(result[name] for name in ("mandatory", "preferred", "context", "manual")):
            continue
        jobs[url] = {
            "m": [code(x) for x in result["mandatory"]],
            "p": [code(x) for x in result["preferred"]],
            "c": [code(x) for x in result["context"]],
            "x": [code(x) for x in result["manual"]],
            "q": result["confidence"],
        }
    payload = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "count": len(jobs), "terms": terms, "jobs": jobs}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    size_mb = len(text.encode("utf-8")) / 1_048_576
    if size_mb > max_raw_mb:
        raise RuntimeError(f"fit index is {size_mb:.1f} MB, above the {max_raw_mb:.1f} MB safety cap")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, out)
    return len(jobs), size_mb
