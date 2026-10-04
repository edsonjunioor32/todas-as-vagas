# Histórico operacional e mapa de responsabilidades

Este registro complementa o README. Atualize-o quando mudar agenda, recuperadores ou publicação.

## Componentes

- `.github/workflows/pages.yml`: coleta e publicação do catálogo, em horários UTC definidos; grupo `catalog-publication` preserva a ordem de todos os escritores.
- `.github/workflows/catalog-catchup.yml` e `jobs-dashboard/catalog_catchup.py`: monitor GitHub-hosted; verifica execuções e despacha uma recuperação por horário ausente, com alerta em caso de falha.
- `ops/github_scheduler.py` e timer systemd da VPS: recuperador externo; consulta os mesmos runs, guarda tentativas por horário em arquivo privado e evita nova postagem ambígua.
- `botwhats`: repositório e serviço separados que consomem o catálogo publicado. Seu histórico operacional fica no `OPERATIONS.md` próprio.

## 2026-10-03 — Idempotência do recuperador

- O recuperador externo passou a reconhecer `repository_dispatch`, paginar os runs e recusar uma decisão com histórico truncado.
- O `resume_key` passou a aparecer no título das execuções manuais, permitindo associar a tentativa persistida ao run correspondente.
- Uma tentativa aceita, mas sem run identificável, deixa o horário em estado `dispatch_unconfirmed` e emite alerta; não é reenviada automaticamente. Reenvio só após falha observada, respeitando backoff e limite por horário.
- O monitor do GitHub usa `queue: single` para não acumular verificações obsoletas. O publicador mantém `queue: max` e `cancel-in-progress: false` para não descartar gravações.
- Verificação: testes de agenda e simulações de run ativo, ausência de visibilidade, falha e paginação. Na implantação, conferir `journalctl -u todas-as-vagas-github-scheduler.service` e runs da coleta antes do próximo horário.

Se houver `dispatch_unconfirmed`, verificar manualmente o run no GitHub antes de qualquer novo disparo. Não apagar o arquivo de estado para forçar repetição: isso remove a proteção contra duplicidade.

## 2026-10-03 — Espaço da VPS

- O alerta do disco do runner está no workflow `vps-health.yml` do repositório `botwhats` (aviso em 75%, falha em 85%).
- Sem build ativo, foi executado `docker builder prune --filter until=168h --force` na VPS. Somente cache de build sem uso há mais de sete dias foi removido: 3,101 GB. A ocupação de `/` passou de 85% para 78%; imagens, volumes, containers e dados privados não foram apagados.
- Antes de repetir a limpeza, verificar `Runner.Worker`, builds ativos, `docker system df` e `df -h /`. Evitar `docker system prune` ou exclusão de diretórios de runner sem inventário.
