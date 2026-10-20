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

## 2026-10-05 — Falha de publicação por termos com aparência de PII

- A coleta do catálogo concluiu, mas a publicação foi bloqueada em `validate_fit.py`: um termo do vocabulário do índice auxiliar de aderência correspondia ao padrão de e-mail/telefone. O valor é deliberadamente omitido dos logs e deste registro.
- A causa estava no pipeline: `fit_requirements.export_fit_index` cria a lista global de termos e referências; `pipeline_fit` enriquecia/quarentenava metadados de vagas, mas não isolava termos PII. Como a validação ocorria antes da publicação, um único termo interrompia a atualização inteira.
- Correção implementada no PR #141: remover do índice de aderência termos que correspondam aos padrões de e-mail/telefone, reindexar as referências restantes e excluir do índice apenas vagas que ficarem sem requisitos; manter a validação final rígida. Os logs registram somente contagens, nunca os valores sinalizados. O catálogo público principal não é alterado por essa quarentena.
- Testes: 30 testes focados passaram (extração do índice, exportação, quarentena de vagas/termos, merge dinâmico e validação do snapshot); teste integrado confirma que o pipeline sanitiza o índice antes do validador completo.
- PR #141 mesclado em `main` no commit `c3644437919e498b69ecbc209506af6dc3986f68`.
- A execução #828 foi iniciada com o código anterior ao merge e falhou na validação; portanto, não publicou. A #829 terminou com sucesso, mas o evento de merge executou apenas a publicação da interface e pulou a coleta — sucesso desse run não significava atualização dos dados do catálogo.
- A recuperação #830 (`repository_dispatch`) executou o commit corrigido, concluiu coleta e validação, publicou banco histórico e snapshots e implantou o GitHub Pages com sucesso em 2026-10-06 00:41 UTC (2026-10-05 21:41 BRT). [Run #830](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/37392384422). O site publicado é https://edsonjunioor32.github.io/todas-as-vagas/.
- A publicação de produção foi confirmada no log do deploy do Pages (`Reported success!`). Nenhuma alteração foi feita na VPS.

## 2026-10-03 — Espaço da VPS

- O alerta do disco do runner está no workflow `vps-health.yml` do repositório `botwhats` (aviso em 75%, falha em 85%).
- Sem build ativo, foi executado `docker builder prune --filter until=168h --force` na VPS. Somente cache de build sem uso há mais de sete dias foi removido: 3,101 GB. A ocupação de `/` passou de 85% para 78%; imagens, volumes, containers e dados privados não foram apagados.
- Antes de repetir a limpeza, verificar `Runner.Worker`, builds ativos, `docker system df` e `df -h /`. Evitar `docker system prune` ou exclusão de diretórios de runner sem inventário.

## 2026-10-16 — Auditoria de CI, recuperação e consumidores

- As falhas dos runs [38885541172](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/38885541172) e [38885541248](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/38885541248) tinham a mesma causa: aspas faltantes na linha 77 de `notify_telegram.py` em um PR. Os runs seguintes de PR e de `main` passaram; não há motivo para reverter a correção.
- O run [38925041698](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/38925041698) do recuperador recebeu HTTP 504 ao consultar a API do GitHub. A consulta agora repete somente falhas transitórias de rede ou HTTP 502/503/504, com limite de três tentativas; erros de autenticação continuam falhando imediatamente. Runs posteriores do recuperador concluíram com sucesso.
- O agente externo `agente-vagas-edson` falhava diariamente com HTTP 404: seu `SOURCE_URL` padrão apontava para `main/docs/data/vagas.json`, que não existe mais. O catálogo ativo está em `public-data/data/vagas.json`; a correção e o teste de regressão ficam naquele repositório.
- Não ativar `WORKFLOW_PARA_COPIAR.yml` ou os gatilhos manuais legados só por não serem executados automaticamente. O workflow de Telegram neste repositório é operacional/manual; o envio regular pertence ao repositório dedicado. Rodá-lo automaticamente aqui pode duplicar mensagens.

## 2026-10-17 — Falhas do scheduler, disco e validações

- O timer `todas-as-vagas-github-scheduler.timer` está instalado como unidade de sistema e ativo. O serviço consulta o GitHub usando o token de `/home/ubuntu/.config/todas-as-vagas/github-scheduler.env`; a validação HTTP sem imprimir a credencial retornou 401. O token salvo na VPS precisa ser substituído por uma credencial válida com acesso Actions ao repositório `edsonjunioor32/todas-as-vagas`; não basta o secret correspondente existir no GitHub, pois secrets não sincronizam automaticamente para a VPS.
- A partição raiz estava em 86% na verificação inicial (38 GB usados, 6,3 GB livres, capacidade exibida de 45 GB). A investigação identificou 267 diretórios órfãos sob `/tmp` (cerca de 5,4 GB), cada um criado pela etapa `Capturar fotografia anterior para proteção` de `.github/workflows/pages.yml`; o passo não removia sua pasta `mktemp`. A correção passa a remover o diretório no encerramento da etapa. A remoção controlada dos órfãos e a medição posterior ainda estão pendentes nesta revisão. Imagens, containers, volumes, banco privado, logs e runners ativos/configurados não fazem parte dessa limpeza.
- Para limitar recorrência, `ops/systemd/todas-as-vagas-docker-cache-prune.service` e `.timer` foram mesclados no PR #149, instalados e habilitados na VPS. A execução diária usa `docker builder prune --filter until=168h --force` após confirmar resposta do daemon; não remove imagens, containers ou volumes. Próxima execução mostrada pelo systemd: 2026-10-18 04:08 UTC. Esta manutenção não reduz a ocupação estrutural atual.
- `fit-ci.yml` foi ajustado para validar a entrada pública do analisador e incluir `docs/index.html`/`docs/styles.css` nos filtros de execução. `prepare_fit_assets.py` valida semanticamente o link visível, sua rota e os ativos; três testes focados passaram.
- `edsonjunioor32-todas-as-vagas-telegram/tests/test_sync_guard.py` foi convertida para `unittest.TestCase`, compatível com descoberta e execução direta pelo workflow; os quatro casos passaram localmente.
- Estado final desta rodada: PR #149 (portal/limpeza limitada) e PR #16 (testes do guard do Telegram) foram mesclados; os workflows associados terminaram verdes. O timer de cache está ativo na VPS. A redundância do scheduler ainda está indisponível até a credencial local ser renovada; a health check de disco continua falhando enquanto `/` permanecer acima de 85%.

## Mapa dos arquivos rastreados

Escopo: 173 arquivos rastreados da branch `main` nesta revisão, incluindo `AGENTS.md` e `ops/ECOSYSTEM_MAP.md`. Cada linha registra a responsabilidade do arquivo; `manual` e `legado` não significam falha. Os arquivos das branches `public-data`/`history-data`, os repositórios dos bots, o agente e o projeto InHire separado estão inventariados no [mapa do ecossistema](ECOSYSTEM_MAP.md), que também contém a matriz de riscos e o checklist de mudanças. Cache, banco privado da VPS e arquivos ignorados não são parte desta lista de arquivos rastreados.

### Raiz e automação GitHub

- `AGENTS.md` — exige análise de impacto e atualização do mapa antes de mudanças operacionais.
- `.github/telegram-trigger` — marcador histórico de acionamento pontual do Telegram; não é agenda.
- `.github/telegram_state.json` — estado de deduplicação do envio manual do Telegram.
- `.github/workflows/benchmark-solides.yml` — diagnóstico isolado da Sólides em pushes filtrados de `main` ou manualmente; não publica catálogo.
- `.github/workflows/catalog-catchup.yml` — vigia atrasos e despacha recuperação do catálogo.
- `.github/workflows/catalog-ci.yml` — validação sem publicação em PRs filtrados ou manualmente.
- `.github/workflows/fit-ci.yml` — testes e preview do analisador; verifica a entrada pública e dispara quando o CTA ou estilo do portal muda.
- `.github/workflows/mercado-livre-isolated.yml` — validação isolada do coletor Mercado Livre.
- `.github/workflows/merge-dynamic-portals.yml` — mesclagem controlada de portais dinâmicos.
- `.github/workflows/pages.yml` — coleta em quatro horários diários e um horário semanal Greenhouse, acionamento manual/recuperação e deploy de interface em push; push comum pode publicar apenas a interface.
- `.github/workflows/telegram.yml` — envio operacional/manual e estado do Telegram.
- `.github/workflows/ux-preview.yml` — validação da interface em PRs.
- `.github/workflows/validate-dynamic-portals.yml` — valida portais dinâmicos em PRs, varredura semanal e execução manual; não publica catálogo.
- `.gitignore` — ignora saídas geradas e caminhos privados específicos; não substitui revisão de segredos.
- `LICENSE` — licença do repositório.
- `README.md` — visão geral, operação e integrações Telegram/WhatsApp.
- `THIRD_PARTY_NOTICES.md` — atribuições e licenças de terceiros.
- `WORKFLOW_PARA_COPIAR.yml` — modelo obsoleto fora do Actions; **não copiar sobre o `pages.yml` atual**, pois agenda, runner e recuperação divergem.
- `package.json` — dependências e scripts Node do site e do pré-processamento.

### Descoberta InHire e site público

- `busca_vagas/build_public_inhire.js` — constrói lote público InHire a partir da descoberta.
- `busca_vagas/harvest_inhire_public.js` — descobre vagas públicas InHire.
- `busca_vagas/inhire_tenants_seed.json` — sementes de empresas InHire.
- `busca_vagas/validate_public_inhire.js` — valida lote InHire antes da publicação.
- `docs/.refresh-fit-request` — marcador histórico de atualização solicitada; não é rotina.
- `docs/aderencia/app.js` — compara currículo com descrição de vaga informada pela pessoa no navegador; não lê o SQLite privado de descrições.
- `docs/aderencia/fit-engine.js` — regras de cálculo de aderência no navegador.
- `docs/aderencia/index.html` — página da análise de currículo.
- `docs/aderencia/styles.css` — estilos da página de aderência.
- `docs/app.js` — lógica da busca, filtros e cartões do portal.
- `docs/assets/todos-os-cursos-icon.jpg` — ícone do atalho Todos os Cursos.
- `docs/data/fit-taxonomy.json` — taxonomia pública do analisador.
- `docs/data/greenhouse-watchlist.json` — lista pública de empresas Greenhouse acompanhadas.
- `docs/favicon.svg` — favicon do portal.
- `docs/filter-terms.js` — normalização e termos de filtros.
- `docs/fit-entry.css` — estilos de entrada para o analisador.
- `docs/fit-entry.js` — CTA/entrada do analisador no portal.
- `docs/index.html` — estrutura da página inicial.
- `docs/og-image.svg` — imagem social do portal.
- `docs/redesign-grid.css` — grade responsiva do redesenho.
- `docs/redesign.css` — estilos do redesenho.
- `docs/robots.txt` — instruções de indexação por robôs.
- `docs/smartrecruiters-brazil.md` — notas da coleta SmartRecruiters Brasil.
- `docs/styles.css` — estilos gerais do portal.
- `docs/theme.js` — comportamento de tema visual.

### Núcleo da coleta e arquivos de dados

- `jobs-dashboard/benchmark_solides.py` — mede o comportamento da fonte Sólides; uso diagnóstico.
- `jobs-dashboard/catalog_catchup.py` — decide atrasos/recuperação sem sobrepor coleta ativa.
- `jobs-dashboard/classify.py` — classificação e normalização de vagas.
- `jobs-dashboard/data/greenhouse_br_companies.json` — empresas brasileiras descobertas no Greenhouse.
- `jobs-dashboard/data/greenhouse_watchlist.json` — empresas Greenhouse sob acompanhamento.
- `jobs-dashboard/data/revolut_br_seed.json` — semente de vagas brasileiras da Revolut.
- `jobs-dashboard/description_crawler.py` — coleta separada de descrições completas para SQLite privado.
- `jobs-dashboard/description_store.py` — persistência e estado da coleta privada.
- `jobs-dashboard/discover_greenhouse_br.py` — descobre empresas/vagas Greenhouse no Brasil.
- `jobs-dashboard/empregare_mcp.py` — consulta diagnóstica/manual da fonte Empregare via MCP.
- `jobs-dashboard/fit_requirements.py` — extrai requisitos e termos do índice de aderência.
- `jobs-dashboard/merge_dynamic_portals.py` — mescla resultados dos portais dinâmicos.
- `jobs-dashboard/notify_telegram.py` — formata e envia notificações Telegram com deduplicação.
- `jobs-dashboard/pipeline.py` — coordena coletores, histórico e snapshot público.
- `jobs-dashboard/pipeline_fit.py` — gera índice auxiliar de aderência.
- `jobs-dashboard/requirements.txt` — dependências Python da coleta e validação.
- `jobs-dashboard/storage.py` — histórico SQLite e exportação compacta do snapshot.
- `jobs-dashboard/validate_dynamic_portals.py` — valida seleção/resultados dos portais dinâmicos.
- `jobs-dashboard/validate_fit.py` — valida índice de aderência antes da publicação.
- `jobs-dashboard/validate_snapshot.py` — valida integridade e segurança do snapshot.

### Fontes de vagas

O registro de adaptadores fica em `jobs-dashboard/sources/__init__.py`. Cada módulo abaixo implementa coleta de uma plataforma, empresa ou grupo; estar registrado **não comprova** alimentação saudável em produção. Algumas fontes podem estar pausadas ou preservando vagas anteriores após falha; verifique contagem/estado por portal. Módulos auxiliares são chamados pelos coletores, não têm agendamento próprio.

- `jobs-dashboard/sources/__init__.py` — importa e registra as fontes ativas.
- `jobs-dashboard/sources/_common.py` — utilitários comuns de normalização.
- `jobs-dashboard/sources/_html.py` — extração/parsing HTML compartilhados.
- `jobs-dashboard/sources/_http.py` — requisições HTTP compartilhadas.
- `jobs-dashboard/sources/_rendered.py` — captura de páginas renderizadas.
- `jobs-dashboard/sources/abler.py` — fontes da plataforma Abler.
- `jobs-dashboard/sources/accenture.py` — vagas Accenture.
- `jobs-dashboard/sources/ats_boards.py` — quadros Greenhouse, Lever e Ashby.
- `jobs-dashboard/sources/bradesco.py` — vagas Bradesco.
- `jobs-dashboard/sources/company_careers.py` — carreiras Stone e iFood.
- `jobs-dashboard/sources/compleo.py` — empresas na plataforma Compleo.
- `jobs-dashboard/sources/convagas.py` — fontes da plataforma Convagas.
- `jobs-dashboard/sources/digisystem.py` — vagas Digisystem.
- `jobs-dashboard/sources/eightfold.py` — fonte Vale na plataforma Eightfold.
- `jobs-dashboard/sources/empregare.py` — vagas Empregare.
- `jobs-dashboard/sources/experian.py` — vagas Experian.
- `jobs-dashboard/sources/ey.py` — vagas EY.
- `jobs-dashboard/sources/geekhunter.py` — GeekHunter e NTT Data.
- `jobs-dashboard/sources/github_boards.py` — fontes de vagas publicadas no GitHub.
- `jobs-dashboard/sources/gupy.py` — vagas Gupy.
- `jobs-dashboard/sources/infojobs.py` — funções de coleta InfoJobs (fuso Brasil).
- `jobs-dashboard/sources/inhire.py` — vagas InHire.
- `jobs-dashboard/sources/jobii.py` — vagas Jobii.
- `jobs-dashboard/sources/journy.py` — vagas Journy.
- `jobs-dashboard/sources/levva.py` — vagas Levva.
- `jobs-dashboard/sources/mercadolivre.py` — vagas Mercado Livre.
- `jobs-dashboard/sources/nerdin.py` — vagas Nerdin.
- `jobs-dashboard/sources/ngcash.py` — vagas NG.CASH.
- `jobs-dashboard/sources/ntconsult.py` — vagas NTConsult/Compleo.
- `jobs-dashboard/sources/oracle_careers.py` — empresas em Oracle Careers.
- `jobs-dashboard/sources/pwc.py` — vagas PwC.
- `jobs-dashboard/sources/quickin.py` — vagas na plataforma Quickin.
- `jobs-dashboard/sources/recrut_ai.py` — empresas na plataforma Recrut.ai.
- `jobs-dashboard/sources/recrutei.py` — vagas Recrutei.
- `jobs-dashboard/sources/remote_boards.py` — agregadores de trabalho remoto.
- `jobs-dashboard/sources/requested_careers.py` — empresas de carreira solicitadas individualmente.
- `jobs-dashboard/sources/requested_portals_03092026.py` — grupo de portais incluídos em 03/09.
- `jobs-dashboard/sources/requested_portals_16092026.py` — grupo de portais incluídos em 16/09.
- `jobs-dashboard/sources/requested_portals_27082026.py` — grupo de portais incluídos em 27/08.
- `jobs-dashboard/sources/requested_portals_28082026.py` — grupo de portais incluídos em 28/08.
- `jobs-dashboard/sources/requested_portals_29082026.py` — grupo de portais incluídos em 29/08.
- `jobs-dashboard/sources/requested_portals_aug2026.py` — demais portais solicitados em agosto.
- `jobs-dashboard/sources/sankhya_senior.py` — vagas Sankhya e Senior.
- `jobs-dashboard/sources/smartrecruiters_brazil.py` — empresas SmartRecruiters no Brasil.
- `jobs-dashboard/sources/solides.py` — vagas Sólides.
- `jobs-dashboard/sources/spassu.py` — vagas Spassu.
- `jobs-dashboard/sources/taggui.py` — vagas Taggui RH.
- `jobs-dashboard/sources/themuse.py` — vagas The Muse.
- `jobs-dashboard/sources/totvs.py` — vagas TOTVS.
- `jobs-dashboard/sources/trakstar.py` — vagas Sensedia via Trakstar.
- `jobs-dashboard/sources/unlockcareer.py` — vagas Mavila Consulting via UnlockCareer.
- `jobs-dashboard/sources/vagascom.py` — vagas Vagas.com.
- `jobs-dashboard/sources/valorei.py` — vagas Valorei.
- `jobs-dashboard/sources/wellfound.py` — vagas Wellfound.
- `jobs-dashboard/sources/wise.py` — vagas Wise.
- `jobs-dashboard/sources/workable.py` — vagas RecargaPay via Workable.
- `jobs-dashboard/sources/workable_brazil.py` — busca Workable no Brasil.
- `jobs-dashboard/sources/wwr.py` — vagas We Work Remotely.

### Testes do coletor

Todos os arquivos desta seção são testes automatizados; não são coletores nem devem ser agendados como fontes.

- `jobs-dashboard/tests/test_abler_precision.py` — precisão Abler e formato Telegram.
- `jobs-dashboard/tests/test_catalog_catchup.py` — decisões e falhas do recuperador.
- `jobs-dashboard/tests/test_description_crawler.py` — extração de descrições.
- `jobs-dashboard/tests/test_dynamic_portals.py` — contratos dos portais dinâmicos.
- `jobs-dashboard/tests/test_eightfold.py` — fonte Eightfold.
- `jobs-dashboard/tests/test_fit_requirements.py` — extração de requisitos.
- `jobs-dashboard/tests/test_gupy.py` — fonte Gupy.
- `jobs-dashboard/tests/test_homepage_cta_styles.py` — CTAs da página inicial.
- `jobs-dashboard/tests/test_mercadolivre.py` — fonte Mercado Livre.
- `jobs-dashboard/tests/test_merge_dynamic_portals.py` — mesclagem dinâmica.
- `jobs-dashboard/tests/test_new_sources.py` — fontes recém-incorporadas.
- `jobs-dashboard/tests/test_ngcash.py` — fonte NG.CASH.
- `jobs-dashboard/tests/test_notify_telegram.py` — notificação Telegram.
- `jobs-dashboard/tests/test_ntconsult.py` — fonte NTConsult.
- `jobs-dashboard/tests/test_pipeline.py` — orquestração e persistência.
- `jobs-dashboard/tests/test_portal_source_resilience.py` — isolamento de falhas de fontes.
- `jobs-dashboard/tests/test_prepare_fit_assets.py` — valida o ponto público de entrada e os ativos locais do analisador.
- `jobs-dashboard/tests/test_private_descriptions.py` — banco privado de descrições.
- `jobs-dashboard/tests/test_publication_concurrency.py` — prevenção de publicações concorrentes.
- `jobs-dashboard/tests/test_pwc_source.py` — fonte PwC.
- `jobs-dashboard/tests/test_quickin_pagination.py` — paginação Quickin.
- `jobs-dashboard/tests/test_recrut_ai_sources.py` — fontes Recrut.ai.
- `jobs-dashboard/tests/test_recrutei_current_markup.py` — HTML atual Recrutei.
- `jobs-dashboard/tests/test_rendered_browser.py` — navegador renderizado.
- `jobs-dashboard/tests/test_requested_portals_16092026.py` — portais do lote de 16/09.
- `jobs-dashboard/tests/test_schedule.py` — agenda e recuperação na VPS.
- `jobs-dashboard/tests/test_smartrecruiters_brazil.py` — fonte SmartRecruiters.
- `jobs-dashboard/tests/test_trakstar.py` — fonte Trakstar.
- `jobs-dashboard/tests/test_vagascom.py` — fonte Vagas.com.
- `jobs-dashboard/tests/test_validate_dynamic_portals.py` — seleção/validação dinâmica.
- `jobs-dashboard/tests/test_validate_snapshot.py` — integridade do snapshot.
- `jobs-dashboard/tests/test_valorei.py` — fonte Valorei.

### Operação, scripts e testes Node

- `ops/OPERATIONS_CHANGELOG.md` — histórico operacional e este mapa de responsabilidades.
- `ops/ECOSYSTEM_MAP.md` — inventário dos repositórios vinculados, branches de dados, dependências e riscos.
- `ops/github_scheduler.py` — agendador externo da VPS, com estado de tentativas.
- `ops/systemd/actions-runner-restart.conf` — política de reinício do runner.
- `ops/systemd/todas-as-vagas-descriptions.service` — serviço de coleta privada de descrições.
- `ops/systemd/todas-as-vagas-descriptions.timer` — agenda da coleta privada.
- `ops/systemd/todas-as-vagas-github-scheduler.service` — unidade do agendador GitHub na VPS.
- `ops/systemd/todas-as-vagas-github-scheduler.timer` — timer de verificação da agenda.
- `ops/systemd/todas-as-vagas-docker-cache-prune.service` — confirma a disponibilidade do daemon e limpa cache de build Docker antigo, sem tocar em imagens, containers ou volumes.
- `ops/systemd/todas-as-vagas-docker-cache-prune.timer` — agenda diária da limpeza limitada de cache Docker.
- `tools/ensure_chromium.sh` — prepara Chromium ARM64 para a coleta.
- `tools/excluded-terms.test.mjs` — testa exclusões dos filtros.
- `tools/filter-state.test.mjs` — testa persistência/estado de filtros.
- `tools/fit-engine.test.mjs` — testa o motor de aderência no navegador.
- `tools/iniciar-preview.bat` — abre prévia local no Windows; uso manual.
- `tools/prepare_fit_assets.py` — prepara ativos públicos do analisador.
- `tools/preview_server.ps1` — servidor local de prévia; uso manual.
- `tools/refresh_request.txt` — registro histórico de pedido manual de atualização.
- `tools/update_nerdin.py` — manutenção pontual da fonte Nerdin; uso manual.

## 2026-10-17 — Correção de metadados INSI e HUNT IT

- INSI: o título agora ignora o cabeçalho genérico "Descrição da Vaga" e a modalidade é extraída do cabeçalho curto; "Híbrido" não é sobrescrito por menções posteriores a "remoto" na descrição.
- HUNT IT: a coleta consulta o JSON-LD das páginas de detalhe para obter título, localidade, modalidade e datePosted, mantendo a URL listada pelo portal.
- Datas do catálogo: publishedAt só é preenchido quando há data fornecida pelo portal. Sem essa informação, a interface exibirá "Vista em" usando a data de observação.
- Inferência: país Brasil sem localidade explícita deixou de ser evidência suficiente para classificar uma vaga como remota.
- Retenção: HUNT IT foi incluído entre os quadros públicos ativos, pois a listagem atual é a evidência de que anúncios antigos continuam abertos.
- Validação: compilação Python, 8 testes de Recrut.ai, 35 testes de pipeline e consulta real aos dois anúncios passaram. A suíte completa executou 299 testes; 2 testes preexistentes de UnlockCareer não puderam iniciar por falta do pacote Selenium na VPS.
- HUNT IT: a localidade pública é normalizada para cidade/UF (por exemplo, São Paulo, SP), mantendo BR no campo de país.\n


## 2026-10-20 — Bloqueio de publicação por contrato visual do portal

- As execuções [#911](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/39355084548) e [#912](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/39355174955) falharam antes da coleta. As mensagens `[compleo:mootit]` sobre `jobdetail/1` e `jobdetail/bad` são fixtures dos testes de indisponibilidade e não representam anúncios reais; os testes do adaptador Compleo passaram.
- A causa efetiva foram duas asserções de `test_homepage_cta_styles.py`: `docs/styles.css` havia perdido o grid desktop esperado e as dimensões responsivas dos CTAs. Como `pages.yml` executa os testes antes da coleta, o passo de coleta/publicação foi pulado e o catálogo permaneceu no último snapshot válido.
- O PR [#155](https://github.com/edsonjunioor32/todas-as-vagas/pull/155) corrigiu somente `docs/styles.css`, preservando o tratamento de falhas dos coletores. Os workflows de validação [#333](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/39432044252) e [#37](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/39432044315) passaram; o PR foi mesclado no commit `f3294b692763f73363ba2c1fd29d662f82384506`.
- O push gerou a execução [#913](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/39432224034), que publicou apenas a interface (`atualizar-e-publicar` ficou pulado por ser evento de push). Portanto, “success” dessa execução não confirma nova coleta. Na verificação posterior, o snapshot público ainda informava `generated_at=2026-10-18T01:39:24Z`, `count=74117` e `307` fontes; aguardar/confirmar a próxima execução de coleta agendada ou de recuperação.
- O scheduler externo da VPS continua retornando HTTP 401 ao consultar o GitHub. Nenhuma credencial, fila, banco ou unidade systemd foi alterada nesta correção; a renovação do token continua sendo uma ação operacional separada.

## 2026-10-20 — Preflight obrigatório antes da coleta e publicação

- Foi adicionada a rotina `jobs-dashboard/preflight_catalog.py`, com testes unitários em `jobs-dashboard/tests/test_preflight_catalog.py`. Ela valida a fotografia pública anterior antes da coleta e valida o novo snapshot antes de qualquer escrita em `history-data`, `public-data` ou no GitHub Pages.
- O preflight bloqueia a publicação quando faltam colunas/dicionários do contrato público, há campos privados, o corte de dois meses não é `2`, o snapshot é inválido/futuro, o timestamp não avançou ou há redução insegura do volume.
- Depois do push, o workflow compara o SHA anterior e o novo de `public-data` e confere byte a byte `data/vagas.json` e `data/fit.json` publicados. Assim, um job verde que só publique a interface não é tratado como coleta concluída.
- O `pages.yml` continua executando a suíte completa antes da coleta e agora adiciona as duas barreiras nomeadas. Isso evita que uma execução seja considerada saudável sem produzir um snapshot novo.
- A recuperação #914 já estava em execução durante esta alteração; nenhuma segunda coleta foi disparada. A causa do bloqueio de 18/10 foi registrada acima e permanece separada da rotina de preflight.

## 2026-10-20 — Correção da ordem do gate de publicação

- A confirmação de mudança do ramo `public-data` foi reposicionada para depois do passo que realiza o push dos snapshots e antes da publicação do Pages. O gate deixa de bloquear por posição e passa a validar o resultado efetivamente publicado.
