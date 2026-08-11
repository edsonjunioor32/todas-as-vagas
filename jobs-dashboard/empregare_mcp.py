# -*- coding: utf-8 -*-
"""Small command-line client for Empregare's public Streamable HTTP MCP.

Examples:
  python empregare_mcp.py --query "suporte" --localidade "João Pessoa"
  python empregare_mcp.py --list-tools
"""
import argparse
import json
import urllib.request

ENDPOINT = "https://www.empregare.com/api/mcp"
PROTOCOL = "2025-06-18"


def rpc(method, params=None, request_id=1):
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }).encode("utf-8")
    request = urllib.request.Request(ENDPOINT, data=payload, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL,
        "User-Agent": "radar-vagas/1.0",
    }, method="POST")
    with urllib.request.urlopen(request, timeout=35) as response:
        text = response.read().decode("utf-8", "replace")
    for line in text.splitlines():
        if line.startswith("data:"):
            message = json.loads(line[5:].strip())
            if "error" in message:
                raise RuntimeError(message["error"])
            return message.get("result") or {}
    parsed = json.loads(text)
    if "error" in parsed:
        raise RuntimeError(parsed["error"])
    return parsed.get("result") or {}


def main():
    parser = argparse.ArgumentParser(description="Consultar vagas pela interface MCP da Empregare")
    parser.add_argument("--list-tools", action="store_true")
    parser.add_argument("--query", default="")
    parser.add_argument("--localidade", default="")
    parser.add_argument("--pcd", action="store_true")
    parser.add_argument("--pagina", type=int, default=1)
    parser.add_argument("--itens", type=int, default=10)
    args = parser.parse_args()

    if args.list_tools:
        print(json.dumps(rpc("tools/list"), ensure_ascii=False, indent=2))
        return
    if not 1 <= args.itens <= 50:
        raise SystemExit("--itens deve estar entre 1 e 50")

    arguments = {
        "query": args.query,
        "localidade": args.localidade,
        "pagina": max(1, args.pagina),
        "itensPagina": args.itens,
    }
    if args.pcd:
        arguments["pcd"] = True
    result = rpc("tools/call", {
        "name": "buscar_vagas",
        "arguments": arguments,
    }, request_id=2)
    content = result.get("content") or []
    text = next((item.get("text") for item in content if item.get("type") == "text"), "{}")
    print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
