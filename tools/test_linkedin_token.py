#!/usr/bin/env python3
"""
Testa a conectividade do LINKEDIN_ACCESS_TOKEN com a Community Management API do LinkedIn.
Testa:
1. GET /v2/userinfo (autenticação básica do membro)
2. GET /rest/posts (leitura via r_organization_social)
3. POST /rest/images?action=initializeUpload (permissão de upload via w_organization_social)
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
    print("ERRO: Variável de ambiente LINKEDIN_ACCESS_TOKEN não configurada.", file=sys.stderr)
    sys.exit(1)

TOKEN = TOKEN.strip()
print(f"Token detectado (comprimento: {len(TOKEN)}, início: {TOKEN[:8]}... fim: ...{TOKEN[-6:]})")

ORG_URN = "urn:li:organization:146671035"
API_VERSIONS = ["202601", "202501", "202401"]

# Teste 1: /v2/userinfo
print("\n=== Teste 1: GET /v2/userinfo ===")
try:
    req = urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {TOKEN}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"SUCESSO userinfo: {data.get('name', 'OK')} ({data.get('sub')})")
except urllib.error.HTTPError as exc:
    print(f"userinfo HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:200]}")
except Exception as exc:
    print(f"userinfo erro: {exc}")

# Teste 2: GET /rest/posts (r_organization_social)
print("\n=== Teste 2: GET /rest/posts por autor ===")
for ver in API_VERSIONS:
    try:
        url = f"https://api.linkedin.com/rest/posts?author={urllib.parse.quote(ORG_URN)}&q=author"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "LinkedIn-Version": ver,
                "X-Restli-Protocol-Version": "2.0.0",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"SUCESSO posts (versão {ver})! Encontrados: {len(data.get('elements', []))}")
            break
    except urllib.error.HTTPError as exc:
        print(f"posts HTTP {exc.code} (versão {ver}): {exc.read().decode('utf-8', errors='replace')[:250]}")
    except Exception as exc:
        print(f"posts erro (versão {ver}): {exc}")

# Teste 3: POST /rest/images?action=initializeUpload (w_organization_social)
print("\n=== Teste 3: POST /rest/images?action=initializeUpload ===")
for ver in API_VERSIONS:
    try:
        body = json.dumps({"initializeUploadRequest": {"owner": ORG_URN}}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.linkedin.com/rest/images?action=initializeUpload",
            data=body,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "LinkedIn-Version": ver,
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            upload_url = data.get("value", {}).get("uploadUrl")
            image_urn = data.get("value", {}).get("image")
            print(f"SUCESSO initializeUpload (versão {ver})!")
            print(f"  - Image URN: {image_urn}")
            print(f"  - Upload URL obtida: {upload_url[:50]}...")
            print(f"\n>> VERSÃO CONFIRMADA DA API: {ver} <<")
            sys.exit(0)
    except urllib.error.HTTPError as exc:
        print(f"images HTTP {exc.code} (versão {ver}): {exc.read().decode('utf-8', errors='replace')[:250]}")
    except Exception as exc:
        print(f"images erro (versão {ver}): {exc}")

print("\nConclusão: Nenhum teste teve sucesso.")
sys.exit(1)
