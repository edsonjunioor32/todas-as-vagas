# Mapa operacional do ecossistema Todas as Vagas

Revisão: 2026-10-17. Este documento complementa o inventário **arquivo a arquivo dos arquivos rastreados de `todas-as-vagas/main`** em [OPERATIONS_CHANGELOG.md](OPERATIONS_CHANGELOG.md#mapa-dos-arquivos-rastreados). As listas abaixo incluem todos os arquivos rastreados na branch padrão dos demais repositórios vinculados, não apenas os executáveis. A classificação descreve a função observada; não autoriza ativar, desativar ou excluir nada. Antes de mudar um componente, confira também o código e os runs atuais: o mapa é uma fotografia, não um substituto para validação em produção.

## Fronteiras e fluxo de dados

1. `todas-as-vagas/main`: `jobs-dashboard/` e `busca_vagas/` descobrem/normalizam vagas; `.github/workflows/pages.yml` coordena coleta, validação, publicação e site. `history-data/data/jobs.db.gz` preserva o banco histórico; `public-data/data/vagas.json` e `data/fit.json` alimentam a interface e os consumidores. Os três arquivos gerados pertencem a branches separadas, **não** à árvore de `main`.
2. `edsonjunioor32-todas-as-vagas-telegram`: lê o catálogo publicado; `sync_snapshot.py` sincroniza o Worker/D1 e `notifier.py` filtra/envia ao canal. Estados de deduplicação e progresso ficam no próprio repositório. O fluxo regular não depende de `.github/workflows/telegram.yml` do repositório central, que é manual.
3. `botwhats`: consome o snapshot público, guarda cópia/estado em volume Docker e usa OpenWA para consulta interativa e publicação no canal. Seu `production.yml` é o publicador ativo; o timer `botwhats-catalog-fallback` na VPS é a redundância.
4. `todas-as-vagas-whats`: publicador **legado**; seu único workflow de envio é manual e executa simulação sem envio. Não é uma segunda redundância autorizada.
5. `agente-vagas-edson`: consome `public-data/data/vagas.json` para ranqueamento personalizado e gera saídas próprias; não publica vagas no catálogo.
6. `vagas-remotas-inhire`: projeto independente de descoberta InHire. Os arquivos `busca_vagas/` do repositório central são cópias/implementações próprias; não há dependência de execução entre os dois repositórios. Desativar este projeto não equivale a desligar InHire no catálogo central.
7. `todos-os-cursos-free` aparece como link de navegação do site, mas não participa da coleta/publicação de vagas. N8n, Postiz, Temporal e outros containers presentes na VPS não são classificados como dependências da rotina de vagas sem evidência de chamada nos fluxos acima.

## Branches de dados do repositório central — 3 arquivos adicionais

| Branch / arquivo | Responsabilidade; impacto de perda ou mudança de contrato |
| --- | --- |
| `public-data/data/vagas.json` | Snapshot de vagas do site, Telegram, WhatsApp e agente; ausência, URL ou esquema alterado interrompe/empobrece todos os consumidores. |
| `public-data/data/fit.json` | Índice auxiliar de aderência usado pela interface; mudança de esquema afeta a análise de currículo, não a origem das vagas. |
| `history-data/data/jobs.db.gz` | Banco histórico usado pela coleta incremental; perda/arquivo inválido compromete deduplicação, continuidade e recuperação do catálogo. |

## Telegram — 26 arquivos rastreados

| Arquivo | Responsabilidade |
| --- | --- |
| `.github/workflows/notify.yml` | Agenda e execução do filtro/envio ao Telegram; grava `state.json`. |
| `.github/workflows/telegram-poll.yml` | Polling desativado inclusive quando acionado manualmente (`if: false`); coexistir com webhook pode duplicar processamento. |
| `.github/workflows/telegram-sync-catchup.yml` | Recuperação **manual** de sincronização perdida do Worker. |
| `.github/workflows/telegram-sync.yml` | Agenda e sincronização do catálogo público com Worker/D1; grava `sync_state.json`. |
| `.github/workflows/telegram-webhook.yml` | Operação do webhook do bot, fora do notificador agendado. |
| `.github/workflows/telegram-worker-deploy.yml` | Publica o Worker que atende consultas interativas. |
| `.github/workflows/validate-button-ui.yml` | Valida interface/botões e contrato da interação. |
| `README.md` | Uso, configuração e operação do bot. |
| `notifier.py` | Filtra novas vagas e envia mensagens; mantém estado de envio. Também fornece funções de leitura usadas por `sync_snapshot.py`. |
| `state.json` | Checkpoint de deduplicação do notificador; não apagar para forçar reenvio. |
| `sync_guard.py` | Verifica se a coleta de origem terminou antes de sincronizar. |
| `sync_snapshot.py` | Baixa e envia o snapshot ao Worker com controle de progresso. |
| `sync_state.json` | Checkpoint de sincronização; evita repetir snapshot idêntico. |
| `tests/test_d1_write_guard.py` | Regressão contra escrita insegura no D1. |
| `tests/test_message_layout.py` | Regressão do layout das mensagens. |
| `tests/test_sync_guard.py` | Testes `unittest` da barreira de atualização; são executados pela descoberta e pela chamada direta do workflow. |
| `tests/test_sync_snapshot_progress.py` | Regressão do avanço/reinício do sync. |
| `tests/test_ui_buttons.py` | Regressão dos botões de interação. |
| `tests/test_worker_message_layout.py` | Regressão do layout produzido pelo Worker. |
| `worker/README.md` | Implantação/operação do Worker. |
| `worker/migrations/0002_drop_unhelpful_job_indexes.sql` | Migração de índices D1; executar sem revisão pode afetar consultas. |
| `worker/package.json` | Scripts e dependências do Worker. |
| `worker/schema.sql` | Esquema D1 da base de vagas/filtros. |
| `worker/src/index.ts` | Webhook, busca, filtros e respostas do bot no Worker. |
| `worker/tsconfig.json` | Compilação TypeScript do Worker. |
| `worker/wrangler.jsonc` | Bindings/implantação Cloudflare do Worker e D1. |

## WhatsApp legado — 8 arquivos rastreados

| Arquivo | Responsabilidade |
| --- | --- |
| `.env.example` | Exemplo de configuração, sem credenciais reais. |
| `.github/workflows/pull-request.yml` | Validação em PR. |
| `.github/workflows/whatsapp-sync.yml` | Simulação manual do publicador antigo; não envia mensagens na configuração atual. |
| `.gitignore` | Exclusão de saídas/segredos locais. |
| `README.md` | Histórico e operação manual legada. |
| `state.json` | Estado do publicador antigo; **não** é o estado do `botwhats`. |
| `tests/test_whatsapp_notifier.py` | Testes do notificador antigo. |
| `whatsapp_notifier.py` | Implementação do notificador antigo, atualmente só invocada em dry-run. |

## botwhats — 39 arquivos rastreados

| Arquivo | Responsabilidade |
| --- | --- |
| `.dockerignore` | Exclui arquivos do contexto da imagem. |
| `.env.example` | Exemplo de variáveis; valores reais ficam em secrets/ambiente. |
| `.github/workflows/openwa-recovery.yml` | Recuperação **manual** da sessão OpenWA. |
| `.github/workflows/production.yml` | Implantação, registro de webhook, sincronização e publicação agendada no canal. |
| `.github/workflows/pull-request.yml` | Testes/validação de mudanças antes de produção. |
| `.github/workflows/vps-health.yml` | Verifica bot, rede, sessão, fila e disco; alerta, não publica vagas. |
| `.gitignore` | Exclui dados/segredos locais do Git. |
| `Dockerfile` | Imagem do serviço do bot. |
| `OPERATIONS.md` | Runbook específico do bot/OpenWA. |
| `README.md` | Arquitetura, uso e configuração. |
| `bot/__init__.py` | Declara o pacote Python. |
| `bot/app.py` | Constrói a aplicação e suas dependências. |
| `bot/catalog_source.py` | Obtém o snapshot `public-data/data/vagas.json`. |
| `bot/filters.py` | Aplica critérios de busca de vagas. |
| `bot/formatting.py` | Formata respostas e mensagens do canal. |
| `bot/http_server.py` | HTTP de webhook e saúde. |
| `bot/menus.py` | Menus/comandos da conversa. |
| `bot/models.py` | Modelos de vagas e dados do bot. |
| `bot/notifications.py` | Seleção/envio e controle de notificações do canal. |
| `bot/openwa.py` | Cliente da API OpenWA, sessão e mensagens. |
| `bot/register_webhook.py` | Registra callback de mensagens recebidas no OpenWA. |
| `bot/runtime.py` | Processamento assíncrono de mensagens e ciclo do bot. |
| `bot/service.py` | Orquestra comandos e pesquisa do usuário. |
| `bot/storage.py` | SQLite persistente: filtros, catálogo, fila e envios. |
| `bot/sync_catalog.py` | Valida/importa snapshot e dispara notificações pendentes. |
| `docker-compose.yml` | Serviço, volumes, rede Docker e healthcheck. |
| `ops/botwhats-cycle.sh` | Lock e marcação de tentativa compartilhados por workflow e fallback; impede corrida/reenvio rápido. |
| `ops/systemd/botwhats-catalog-fallback.service` | Serviço de recuperação na VPS. |
| `ops/systemd/botwhats-catalog-fallback.timer` | Agenda da recuperação na VPS. |
| `renovate.json` | Política de atualização de dependências. |
| `tests/test_bot.py` | Regressão de filtros/comandos. |
| `tests/test_catalog_source.py` | Regressão de leitura do catálogo. |
| `tests/test_channel_notifications.py` | Regressão de fila/envio do canal. |
| `tests/test_cycle_script.py` | Regressão do lock/redundância do ciclo. |
| `tests/test_durable_hardening.py` | Regressão de persistência e recuperação. |
| `tests/test_hardening.py` | Regressão de limites/validação defensiva. |
| `tests/test_openwa_session.py` | Regressão de conexão/sessão OpenWA. |
| `tests/test_runtime.py` | Regressão do processamento em execução. |
| `tests/test_workflows.py` | Regressão dos contratos de workflow. |

## Agente de vagas — 17 arquivos rastreados

| Arquivo | Responsabilidade |
| --- | --- |
| `.github/workflows/vagas.yml` | Agenda diária, testes, ranqueamento e publicação das saídas próprias. |
| `.gitignore` | Exclui dados locais não versionados. |
| `README.md` | Uso e limites do agente. |
| `docs/app.js` | Interface dos resultados ranqueados. |
| `docs/index.html` | Entrada da interface do agente. |
| `docs/styles.css` | Aparência da interface. |
| `output/resumo.md` | Resumo publicado da execução. |
| `output/vagas_ranqueadas.csv` | Exportação tabular publicada. |
| `output/vagas_ranqueadas.json` | Dados ranqueados publicados; contrato do site do agente. |
| `perfil.json` | Perfil usado no ranqueamento; tratar como dado pessoal. |
| `src/enrichment.py` | Enriquecimento limitado dos dados das vagas. |
| `src/pipeline.py` | Fonte, normalização e utilitários de coleta/ranking. |
| `src/pipeline_v2.py` | Pipeline atual de seleção e ranqueamento. |
| `src/scoring_v2.py` | Cálculo da aderência/filtragem remota. |
| `tests/test_enrichment.py` | Regressão do enriquecimento. |
| `tests/test_pipeline.py` | Regressão do pipeline. |
| `tests/test_scoring_v2.py` | Regressão da pontuação. |

## Projeto InHire independente — 14 arquivos rastreados

| Arquivo | Responsabilidade |
| --- | --- |
| `.github/workflows/pages.yml` | Coleta/publicação do **projeto separado**. |
| `README_GITHUB_PAGES.md` | Operação do projeto separado. |
| `busca_vagas/build_public_inhire.js` | Monta lote público InHire local. |
| `busca_vagas/harvest_inhire_public.js` | Descobre vagas InHire localmente. |
| `busca_vagas/inhire_tenants_seed.json` | Sementes de empresas. |
| `busca_vagas/validate_public_inhire.js` | Valida a exportação local. |
| `docs/app.js` | Interface do projeto separado. |
| `docs/data/meta.json` | Metadados gerados da coleta própria. |
| `docs/data/vagas.json` | Snapshot gerado da coleta própria. |
| `docs/favicon.svg` | Ícone do site separado. |
| `docs/index.html` | Entrada do site separado. |
| `docs/robots.txt` | Diretrizes de indexação do site separado. |
| `docs/styles.css` | Estilo do site separado. |
| `package.json` | Scripts/dependências Node locais. |

## Estado fora do Git e limites do inventário

- VPS: `/home/ubuntu/todas-as-vagas` (checkout do coletor), `/home/ubuntu/todas-as-vagas-private/descriptions.sqlite3` (descrições completas privadas), `-wal`/`-shm` transitórios e cópias de recuperação. O arquivo SQLite não integra o catálogo público. `jobs-dashboard/description_crawler.py` e `ops/systemd/todas-as-vagas-descriptions.{service,timer}` são os arquivos versionados correspondentes. A unidade instalada `/etc/systemd/system/todas-as-vagas-descriptions-watchdog.service` **não tem equivalente versionado**: é `oneshot` e executa `systemctl start --no-block todas-as-vagas-descriptions.service`; o timer instalado é horário e aponta para ela. Isto difere do template do Git; conferir `systemctl cat` antes de alterar o agendamento.
- VPS: `todas-as-vagas-github-scheduler.{service,timer}` instalado sob systemd, `ops/github_scheduler.py` versionado, ambiente privado em `/home/ubuntu/.config/todas-as-vagas/github-scheduler.env` e estado de tentativas privado. Nunca copiar token/estado para o Git. A unidade do scheduler usa o checkout em `/home/ubuntu/todas-as-vagas`; mudanças em `main` não chegam automaticamente se a cópia local ficar atrasada. O recuperador da VPS e `catalog-catchup.yml` **não compartilham o registro de tentativas**, embora consultem o mesmo histórico de runs.
- `todas-as-vagas-docker-cache-prune.{service,timer}` foi mesclado no PR #149 e instalado/habilitado como timer de sistema na VPS. Execução diária, com próxima ativação observada em 2026-10-18 04:08 UTC; remove somente cache de build Docker com mais de sete dias e não executa se o daemon estiver indisponível. Não remove imagens, containers ou volumes.
- VPS: `openwa` (imagem `rmyndharis/openwa:0.24.0`, dados em `/opt/openwa/data`), `botwhats` e seu volume/SQLite, rede `openwa_net`, runner ARM64 e timer de fallback de usuário. A configuração efetiva, secrets e dados persistentes não são arquivos rastreados desses repositórios. Não expor credenciais no mapa.
- Cloudflare Worker/D1 do Telegram e APIs externas dos portais são serviços fora do Git; `worker/` documenta código e esquema, mas o estado remoto deve ser verificado separadamente. Pacotes, camadas Docker, internals do runner e caches não são arquivos de projeto e ficam fora da promessa de inventário de arquivos rastreados.

## Matriz de impacto e risco antes de desativar ou alterar

| Componente / mudança | O que deixa de funcionar ou pode degradar | Verificação e decisão segura |
| --- | --- | --- |
| `todas-as-vagas/.github/workflows/pages.yml` (agenda/coleta) | Vagas de **todos** os portais param de chegar; site e bots continuam mostrando snapshot antigo. Uma execução de interface em push **não prova** atualização de vagas. | Conferir run agendado completo, horário UTC, contagem/data do snapshot `public-data` e publicação `history-data`. Nunca desativar sem agendador substituto e recuperação testada. |
| Deploy só da interface em push de `main` | O site pode mudar sem nova coleta; em falha de deploy, consumidores diretos do JSON podem estar atualizados enquanto o Pages continua antigo. | Distinguir o job `publicar-interface` do job de coleta; conferir a cópia `docs/data/` publicada e o snapshot bruto. |
| Escritas sequenciais de `pages.yml` | Histórico, snapshot público e Pages podem ficar em revisões diferentes se uma etapa intermediária falhar. | Comparar separadamente os heads `history-data`/`public-data`, o run completo e o deploy Pages; não confiar apenas no status agregado. |
| Adaptador de portal, lista/seed ou filtro em `jobs-dashboard/` / `busca_vagas/` | Somente os portais afetados deixam de atualizar; vagas antigas podem permanecer até expirar. | Identificar fonte e consumidores, comparar contagem/IDs/links antes e depois, testar amostra da origem e regra de retenção. Não usar sucesso global do workflow como prova por portal. |
| `catalog-catchup.yml` ou scheduler da VPS | Perda da redundância: execução perdida pode não ser recuperada; se ambos falham, cron do GitHub vira ponto único. | Confirmar estado dos **dois** recuperadores, token do scheduler, última decisão/dispatch e idempotência; não executar resgate manual sem verificar `resume_key`/runs para evitar duplicata. |
| `merge-dynamic-portals.yml` manual | Perde-se a via de reparo/publicação parcial de portais dinâmicos; coleta integral regular permanece. | Testar snapshot, índice de aderência e publicação das três saídas antes de usar como contingência. |
| Validação/PII/snapshot (`catalog-ci`, `fit-ci`, validadores) | Falhas podem bloquear publicação inteira; removê-las pode publicar dados quebrados ou pessoais. | Quarentenar registro problemático quando previsto, manter validação final; testar catálogo e índice separadamente. |
| `history-data/data/jobs.db.gz` | Coleta incremental, histórico e deduplicação podem perder continuidade. | Validar integridade e backup antes de substituir; não limpar para “reiniciar” coleta. |
| `public-data/data/vagas.json` (URL/esquema/IDs) | Site, Telegram, WhatsApp e agente podem parar ou duplicar notificações. | Testes de contrato dos quatro consumidores, amostra de IDs estáveis e publicação coordenada. |
| `public-data/data/fit.json` ou `jobs-dashboard/fit_*` | Aderência de currículo pode falhar embora a listagem de vagas continue. | Testar interface e validação do índice; não confundir com queda do catálogo principal. |
| Telegram `telegram-sync.yml`, catchup, `sync_state.json`, Worker/D1 | Consulta interativa pode ficar desatualizada; notificações podem sair fora de sincronia com o catálogo. | Comparar hash/progresso e execução de sync com data do catálogo; confirmar Worker/D1 antes de tocar no checkpoint. |
| Telegram `notify.yml`, `notifier.py`, `state.json` | Canal deixa de receber novas vagas ou, se resetar estado, pode reenviar lote antigo. | Conferir último envio, fila e checkpoint; `telegram.yml` central não é substituição automática segura. |
| Dois caminhos de envio do Telegram (Worker/D1 e `notifier.py`) | Um chat cadastrado em ambos pode receber duplicatas: `sent_jobs` no D1 e `state.json` não compartilham deduplicação. | Conferir destinatários e ledgers reais antes de alterar agendamento ou migrar usuários; não desligar um caminho sem validar quem depende dele. |
| `botwhats/production.yml` ou runner ARM64 | Implantação/sync/envio ao canal deixam de ser garantidos; fallback da VPS pode manter sync, mas precisa comprovação. | Conferir timer fallback, último sync, fila e último envio; não presumir que o container “healthy” prova publicação. |
| `botwhats` fallback, `ops/botwhats-cycle.sh` ou SQLite/volume | Sem redundância, ou risco de corrida/reenvio/estado perdido. | Verificar lock, marcador de tentativa, timer, volume, filas e contagem enviada antes de modificar. |
| OpenWA, rede `openwa_net`, webhook, sessão ou credenciais | Canal e consultas interativas param embora catálogo siga atualizando. | Verificar sessão `ready`, `engineLoaded`, webhook, rede, fila e último envio; não exigir navegador aberto. |
| `todas-as-vagas-whats/whatsapp-sync.yml` legado | Desativá-lo não deve afetar produção atual; **reativá-lo para envio** pode duplicar mensagens/usar estado errado. | Manter manual/dry-run até migração formal e teste de exclusão mútua. |
| Agente `.github/workflows/vagas.yml` | Somente recomendações pessoais ficam desatualizadas; catálogo e bots não dependem dele. | Verificar data do `output/` e URL da fonte `public-data`; não tratar falha do agente como falha da coleta. |
| Coletor privado de descrições / timer da VPS | Descrições completas deixam de enriquecer a base privada; vagas públicas continuam chegando. | Conferir timer, watchdog instalado, último avanço do SQLite e taxa de falhas; não inferir saúde pela contagem do site. |
| `vagas-remotas-inhire` independente | Seu site/snapshot separado envelhece; não há evidência de dependência da coleta InHire central. | Confirmar referências reais no código antes de remover; testar os dois projetos separadamente. |

### Riscos e correções em acompanhamento observados em 2026-10-17

- **Alta prioridade — recuperador da VPS:** timer e serviço de sistema estão instalados; o timer está ativo, mas o serviço falha com HTTP 401 ao consultar o GitHub. O token do ambiente privado foi testado sem expor seu valor e recebeu HTTP 401. A redundância externa **permanece indisponível** até substituir a credencial local por uma válida; não disparar recuperação às cegas.
- **Alta prioridade — disco da VPS:** na última medição de 2026-10-17, `/` estava em 86% (38 GB usados de 45 GB; 6,3 GB livres), acima do limite de falha de 85% do `botwhats/vps-health.yml`. A causa adicional foi identificada no workflow `.github/workflows/pages.yml`: a etapa `Capturar fotografia anterior para proteção` criava um diretório `mktemp` com `data/vagas.json`, mas não o removia ao terminar. Foram encontrados 267 diretórios temporários correspondentes, somando cerca de 5,4 GB; a ausência de execução ativa foi confirmada e a remoção controlada dos diretórios ainda está pendente. A correção adiciona limpeza automática ao fim da etapa. A limpeza anterior removeu 63,83 MB de cache Docker antigo, cache apt e duas cópias incompletas de runner (587 MB cada, sem `.runner`, serviço ou processo); imagens, containers, volumes, banco privado, logs e runners ativos/configurados foram preservados. O timer diário limita novo acúmulo de cache de build.
- **Média prioridade — drift de infraestrutura:** `todas-as-vagas-descriptions-watchdog.service` está instalado/ativo na VPS, mas não consta dos arquivos rastreados no repositório central. Documentar/versar a unidade após comparar o conteúdo efetivo e o comportamento desejado.
- **Média prioridade — teste de guard do Telegram:** corrigido e mesclado no PR #16 do repositório `edsonjunioor32-todas-as-vagas-telegram`; os quatro casos passaram localmente e no workflow `Validar menus guiados do Telegram` (run 39047242932). Alteração limitada aos testes.
- **Média prioridade — CI de aderência:** corrigido e mesclado no PR #149; o workflow valida o CTA público, acompanha mudanças em `docs/index.html`/`docs/styles.css` e passou no run 39047220637. A validação de catálogo também passou (run 39047220595).
- **Média prioridade — instrução antiga de instalação:** `WORKFLOW_PARA_COPIAR.yml` tem cron, runner e política de concorrência antigos. O README foi corrigido para proibir sua cópia sobre `pages.yml`.
- **Observação:** o último workflow de produção do `botwhats` e os de Telegram consultados estavam bem-sucedidos; isso não elimina os riscos de disco/scheduler nem comprova que cada portal individual foi atualizado.

## Checklist obrigatório de impacto para mudanças futuras

1. Identificar arquivo, workflow, branch, serviço instalado e todos os consumidores na matriz; buscar referências no código **e na configuração de produção**.
2. Separar “coleta”, “publicação”, “recuperação”, “notificação”, “consulta” e “observabilidade”: um run verde em uma etapa não atesta as demais.
3. Verificar última execução, próximo horário UTC, fila/checkpoint, data do snapshot e contagem por portal antes e depois. Para alterações de IDs/URLs/esquema, testar site, Telegram, WhatsApp e agente.
4. Para desativar agenda ou fonte, demonstrar substituto ativo e definir rollback; não ativar publicadores legados em paralelo.
5. Atualizar este arquivo e o inventário central quando árvores/contratos mudarem; comparar todas as árvores Git (`main` dos seis repositórios mais `public-data`/`history-data`) com as linhas do mapa. Não registrar secrets, dados pessoais nem conteúdo das descrições privadas.
