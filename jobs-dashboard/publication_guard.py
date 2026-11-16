# -*- coding: utf-8 -*-
"""Decide se o ``main`` avançou com mudanças que invalidam a coleta em curso.

A publicação do catálogo recusa um snapshot calculado com código defasado.
Antes, *qualquer* commit no ``main`` durante a coleta (~35 min) bastava para
recusar — inclusive os commits automáticos de dados (snapshot do LinkedIn,
estado dos digests, índices Greenhouse/InHire) e edições de documentação,
que não mudam o código da coleta.  Este guarda compara as árvores do commit
disparador e da ponta atual do ``main`` e só bloqueia quando algum arquivo
fora dessa lista mudou.

Uso::

    python jobs-dashboard/publication_guard.py --base "$GITHUB_SHA" --head origin/main
    python jobs-dashboard/publication_guard.py --base "$GITHUB_SHA" --head origin/main \\
        --forbid jobs-dashboard/data/greenhouse_br_companies.json

Saída 0: seguro publicar.  Saída 1: há mudanças bloqueantes (listadas).
Saída 2: não foi possível comparar (tratar como bloqueante).
"""
import argparse
import subprocess
import sys

# Arquivos gravados automaticamente por workflows; mudar estes arquivos não
# altera o código que gerou a coleta em curso.
DATA_PATHS = frozenset({
    "docs/data/linkedin_vagas.json",
    "docs/data/linkedin_digest_state.json",
    "docs/data/greenhouse-watchlist.json",
    "jobs-dashboard/data/greenhouse_br_companies.json",
    "jobs-dashboard/data/greenhouse_watchlist.json",
    "busca_vagas/inhire_tenants_seed.json",
})
DOCUMENTATION_SUFFIXES = (".md",)


def blocking_paths(changed, forbid=()):
    """Arquivos alterados que impedem publicar, em ordem alfabética.

    ``forbid`` lista arquivos que, mesmo sendo dados, não podem ter mudado
    (por exemplo, o arquivo que esta execução vai gravar por cima).
    """
    forbidden = set(forbid)
    blocking = set()
    for path in changed:
        path = str(path or "").strip()
        if not path:
            continue
        if path in forbidden:
            blocking.add(path)
        elif path not in DATA_PATHS and not path.endswith(DOCUMENTATION_SUFFIXES):
            blocking.add(path)
    return sorted(blocking)


def _git(*args):
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def changed_paths(base, head):
    """Arquivos que diferem entre as árvores de ``base`` e ``head``."""
    return [line for line in _git("diff", "--name-only", base, head).splitlines() if line]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="commit que disparou a coleta")
    parser.add_argument("--head", required=True, help="ponta atual do main")
    parser.add_argument("--forbid", nargs="*", default=[],
                        help="arquivos de dados que também não podem ter mudado")
    args = parser.parse_args(argv)
    try:
        base = _git("rev-parse", args.base).strip()
        head = _git("rev-parse", args.head).strip()
        if base == head:
            print(f"OK: o main continua em {base}.")
            return 0
        changed = changed_paths(base, head)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        print(f"ERRO: não foi possível comparar {args.base} e {args.head}: {detail}".strip(),
              file=sys.stderr)
        return 2
    blocking = blocking_paths(changed, args.forbid)
    if blocking:
        print(
            f"ERRO: o main avançou de {base[:12]} para {head[:12]} com mudanças que "
            "afetam esta execução:", file=sys.stderr,
        )
        for path in blocking:
            print(f"  - {path}", file=sys.stderr)
        return 1
    print(
        f"OK: o main avançou de {base[:12]} para {head[:12]} só com dados automáticos "
        f"ou documentação ({len(changed)} arquivo(s)); a coleta continua válida."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
