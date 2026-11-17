#!/usr/bin/env python3
"""
Testa a conectividade do LINKEDIN_ACCESS_TOKEN com a Community Management API do LinkedIn.
Realiza uma requisição GET segura para /rest/organizationAcls sem criar publicações.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN")
if not TOKEN or not TOKEN.strip():
    print("ERRO: Variável de ambiente LINKEDIN_ACCESS_TOKEN não configurada.", file=sys.stderr)
    sys.exit(1)

TOKEN = TOKEN.strip()
print(f"Token detectado (comprimento: {len(TOKEN)}, início: {TOKEN[:6]}...)")

# Testar versões da API caso uma seja muito recente ou antiga
VERSIONS_TO_TRY = ["202611", "202601", "202501", "202401"]
success = False

for version in VERSIONS_TO_TRY:
    print(f"\n--- Testando com LinkedIn-Version: {version} ---")
    req = urllib.request.Request(
        "https://api.linkedin.com/rest/organizationAcls?q=roleAssignee",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "LinkedIn-Version": version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"SUCESSO! HTTP {resp.status}")
            elements = data.get("elements", [])
            print(f"Organizações administradas encontradas: {len(elements)}")
            for el in elements:
                org = el.get("organization")
                role = el.get("role")
                state = el.get("state")
                print(f"  - Org: {org} | Cargo: {role} | Status: {state}")
            success = True
            print(f"\n>> Versão recomendada para produção: {version} <<")
            break
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        print(f"Falha HTTP {exc.code} com versão {version}: {err_body[:300]}")
    except Exception as exc:
        print(f"Erro inesperado com versão {version}: {exc}")

if success:
    print("\n[OK] Conexão com a Community Management API do LinkedIn VALIDADA com sucesso!")
    sys.exit(0)
else:
    print("\n[FALHA] Nenhuma versão obteve sucesso na validação do token.", file=sys.stderr)
    sys.exit(1)
