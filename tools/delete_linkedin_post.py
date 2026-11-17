#!/usr/bin/env python3
"""
Utilitário para excluir publicações do LinkedIn por URN usando a Community Management API.
Uso:
    python tools/delete_linkedin_post.py <post_urn>
"""
from __future__ import annotations

import os
import sys

from linkedin_api import delete_post


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python tools/delete_linkedin_post.py <post_urn>", file=sys.stderr)
        return 1

    post_urn = sys.argv[1].strip()
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    if not token:
        print("Erro: LINKEDIN_ACCESS_TOKEN não configurado no ambiente.", file=sys.stderr)
        return 1

    print(f"Tentando excluir post: {post_urn} no LinkedIn...")
    try:
        success = delete_post(post_urn, token)
        if success:
            print(f"Post {post_urn} excluído com sucesso do LinkedIn!")
            return 0
        else:
            print(f"Não foi possível confirmar a exclusão do post {post_urn}.", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Erro ao excluir post: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
