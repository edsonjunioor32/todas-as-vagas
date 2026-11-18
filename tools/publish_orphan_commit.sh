#!/usr/bin/env bash
# Publica o índice preparado de um worktree como um commit ÓRFÃO único no ramo
# indicado, substituindo o anterior com --force-with-lease.
#
# Os ramos de dados (public-data) guardam só a fotografia mais recente: cada
# commit regrava ~20 MB de JSON minificado, então manter a cadeia de commits
# acumulava gigabytes de histórico sem uso (o site só lê a ponta do ramo).
#
# Uso: publish_orphan_commit.sh <worktree> <ramo> <mensagem>
# Pré-requisitos: os arquivos já estão em `git add` no worktree e
# refs/remotes/origin/<ramo> aponta para a ponta que serviu de base (se existir).
set -euo pipefail

worktree="$1"
branch="$2"
message="$3"

export GIT_AUTHOR_NAME="github-actions[bot]"
export GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

tree="$(git -C "$worktree" write-tree)"
commit="$(git -C "$worktree" commit-tree "$tree" -m "$message")"

# A lease protege contra outro escritor que tenha publicado depois do nosso
# fetch: nesse caso o push falha em vez de descartar a publicação dele.
expected="$(git -C "$worktree" rev-parse --verify --quiet "refs/remotes/origin/$branch" || true)"
git -C "$worktree" push \
  --force-with-lease="refs/heads/$branch:${expected}" \
  origin "$commit:refs/heads/$branch"

echo "Publicado $commit como commit órfão único em $branch."
