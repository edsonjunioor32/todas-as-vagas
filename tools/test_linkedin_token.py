#!/usr/bin/env python3
"""
Testa a conectividade do LINKEDIN_ACCESS_TOKEN com a Community Management API do LinkedIn.
Imprime detalhes completos de headers de erro (ex: WWW-Authenticate) para diagnosticar
exatamente por que a autenticação está falhando.
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
COMMON_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "TVLink-TodasAsVagas/1.0 (https://github.com/edsonjunioor32/todas-as-vagas)",
}

def print_http_error(prefix: str, exc: urllib.error.HTTPError):
    print(f"{prefix} HTTP {exc.code}")
    www_auth = exc.headers.get("WWW-Authenticate")
    if www_auth:
        print(f"  --> WWW-Authenticate: {www_auth}")
    for h, v in exc.headers.items():
        if "error" in h.lower() or "auth" in h.lower() or "linkedin" in h.lower() or "status" in h.lower():
            print(f"  --> Header {h}: {v}")
    body = exc.read().decode("utf-8", errors="replace")
    print(f"  --> Body: {body[:300]}")

# Teste 1: /v2/userinfo
print("\n=== Teste 1: GET /v2/userinfo ===")
try:
    req = urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo",
        headers=COMMON_HEADERS
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"SUCESSO userinfo: {data.get('name', 'OK')} ({data.get('sub')})")
except urllib.error.HTTPError as exc:
    print_http_error("userinfo", exc)
except Exception as exc:
    print(f"userinfo erro: {exc}")

# Teste 2: /v2/me
print("\n=== Teste 2: GET /v2/me ===")
try:
    req = urllib.request.Request(
        "https://api.linkedin.com/v2/me",
        headers=COMMON_HEADERS
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"SUCESSO me: {data.get('id', 'OK')}")
except urllib.error.HTTPError as exc:
    print_http_error("me", exc)
except Exception as exc:
    print(f"me erro: {exc}")

# Teste 3: GET /rest/posts
print("\n=== Teste 3: GET /rest/posts por autor ===")
for ver in ["202601", "202501", "202401"]:
    try:
        url = f"https://api.linkedin.com/rest/posts?author={urllib.parse.quote(ORG_URN)}&q=author"
        headers = dict(COMMON_HEADERS)
        headers["LinkedIn-Version"] = ver
        headers["X-Restli-Protocol-Version"] = "2.0.0"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"SUCESSO posts (versão {ver})! Encontrados: {len(data.get('elements', []))}")
            break
    except urllib.error.HTTPError as exc:
        print_http_error(f"posts (v{ver})", exc)
    except Exception as exc:
        print(f"posts erro (v{ver}): {exc}")

# Teste 4: POST /rest/images?action=initializeUpload
print("\n=== Teste 4: POST /rest/images?action=initializeUpload ===")
for ver in ["202601", "202501", "202401"]:
    try:
        body = json.dumps({"initializeUploadRequest": {"owner": ORG_URN}}).encode("utf-8")
        headers = dict(COMMON_HEADERS)
        headers["LinkedIn-Version"] = ver
        headers["X-Restli-Protocol-Version"] = "2.0.0"
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            "https://api.linkedin.com/rest/images?action=initializeUpload",
            data=body,
            headers=headers
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
        print_http_error(f"images (v{ver})", exc)
    except Exception as exc:
        print(f"images erro (v{ver}): {exc}")

print("\nConclusão: Nenhum teste teve sucesso.")
sys.exit(1)
