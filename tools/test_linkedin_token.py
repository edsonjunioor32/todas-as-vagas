#!/usr/bin/env python3
"""
Testa o LINKEDIN_ACCESS_TOKEN contra a Community Management API do LinkedIn.

1. POST /rest/images?action=initializeUpload (upload de imagem da página)
2. GET /rest/organizationAcls?q=roleAssignee (papéis do usuário na página)

Os logs do Actions são públicos neste repositório: nenhum trecho do token é
impresso, só o comprimento. Cada resposta recebe um diagnóstico com a causa
provável, e a saída é 1 quando nenhum teste passa.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ORG_URN = "urn:li:organization:146671035"
API = "https://api.linkedin.com/rest"
# Versões mensais recentes; o LinkedIn aposenta as antigas periodicamente.
VERSIONS_TO_TEST = [
    "202611", "202610", "202609", "202608", "202607", "202606",
    "202605", "202604", "202603", "202602", "202601", "202512",
]

DIAGNOSES = {
    401: "token inválido, expirado ou revogado — gere um novo token OAuth para o app.",
    403: (
        "token válido, mas sem permissão: confira se o app tem o produto Community "
        "Management API aprovado, se o token inclui os escopos w_organization_social "
        "e r_organization_admin, e se o usuário do token é administrador da página "
        f"{ORG_URN}."
    ),
    404: "recurso não encontrado — confira o ID da organização.",
    426: "versão da API não suportada (Linkedin-Version) — tente uma versão mais recente.",
    429: "limite de chamadas do LinkedIn atingido — tente mais tarde.",
}


def diagnose(status: int, body: str) -> str:
    text = body.casefold()
    if status == 400 and "version" in text:
        return DIAGNOSES[426]
    if status == 403 and "scope" in text:
        return "escopo ausente no token: " + DIAGNOSES[403]
    return DIAGNOSES.get(status, "resposta inesperada — veja o corpo acima.")


def request(token: str, url: str, version: str, data: bytes | None = None):
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "TodasAsVagas-TokenCheck/1.0",
        "X-Restli-Protocol-Version": "2.0.0",
        "Linkedin-Version": version,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def run_test(token: str, name: str, url: str, versions, data: bytes | None = None):
    """Tenta as versões em ordem; devolve (versão_ok, último_diagnóstico)."""
    last = None
    for version in versions:
        try:
            payload = request(token, url, version, data)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:300]
            last = (error.code, diagnose(error.code, body))
            print(f"{name} {version}: HTTP {error.code} — {body}")
            if error.code in (401, 403, 404, 429):
                # Não depende da versão: repetir não muda o resultado.
                break
            continue
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            last = (None, f"falha de rede ou resposta inválida: {error}")
            print(f"{name} {version}: {error}")
            continue
        print(f"[OK] {name} funcionou com a versão {version}.")
        if isinstance(payload, dict) and "elements" in payload:
            print(f"     {len(payload['elements'])} papel(éis) encontrado(s).")
        return version, None
    return None, last


def main() -> int:
    token = (os.environ.get("LINKEDIN_ACCESS_TOKEN") or "").strip()
    if not token:
        print("ERRO: LINKEDIN_ACCESS_TOKEN não configurada.", file=sys.stderr)
        return 1
    print(f"Token presente ({len(token)} caracteres).")

    body = json.dumps({"initializeUploadRequest": {"owner": ORG_URN}}).encode("utf-8")
    tests = (
        ("initializeUpload", f"{API}/images?action=initializeUpload", VERSIONS_TO_TEST, body),
        ("organizationAcls", f"{API}/organizationAcls?q=roleAssignee", VERSIONS_TO_TEST[:4], None),
    )
    diagnoses = []
    for name, url, versions, data in tests:
        print(f"\n=== {name} ===")
        version, problem = run_test(token, name, url, versions, data)
        if version:
            print(f"\nVersão confirmada da Community Management API: {version}")
            return 0
        if problem:
            diagnoses.append((name, problem))

    print("\nNenhum teste passou. Causa provável:")
    for name, (status, message) in diagnoses:
        print(f"  - {name} (HTTP {status or '—'}): {message}")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::error title=Token LinkedIn ({name})::HTTP {status or '—'} — {message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
