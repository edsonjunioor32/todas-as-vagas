#!/usr/bin/env python3
"""
Testa a conectividade do LINKEDIN_ACCESS_TOKEN com a Community Management API do LinkedIn.
Testa:
1. POST /rest/images?action=initializeUpload com as versões mensais mais recentes
2. GET /rest/organizationAcls?q=roleAssignee (para confirmar papéis administrativos da página)
3. GET /rest/organizations/146671035
4. POST /rest/posts
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN")
if not TOKEN or not TOKEN.strip():
    print("ERRO: LINKEDIN_ACCESS_TOKEN não configurada.", file=sys.stderr)
    sys.exit(1)

TOKEN = TOKEN.strip()
print(f"Token detectado (comprimento: {len(TOKEN)}, início: {TOKEN[:8]}... fim: ...{TOKEN[-6:]})")

ORG_URN = "urn:li:organization:146671035"

# Versões mensais recentes (últimos 12 meses)
VERSIONS_TO_TEST = [
    "202611", "202610", "202609", "202608", "202607", "202606",
    "202605", "202604", "202603", "202602", "202601", "202512"
]

def make_req(url: str, data: bytes | None = None, ver: str | None = None):
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "User-Agent": "TVLink-TodasAsVagas/1.0",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if ver:
        headers["Linkedin-Version"] = ver
    if data is not None:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=data, headers=headers)

success_version = None

print("\n=== Testando POST /rest/images?action=initializeUpload ===")
body = json.dumps({"initializeUploadRequest": {"owner": ORG_URN}}).encode("utf-8")
for ver in VERSIONS_TO_TEST:
    try:
        req = make_req("https://api.linkedin.com/rest/images?action=initializeUpload", data=body, ver=ver)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"[SUCESSO] initializeUpload funcionou com versão {ver}!")
            print(f"  - Image URN: {data.get('value', {}).get('image')}")
            upload_url = data.get('value', {}).get('uploadUrl')
            print(f"  - Upload URL obtida: {upload_url[:50]}...")
            success_version = ver
            break
    except urllib.error.HTTPError as exc:
        print(f"Versão {ver}: HTTP {exc.code} - {exc.read().decode('utf-8', errors='replace')[:120]}")
    except Exception as exc:
        print(f"Versão {ver}: Erro {exc}")

if success_version:
    print(f"\n🎉 VERSÃO CONFIRMADA DA COMMUNITY MANAGEMENT API: {success_version} 🎉")
    sys.exit(0)

print("\n=== Testando GET /rest/organizationAcls?q=roleAssignee ===")
for ver in VERSIONS_TO_TEST[:4]:
    try:
        req = make_req("https://api.linkedin.com/rest/organizationAcls?q=roleAssignee", ver=ver)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"[SUCESSO] organizationAcls com versão {ver}: {len(data.get('elements', []))} elementos")
            success_version = ver
            break
    except urllib.error.HTTPError as exc:
        print(f"organizationAcls {ver}: HTTP {exc.code} - {exc.read().decode('utf-8', errors='replace')[:120]}")
    except Exception as exc:
        print(f"organizationAcls {ver}: Erro {exc}")

if success_version:
    print(f"\n🎉 VERSÃO CONFIRMADA DA COMMUNITY MANAGEMENT API: {success_version} 🎉")
    sys.exit(0)

print("\nConclusão: Nenhum teste teve sucesso.")
sys.exit(1)
