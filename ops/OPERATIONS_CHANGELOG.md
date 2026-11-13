## 2026-11-13 — Filtros de empresa e avaliação na interface

- **Interface:** adicionados filtros dedicados por empresa e por avaliação oficial do Glassdoor, incluindo a opção de mostrar somente vagas sem avaliação.
- **Ordenação:** adicionada a opção `Melhor avaliação`; notas oficiais são ordenadas de forma decrescente e vagas sem nota ficam no final.
- **Persistência:** os novos critérios são preservados na URL, nos chips de filtros, na limpeza e na exportação CSV.
- **Regra de dados:** o filtro e a ordenação usam somente `glassdoorRating`; o fallback não é misturado com a nota oficial.
- **Validação:** a sintaxe e os workflows do frontend devem confirmar a alteração antes da publicação.

## 2026-11-12 — Cobertura Glassdoor para todas as empresas do catálogo

- A rotina deixou de limitar o enriquecimento às quatro empresas do manifesto canônico. Ela agora extrai todos os nomes únicos do snapshot público e mantém uma fila `catalog_profiles` resumível no cache público.
- Empresas novas são consultadas pelo scraper Omkar em lotes de até 100 por execução agendada, com limite manual configurável até 1.000. O workflow continua separado da coleta de vagas e a execução diária permanece idempotente por empresa e data local.
- Cada consulta usa o nome do catálogo como único alias aprovado. O retorno só é aceito com correspondência exata após normalização; colisões, empresa divergente, ausência de média e falhas permanecem sem nota e não apagam a última nota válida.
- Perfis descobertos sem URL canônica confirmada podem fornecer apenas média e quantidade de avaliações. Nenhuma URL de Glassdoor é inventada; links continuam restritos a perfis HTTPS validados.
- O fallback HasData segue separado e limitado aos perfis canônicos aprovados. Nenhum texto de avaliação é coletado ou publicado.
- Foram adicionados testes de descoberta em lote, preservação de cache, enriquecimento de empresa descoberta e validação do novo parâmetro do workflow. A suíte completa local passou com 455 testes.

## 2026-11-12 — Reprocessamento de descrições vazias após evolução do parser

- A fila privada agora reprocessa imediatamente registros sem descrição cujo `parser_version` ficou atrás do parser atual. O backoff continua valendo depois que a tentativa já passou pelo parser vigente.
- Registros que já possuem descrição não entram nesse reprocessamento automático; a rotina mantém a janela normal de atualização para evitar tráfego e custo desnecessários.
- Vagas InHire vazias são priorizadas dentro do lote porque a API pública específica já foi validada como capaz de recuperar anúncios ativos que a página inicial renderiza apenas como shell. Anúncios que retornarem HTTP 404/410 continuam sendo classificados como `gone`.
- Foram adicionados testes de regressão para a migração de parser, prioridade do InHire e preservação do backoff.

## 2026-11-12 — InHire API antes da página renderizada

- O coletor agora consulta primeiro a API pública do InHire para URLs compatíveis, evitando baixar a página SPA apenas para descobrir que ela é um shell sem descrição.
- O HTML e o Obscura continuam como fallback somente quando a API está indisponível ou não consegue decidir; HTTP 404/410 e descrições válidas são persistidos diretamente.
- A versão do parser foi incrementada para `description-crawler-v3`, reabrindo somente registros sem descrição para a nova estratégia; descrições já armazenadas continuam fora do reprocessamento em massa.

## 2026-11-12 — Coleta diária da média geral pelo scraper de classificações

- O teste isolado do `omkarcloud/glassdoor-scraper` confirmou a rota `/companies/ratings` e retornou a média oficial da Heineken Brasil como `4,0`, sem necessidade de ler o conteúdo textual das avaliações.
- A rotina diária passou a iniciar esse scraper em container temporário no runner dedicado do catálogo, fixado no commit `0567eb6ef90674aacde32e79ee668c09f23d91be`, exposto somente em `127.0.0.1:18081` e encerrado ao final da execução.
- `jobs-dashboard/glassdoor.py` consulta apenas `ratings.overall` e `reviews_count`, exige correspondência do nome retornado com os aliases aprovados e preserva o cache anterior quando a fonte falha. O fallback HasData continua separado, não promove nota de vaga a nota oficial do perfil e deixa de ser exibido quando já existe uma média oficial.
- Os perfis aprovados agora declaram explicitamente o nome usado no scraper (`scraper_company`), evitando que aliases globais sejam confundidos com a empresa brasileira correta.
- A rotina foi executada antes desta alteração com sucesso operacional, mas encontrou `0` perfis oficiais novos; o resultado justificou a integração desta fonte específica. A execução #13 após a mesclagem também não consultou os perfis porque o carimbo diário já estava preenchido por tentativas anteriores.
- Validação local: suíte completa com 452 testes aprovada, além de compilação, YAML e `git diff --check`.

### Correção da execução pontual

- A primeira execução após o deploy encontrou os quatro perfis como já verificados no dia e, por isso, não chamou o novo scraper; o cache público permaneceu sem médias oficiais. A rotina diária continua idempotente, mas agora o `workflow_dispatch` oferece `force_refresh` para uma recuperação controlada.
- O modo forçado usa `--force` somente na execução manual solicitada; não muda a cadência agendada, não remove dados válidos e continua preservando o cache anterior em caso de falha.
- O run manual #14 (`43325577409`) foi executado com `force_refresh=true` e terminou com `4` perfis atualizados, `0` falhas e `0` perfis ignorados. O container foi encerrado e removido ao final.
- O cache público passou a registrar: Accenture `3,7` (231.289 avaliações), Heineken Brasil `4,0` (245), Sicredi `4,3` (5.482) e Skeelo `4,2` (142). O deploy do Pages foi concluído no mesmo run; a fonte pública ficou no commit `2e31d85` do ramo `public-data`.

## 2026-11-12 — Uso restrito do campo `overallRating` do perfil Glassdoor

- Incorporada somente a parte necessária do `omkarcloud/glassdoor-scraper`: o reconhecimento de `ratings.overallRating` em metadados estruturados do perfil público.
- Nenhum endpoint de avaliações, texto de reviews, salários, entrevistas, login, proxy ou bypass anti-bot foi incorporado. O fluxo continua usando os perfis canônicos aprovados, `robots.txt`, cache diário e fallback HasData já existente.
- A ausência ou falha da nota continua preservando o cache anterior; o portal nunca transforma ausência em `0,0`.
- Teste offline adicionado para comprovar a leitura da média geral e o descarte de texto de avaliação.

## 2026-11-11 — InHire API público e separação de anúncios removidos

- Adicionado `jobs-dashboard/inhire_descriptions.py`, que resolve o tenant público e consulta a API pública do InHire antes do fallback de navegador. A coleta não usa credenciais, não contorna `robots.txt` e não altera o catálogo público.
- Vagas InHire com HTTP 404/410 passam a ser registradas como `gone`/removidas, preservando uma descrição histórica já armazenada e evitando que uma vaga removida seja confundida com bloqueio, erro temporário ou ausência de texto.
- `description_quality.py` e `description_report.py` exibem a categoria removida separadamente. O armazenamento aplica backoff terminal de 30 dias e não reprocessa uma vaga removida apenas porque sua descrição antiga ficou fora da janela de atualização.
- Corrigido o relatório somente leitura para abrir o SQLite com URI compatível com Windows e Linux. O `parser_version` foi atualizado para `description-crawler-v2` para identificar o novo contrato de coleta.
- O Browserless não foi incorporado: a infraestrutura atual não possui esse serviço; o fallback existente continua sendo o Obscura, limitado por tempo, tamanho e política de acesso.
- Testes direcionados: InHire API, crawler privado, classificação de qualidade e relatório passaram; a compilação dos módulos alterados e `git diff --check` também passaram.

## 2026-11-11 — Contrato de qualidade das descrições privadas

- Criados jobs-dashboard/description_quality.py e jobs-dashboard/description_report.py. A classificação é derivada, explicável e não chama texto curto de descrição completa.
- O relatório é somente leitura: usa SQLite em modo ro e query_only, separa caracteres de bytes UTF-8 e agrupa qualidade, status, content_kind e portal.
- O crawler mantém as métricas existentes e acrescenta quality_this_run, quality_by_source_this_run e quality_scope. Esses campos descrevem somente as vagas processadas no ciclo.
- Baseline medido na VPS em 2026-11-11: 84.133 registros; 64.561 com texto; 33.378 candidatos extensos; 24.167 utilizáveis; 5.624 curtos; 5.957 vazios; 11.022 bloqueados; 1.392 stale; 2.593 pendentes.
- Os testes direcionados da Fase 1 passaram (31 testes). A suíte completa da cópia da VPS teve 406 aprovações e duas falhas/erros pré-existentes do UnlockCareer causados pela ausência do pacote Selenium naquela máquina; isso permanece separado da Fase 1.
- O relatório não executa sincronização de manifesto, limpeza, coleta, publicação ou fallback de navegador.

## 2026-11-11 — Inclusão do portal SONDA

- **Fonte pública:** `https://carrera.sonda.com/search/?q=&q2=&alertId=&title=&location=Brasil&department=`, portal de carreiras SAP SuccessFactors da SONDA.
- **Implementação:** `jobs-dashboard/sources/sonda.py` percorre a tabela pública de resultados, consulta as páginas individuais públicas e normaliza título, requisitado, localização, departamento, data `datePosted` e descrição pública.
- **Integração:** a fonte foi registrada no pipeline como `sonda`, com rótulo SONDA no site e nas notificações do Telegram. O filtro Brasil do portal é mantido; nenhuma credencial ou login é necessário.
- **Validação:** foram adicionados testes offline para parser, deduplicação dos links desktop/mobile, schema.org, data de publicação, modalidade explícita e registro da fonte. A execução ao vivo deve confirmar a contagem no workflow de validação antes de entrar na rotina regular.

## 2026-11-11 — Descoberta InHire fora da rotina horária

- **Verificação pós-mesclagem:** a próxima coleta completa será executada com a regra de descoberta semanal já publicada, evitando que a execução longa anterior seja usada como evidência do código antigo.

- **Coleta otimizada:** a etapa exploratória de novos tenants InHire deixa de rodar em todas as janelas do catálogo e passa a rodar no domingo, no slot semanal de descoberta, ou sob demanda. A coleta de tenants já conhecidos continua em cada atualização regular.
- **Motivo operacional:** Wayback, URLScan, crt.sh e Common Crawl são fontes exploratórias independentes e podem consumir vários minutos; separá-las reduz o tempo de cauda das atualizações frequentes sem perder a descoberta periódica de novas empresas.
- **Risco controlado:** uma empresa InHire recém-publicada pode entrar no catálogo na próxima descoberta semanal, mas as empresas já cadastradas não sofrem atraso. A etapa continua com tolerância a falhas e não bloqueia os demais portais.

## 2026-11-11 — Coleta pública independente da VPS e saúde dos canais

- **Coleta resiliente:** `.github/workflows/pages.yml` e `merge-dynamic-portals.yml` passaram a usar `ubuntu-latest` para a coleta pública e para a consolidação de portais dinâmicos. A indisponibilidade do runner da VPS deixou de ser um ponto único para o catálogo; a VPS continua responsável pelos dados privados, OpenWA, fallback e serviços persistentes.
- **Navegador otimizado:** `tools/ensure_chromium.sh` identifica ARM64 e x64, instala o par compatível de Chrome/ChromeDriver e usa cache do GitHub Actions. O limite de sessões renderizadas continua separado da concorrência HTTP (`COLLECTOR_BROWSER_WORKERS=2`) para reduzir saturação e timeouts.
- **Gates separados:** a coleta não executa mais a suíte completa do analisador de aderência antes de consultar os portais. O smoke do fit e a validação do `fit.json` continuam sendo executados, mas falham de forma não bloqueante; quando necessário, `pipeline_fit.py` e o workflow preservam o último índice de aderência válido. A validação estrutural, privacidade e preflight do catálogo continuam bloqueando publicação insegura.
- **Recuperação real:** `catalog-catchup.yml` agora despacha a recuperação para runner hospedado. O scheduler da VPS permanece como segunda via e mantém estado separado; a idempotência e os slots continuam obrigatórios para evitar duplicidade.
- **Observabilidade externa:** foram preparados monitores diários independentes para Telegram ([PR #17](https://github.com/edsonjunioor32/edsonjunioor32-todas-as-vagas-telegram/pull/17)) e WhatsApp ([PR #29](https://github.com/edsonjunioor32/botwhats/pull/29)). Eles verificam catálogo, permissões, webhook, sessão e prontidão sem enviar mensagens de teste. O monitor do WhatsApp exige secrets SSH no ambiente `production`; a sessão OpenWA ainda precisa estar autenticada para o canal voltar a publicar.
- **Validação local:** os testes direcionados de aderência/agendamento e os testes do recuperador passaram; a suíte completa e os checks dos PRs serão a validação final antes da mesclagem.

## 2026-11-10 — Correção da coleta contínua do LinkedIn e continuidade de catálogo em execuções parciais

- **Integração da PR #187 na `main`:** merged commit `e9ad241` trazendo a injeção mandatória de `geoId=106057199`, orçamento dinâmico na Fase 2 para mitigar timeouts de 45 min no CI e preservação atômica das modalidades históricas em `clear_linkedin_work_models`.
- **Condição de parada na paginação do LinkedIn (`tools/collect_linkedin.py`):** ajustada a verificação de interrupção para parar apenas em `len(batch) == 0` (ou ausência de novos registros) em vez de abortar prematuramente quando `len(batch) < results_wanted`, garantindo a coleta de snapshots completos mesmo com retornos parciais (< 100) do endpoint guest do LinkedIn.
- **Continuidade de fontes em coletas parciais (`jobs-dashboard/storage.py` e `pipeline.py`):** implementado suporte a `selected_sources` em `storage.prune` e `storage.export_snapshot`. Em execuções parciais (como `linkedin_refresh`), o corte da Gupy passa a respeitar o `cutoff` recente de 3 dias (em vez de exigir data estritamente de hoje), os feeds corporativos ativos (`ACTIVE_PUBLIC_FEED_SOURCES`) mantêm a isenção de publicação e falhas persistidas em `source_health` são mantidas em `failed_sources`, permitindo que `validate_snapshot.py` aprove o snapshot sem bloquear a publicação no GitHub Pages.
- **Compatibilidade de testes multiplataforma (`ops/github_scheduler.py` e `test_schedule.py`):** isolamento do módulo Unix `fcntl` com fallback para `msvcrt.locking` no Windows e guarda de verificação de permissão POSIX, permitindo a execução de 100% dos 371 testes unitários (incluindo agendador) em qualquer ambiente (Windows e Linux).
- **Validação:** 100% de sucesso nos 371 testes unitários do catálogo, agendador e pipeline.

## 2026-11-07 — Otimização e correções estruturais na coleta e persistência do LinkedIn

- **Orçamento dinâmico na Fase 2 (`tools/collect_linkedin.py`):** cálculo de `remaining = MAX_UNIQUE_RESULTS_PER_RUN - len(all_jobs_dict)`. Se `remaining <= 0`, a Fase 2 é pulada sem requisições desnecessárias; se `remaining > 0`, a consulta é estritamente limitada a `min(remaining, JOBSPY_MAX_RESULTS_PER_QUERY)` como limite efetivo, eliminando o download inútil e descarte de centenas de vagas que inflavam a duração do workflow no CI.
- **Isolamento do parser de candidatura (`_ApplicationCTAParser`):** detecção restrita ao cabeçalho/painel principal (`top-card-layout`, `top-card`, `topcard`) e controles prioritários (`apply-button`, `jobs-apply-button`), com suporte a atributos `value`/`name` para elementos de botão/input e ignorando explicitamente seções de vagas similares e carrosséis no rodapé (`similar-jobs`, `carousel`, `recommended-jobs`, `recommended`, `related-jobs`, `related`), prevenindo falsos positivos e sinais conflitantes.
- **Injeção de `geoId=106057199` do Brasil:** parâmetros de consulta ao LinkedIn guest recebem obrigatoriamente `geoId="106057199"` em `LinkedIn._search_params` e na sessão resiliente, garantindo que 100% dos resultados pertençam ao Brasil e prevenindo vazamento geográfico internacional.
- **Suporte e rastreabilidade de Candidatura Simplificada (`f_AL=true`):** adicionada flag `--easy-apply` no coletor e input `easy_apply_only` no workflow `linkedin-jobs.yml`. Quando ativo, JobSpy aplica o filtro nativo `f_AL=true` do LinkedIn e as vagas sem selo individual no HTML recebem proveniência explícita `query_filter_f_AL` e `filter: "easy_apply"` no snapshot, com enriquecimento hierárquico em duplicatas via `APPLICATION_EVIDENCE_PRIORITY`.
- **Preservação de modalidade histórica (`jobs-dashboard/storage.py`):** `clear_linkedin_work_models(conn, jobs=jobs, target_uids=target_uids)` corrigido para redefinir a modalidade estritamente das vagas fornecidas mesmo quando chamado apenas com `target_uids` ou lista vazia, evitando a limpeza inadvertida de toda a tabela e preservando intactas as modalidades históricas de vagas anteriores válidas do LinkedIn armazenadas no banco.
- **Validação:** 100% de aprovação na suíte de testes com 92 testes unitários (`test_linkedin.py`, `test_pipeline.py`, `test_preflight_catalog.py`, `test_validate_snapshot.py`).

## 2026-11-07 — Atualização integral após recuperação do runner

- **Execução confirmada:** o agendador da VPS repetiu de forma idempotente o slot pendente (`attempt=2`) após o merge do commit `07dab8c`; o workflow `42317073815` concluiu com sucesso.
- **Validação do fluxo:** Greenhouse, descoberta/coleta do InHire, consolidação dos portais, validações de integridade, publicação dos snapshots, preservação do histórico e deploy do GitHub Pages passaram sem falha.
- **Snapshot público conferido:** `generated_at=2026-11-07T01:07:31.591433+00:00`, `82.208` vagas, `64.052` coletadas na execução e `18.156` preservadas. Gupy voltou ao catálogo com `13.717` vagas; LinkedIn ficou com `2.043`, Skeelo com `14` e Heineken com `239`.
- **Pós-execução:** o runner permaneceu `active/running`, com `6,9 GB` livres (85% de uso) e `_diag` em `139 MB`. O snapshot foi conferido no endpoint público antes de encerrar a recuperação.

## 2026-11-06 — Recuperação do runner self-hosted do catálogo

- **Causa raiz confirmada:** a partição `/` da VPS `serverall` chegou a 100% (45 GB usados, 0 bytes livres). O runner `actions.runner.edsonjunioor32-todas-as-vagas.serverall-vagas` entrou em reinício a cada cinco segundos e falhou com `No space left on device` ao criar o próprio diagnóstico; a etapa de dependências da atualização não chegou à coleta.
- **Origem do crescimento:** o diretório `/home/ubuntu/actions-runner-todas-vagas/_diag` acumulou 285 arquivos `Runner_*.log` de aproximadamente 25 MB cada, cerca de 4,2 GB no total. Não foram removidos imagens, volumes, bancos, snapshots ou dados de vagas.
- **Ação operacional:** o serviço do runner do catálogo foi parado somente durante a limpeza, os 285 logs de diagnóstico foram removidos por padrão de nome restrito e o serviço foi iniciado novamente. O filesystem passou a 92% de uso, com cerca de 3,9 GB livres; o processo `Runner.Listener` e um `Runner.Worker` permaneceram ativos após a recuperação.
- **Validação:** a execução manual `42315018149` (`Execução manual do catálogo`, 23:55 UTC) avançou pelo preparo de dependências e Selenium, mas foi bloqueada pelo teste antigo do LinkedIn antes da coleta. A atualização só deve ser repetida depois da validação CI das correções de teste, sem publicar snapshot parcial.
- **Risco residual:** a margem de disco ainda exige monitoramento; o runner não deve acumular novamente diagnósticos sem retenção. A limpeza foi limitada aos logs do runner quebrado e é reversível apenas por nova execução/geração de diagnóstico, não por restauração de dados de vagas.

## 2026-11-06 — Bloqueio contra perda silenciosa de fontes em coleta parcial

- **Causa protegida:** execuções parciais, como `LinkedIn-only`, conseguiam publicar um snapshot menor sem declarar que as fontes presentes anteriormente não haviam sido consultadas. Isso podia retirar milhares de vagas de Gupy e de outros portais sem um erro explícito.
- **Validação implementada:** `validate_snapshot.py` agora compara `source_counts` com o snapshot anterior e bloqueia o publish quando uma fonte desaparece sem `failed_sources` explícito ou sem avanço do respectivo `source_last_success_at`.
- **Escopo observável:** `pages.yml` registra `CATALOG_COLLECTION_SCOPE=full` em coleta integral e `partial:linkedin` na atualização restrita; o workflow de portais dinâmicos registra `partial:dynamic`.
- **Regressão coberta:** testes verificam tanto o bloqueio da perda sem confirmação quanto a permissão para uma falha declarada.
- **Operação:** a atualização pontual deve usar coleta integral; execuções parciais continuam permitidas somente quando a validação confirma a continuidade das demais fontes.

## 2026-11-06 — Correção da modalidade remota do LinkedIn

- **Causa raiz confirmada:** a busca pública guest atual do LinkedIn ignora o filtro legado `f_WT=2`, e o JobSpy usado pelo coletor ignora `is_remote` para essa fonte. Portanto, aquela busca pode devolver vagas presenciais e híbridas. A implementação anterior tratou a consulta como prova de modalidade; em uma coleta, isso marcou falsamente **994 de 1.006** anúncios como remotos.
- **Remediação:** removidos o monkeypatch que injetava `f_WT=2`, `is_remote` como sinal de classificação e `linkedin_remote_search_filter` da lista de evidências aceitas pelo adaptador. A busca complementar usa `remoto`, `remota`, `remote`, `home office` e `work from home` somente para descobrir candidatos. Cada vaga só recebe modalidade a partir do badge real capturado na página individual, de uma declaração explícita e não ambígua na descrição ou de override manual verificado. A deduplicação só enriquece o anúncio com essas evidências válidas.
- **Override verificado:** LinkedIn `4484868146`, Desenvolvedor da Mirante Tecnologia, é remoto. A descrição pública da vaga declara “Modalidade: Remota”; o override existe no coletor e como fallback do adaptador para snapshots sem proveniência.
- **Limitações e risco residual:** palavras-chave podem trazer falsos candidatos, omitir vagas que não usam esses termos e sofrer paginação/rate limit; elas nunca rotulam um anúncio. Quando não houver evidência individual acessível, modalidade fica desconhecida e a vaga continua elegível. Permanecem os limites de 1.000 resultados por consulta e 1.200 anúncios únicos por execução; logo, não há garantia de recuperar todas as remotas.
- **Publicação de saneamento já confirmada:** o commit `fbccbc22` atualizou o snapshot e o run `42213003518` o publicou às 11:50 UTC. Entre 1.779 anúncios LinkedIn, o catálogo mostra 1 remota (Mirante), 8 presenciais e 1.770 sem modalidade. Dos falsos rótulos, 970 registros foram conciliados com o snapshot anterior (8 presenciais e 962 desconhecidos); 24 sem correspondência ficaram desconhecidos. O código corretivo ainda aguarda assinatura e integração; até lá, uma coleta agendada em `main` pode reintroduzir os rótulos falsos.
- **Validação:** o snapshot saneado foi publicado e conferido no GitHub Pages. Os testes não foram alterados nem executados neste trabalho. A coleta com a nova regra e sua publicação ainda aguardam integração do código.
- **Rollback:** antes de qualquer publicação, basta descartar/reverter o branch isolado. Se futuramente integrado, reverter o commit de código e repetir coleta/publicação controladas; não restaurar `f_WT=2` como evidência.

# Histórico operacional e mapa de responsabilidades

## 2026-11-05 — Recuperação independente da coleta do LinkedIn

- **Causa raiz confirmada:** o timer `todas-as-vagas-github-scheduler.timer` da VPS estava ativo e executava a cada cinco minutos, mas `ops/github_scheduler.py` consultava exclusivamente `pages.yml`, cuja agenda é a do catálogo geral (`11, 14, 18 e 23 UTC`). O coletor separado `linkedin-jobs.yml`, agendado para `10 e 22 UTC`, não era observado nem recuperado. Por isso o log podia registrar `slot_succeeded` para o catálogo enquanto não existia uma execução do LinkedIn no slot esperado.
- **Evidência da ocorrência:** na verificação de 05/11, o último run do LinkedIn era `41951930204` (sucesso, 02:30 UTC); não havia execução correspondente à janela de 10 UTC. O catálogo geral continuava saudável e o `public-data` publicado às 15:20 UTC ainda continha 1.679 vagas LinkedIn, incluindo as 1.000 do snapshot mais recente; o problema era a ausência de uma recuperação específica para a próxima janela, não a remoção dos registros já publicados.
- **Correção implementada:** o recuperador agora monitora `pages.yml` e `linkedin-jobs.yml` separadamente. O LinkedIn usa os slots `10 e 22 UTC`, histórico de runs de 24 horas para tolerar atraso do GitHub, o endpoint correto de `workflow_dispatch` e o campo privado `linkedin_dispatched_slots`, sem compartilhar tentativas com o catálogo. Mantêm-se o backoff, a janela de visibilidade e o limite de tentativas; commits `[linkedin-refresh]` não são confundidos com uma nova coleta.
- **Validação:** adicionados testes para o calendário/filtragem do LinkedIn, isolamento do estado, leitura do workflow correto e dispatch do workflow correto. O `py_compile` do scheduler passou; os testes direcionados passaram no Windows. A suíte completa local foi bloqueada por limitações do Python nativo do Windows (`fcntl` ausente e erro de `os.replace` no diretório temporário); a validação final deve ocorrer no runner Linux antes da instalação na VPS.
- **Implantação e rollback:** após o merge, atualizar o checkout `/home/ubuntu/todas-as-vagas` na VPS e executar uma verificação somente leitura do serviço. Não disparar manualmente lotes extras se o scheduler já registrar a execução do slot. Para reverter, desfazer a alteração de `ops/github_scheduler.py`; o campo `linkedin_dispatched_slots` pode permanecer no estado privado sem afetar a versão anterior.

## 2026-11-04 — Inclusão do portal Heineken

- **Fonte pública:** `https://careers.theheinekencompany.com/Job-Listing`, com os filtros oficiais de Brasil (`field_location_country_code_1=BR` e `operatings_company=289`). A coleta usa somente HTML público, sem Selenium.
- **Paginação e integridade:** o adaptador segue o `rel=next`/`Show more` (`page=0%2C0%2CN`), com limite defensivo de 100 páginas, validação do host/caminho oficial, deduplicação por `click-id` e fallback para o slug da URL quando o identificador não está disponível. Catálogo vazio ou card incompleto interrompe a fonte para preservar o snapshot anterior.
- **Dados normalizados:** título, empresa, departamento, URL oficial, cidade, país/mercado `BR`, modalidade identificada por título/localidade e categorias `[departamento, "Heineken"]` sem duplicatas. A listagem não fornece `datePosted` confiável; `published_date` permanece vazio.
- **Validação e rollback:** os testes isolados da Heineken e do validador dinâmico foram aprovados; a validação live retornou **223 vagas únicas** (o portal informou 224 cards, com a deduplicação evitando uma publicação repetida). A fonte foi registrada no catálogo e no validador dinâmico; repetir com `python jobs-dashboard/validate_dynamic_portals.py --sources heineken`. Para reverter, remover o adaptador e seus registros de catálogo/validador ou reverter a alteração, sem apagar o snapshot anterior.

## 2026-11-04 — Inclusão do portal Skeelo

- **Fonte pública:** `https://skeelo.com/pt/carreiras/#vagas_abertas`, usando o endpoint JSON público `https://skeelo.com/api/ats/jobs?page=N`, sem autenticação.
- **Paginação e integridade:** o adaptador percorre todas as páginas informadas por `totalPages`, com limite defensivo de 50 páginas, validação de `items` e deduplicação por UUID. Payload inválido, URL fora de `ats.rippling.com/skeelo/jobs/<UUID>` ou catálogo vazio interrompem a fonte para que o snapshot anterior seja preservado pelo fluxo existente.
- **Dados normalizados:** título, departamento, URL ATS Rippling, cidade, estado, país/mercado, modalidade `remote`, `hybrid` ou `on-site` e categorias `[departamento, "Skeelo"]`. A modalidade remota brasileira sem cidade explícita usa `Brasil` como localidade agregada.
- **Data de publicação:** a API pública não expõe data de publicação confiável; `published_date` permanece vazio e nenhuma data é inferida.
- **Integração e validação:** a fonte foi registrada no catálogo e no validador dinâmico. Os testes cobrem paginação, normalização, deduplicação e seleção/registro da fonte; a validação ao vivo deve ser executada com `python jobs-dashboard/validate_dynamic_portals.py --sources skeelo`.
- **Rollback:** remover o registro de `skeelo` e o adaptador dedicado, ou reverter o commit desta inclusão. Nenhum dado anterior deve ser apagado quando a fonte falhar.

## 2026-11-04 — Cobertura e evidências públicas do LinkedIn

- **Correção do diagnóstico da Dexian:** a captura enviada pelo usuário confirma que a vaga 4479109326 é **Remota** e tem **Candidatura simplificada**. Esses dois dados agora têm overrides documentados para que a evidência fornecida não se perca quando a página pública anônima não expõe o mesmo CTA. O coletor que gerou o snapshot consultado já fazia busca aberta, sem easy_apply=True; portanto, candidatura externa não explica a ausência da vaga. Os IDs 4479867000, 4479109326 e 4484056862 não constavam no snapshot consultado; como não há respostas brutas antigas nem motivos de descarte por anúncio, a causa individual da ausência permanece inconclusiva.
- **Limite de coleta:** padrão de até **1.000 resultados gerais** e até **1.000 registros brutos na consulta remota complementar**. O teto rígido de **1.200 anúncios únicos** é aplicado somente depois da deduplicação entre consultas; duplicatas não reduzem o saldo para novas vagas. O limite individual do JobSpy 1.4.1 e o teto agregado também valem no modo `--terms` e em `workflow_dispatch`.
- **Tipo de candidatura por anúncio:** a mesma resposta HTML individual já usada para modalidade é inspecionada nos controles de candidatura. O snapshot registra applicationType (easy_apply, external ou unknown), applicationVerified e applicationEvidence. Easy Apply exige indicador explícito; candidatura externa exige marcador explícito ou CTA com endereço HTTP(S) comprovadamente fora de domínios do LinkedIn. CTA genérico, ausência de dado público ou sinais conflitantes resultam em unknown; nenhum desses casos exclui a vaga.
- **Modalidade preservada:** somente selo capturado na página individual, declaração textual explícita ou override manual documentado comprovam workplaceType; filtro remoto e campos genéricos do JobSpy permanecem sem valor probatório.
- **Observabilidade:** cada busca informa limites solicitados/efetivos, resultados retornados, páginas, deduplicação e avisos de teto. O log e GITHUB_STEP_SUMMARY mostram as contagens easy_apply, external e unknown.
- **Casos de regressão:** testes cobrem Easy Apply explícito, URL externa, CTA genérico, evidência conflitante, vagas unknown mantidas no snapshot, limite de 1.000 por consulta, teto único pós-deduplicação em buscas abertas/com termos e regras existentes de modalidade.
- **Impacto:** somente a busca e o snapshot auditável do LinkedIn mudam. A classificação de candidatura não é copiada para o catálogo público nem altera o layout do portal; vagas desconhecidas continuam elegíveis. Telegram e WhatsApp seguem consumindo o catálogo compartilhado.
- **Validação da coleta inicial:** o workflow 41821290704 concluiu com sucesso e publicou snapshot de 902 vagas. Foram 290 registros gerais e 910 brutos remotos, dos quais 288 eram duplicatas. A execução identificou que o código aplicava o saldo único antes da deduplicação e encerrava a busca remota em 910; o PR de correção passa a limitar o total após a deduplicação. Easy Apply: 1; externa: 0; desconhecida: 901, pois a resposta pública anônima não expôs CTA verificável para essas vagas. Os IDs 4479867000, 4479109326 e 4484056862 continuaram ausentes; sua causa individual permanece inconclusiva. A nova coleta após a correção e sua publicação ficam pendentes.
- **Reversão:** reverter o commit do PR e executar novamente o workflow LinkedIn. O snapshot anterior é preservado se a coleta falhar; a reversão do código restaura a regra e os limites anteriores.



## 2026-11-04 — Modalidade do LinkedIn somente com selo verificável

- **Causa raiz:** parâmetros de rastreamento e barra final impediam a captura do HTML; uma URL original válida podia autorizar o uso do HTML de um redirecionamento para outra vaga/domínio ou de uma resposta sem URL final; caminho frouxo aceitava rotas adicionais; elementos HTML vazios podiam iniciar ou estender a leitura além do selo. Na falta do selo, a coleta, os inferidores do pipeline e os rótulos persistidos ainda podiam preencher ou conservar modalidades por localização, título, busca remota ou dados antigos.
- **Correção:** só captura quando a URL final está presente e seu domínio e caminho completo correspondem à vaga; trata tags HTML vazias, inclusive autocontidas, sem permitir que iniciem/estendam o selo e aceita `workplaceVerified` apenas como booleano `true`. Modalidade desconhecida do LinkedIn não é inferida antes nem depois da gravação; em uma coleta LinkedIn bem-sucedida, rótulos antigos são limpos e o snapshot é reaplicado na mesma transação; falhas de gravação revertem a limpeza. Se a coleta falhar, os dados existentes são preservados.
- **Casos cobertos:** Nortal / (1608) Forward Deployed Engineer deve ser remoto; St Marche / Açougueiro(a) - Vila Mascote deve ser presencial. Vagas sem URL final, redirecionadas para outro domínio/ID, em caminhos que não correspondem exatamente à página da vaga, com selo marcado em elemento HTML vazio ou tag autocontida, com modalidade ausente ou `workplaceVerified: "false"` não herdam modalidade do título, localização ou busca.
- **Coleta incompleta:** falha em qualquer fase obrigatória cancela a execução antes de gravar o snapshot; assim, a falha não apaga rótulos verificados nem substitui os dados anteriores.
- **Exceções comprovadas:** Nortal (li-4486898930) remoto e St Marche (li-4478138443) presencial, conforme capturas do LinkedIn fornecidas em 03/11/2026. Os demais anúncios sem selo na resposta pública anônima permanecem sem modalidade.
- **Impacto:** a coleta LinkedIn e a publicação do catálogo continuam no fluxo existente. Vagas sem modalidade verificável permanecem no portal, mas sem rótulo de modalidade; filtros de modalidade não as tratam como remoto, híbrido ou presencial. Telegram e WhatsApp continuam consumindo o mesmo catálogo, sem mudança em seus publicadores.
- **Validação local:** 22 testes do LinkedIn e 36 testes do pipeline aprovados. CI do commit atualizado e nova coleta/publicação ainda pendentes.
- **Pós-implantação:** conferir `li-4486898930` como remoto e `li-4478138443` como presencial no snapshot do LinkedIn, no `public-data/data/vagas.json` e no GitHub Pages; confirmar que vagas não verificadas aparecem sem chip de modalidade.
- **Reversão:** reverter o commit desta correção e executar novamente a coleta/publicação. Isso restaura a classificação anterior por heurística e pode reintroduzir rótulos incorretos.


## 2026-11-03 — Modalidade do LinkedIn validada na página individual

- **Diagnóstico original, retificado em 2026-11-06:** o filtro remoto legado (`f_WT=2`) não é uma fonte confiável de candidatos remotos: a busca guest atual o ignora. O cartão de busca também não basta para classificar modalidade; o dado deve vir do selo real da página individual, de descrição explícita ou de override verificado.
- **Correção então implementada e ainda válida:** o coletor abre a página de detalhes durante a coleta, lê o selo Remote, Hybrid ou On-site/Presencial e marca a evidência por anúncio. A estratégia de descoberta atualmente vigente é a busca por palavras de modalidade documentada no registro de 2026-11-06; nem os termos nem o filtro legado comprovam modalidade.
- **Proteção:** buscas por palavras-chave servem apenas para descoberta; vagas sem selo ou descrição explícita permanecem sem modalidade, exceto overrides manuais verificados. A suíte mantém regressões para Nortal, St Marche e backfill.
- **Validação:** o snapshot continua sem publicar a descrição completa das vagas; somente o modelo de trabalho verificado é incorporado ao catálogo.

## 2026-11-03 — Catálogo integral sem restrição por termos

- **Regra consolidada:** o portal Todas as Vagas deve reunir as vagas públicas retornadas pelos adaptadores registrados, mantendo somente validações de publicação, localização, prazo e janela de até dois meses. Termos de cargo não são critério de inclusão.
- **Causa da regressão:** o índice amplo público da Gupy é limitado a aproximadamente 10.000 resultados; as buscas complementares por termos eram apenas uma expansão parcial e deixavam fora anúncios antigos ativos cujo título não correspondia aos termos.
- **Correção:** a consulta ampla continua sendo a fonte autoritativa e nunca é filtrada por termos; as consultas complementares permanecem aditivas. A página pública `https://carreirasomie.gupy.io/` foi incluída na reconciliação por portal, cobrindo a vaga Gupy `12711932` e evitando depender apenas de termos.
- **Outros portais:** a auditoria não encontrou filtro global de título no pipeline. Vagas.com remove `q=buscar` durante a paginação; filtros geográficos em SmartRecruiters/UnlockCareer e o modo padrão aberto do LinkedIn não são filtros de cargo.
- **Proteções:** teste de regressão para Omie e para um título fora da lista de buscas complementares; documentação no README e no mapa do ecossistema. A publicação só deve ser considerada concluída após validar o novo `public-data/data/vagas.json` e o GitHub Pages.
- **Limitação conhecida:** a Gupy ainda não oferece, por esse MCP público, uma exportação integral sem paginação/limite do provedor. Novas páginas públicas relevantes devem ser adicionadas ao manifesto monitorado até existir um enumerador oficial completo.
## 2026-10-31 — Resiliência, Backoff HTTP 429 e Benchmark da Coleta Aberta no LinkedIn

- **Benchmark Isolado na `main` (commit `a18798c`):**
  - **Início/Fim (UTC):** 2026-10-31 20:41:17 UTC a 20:41:56 UTC (duração total: 38.85s).
  - **Tráfego HTTP:** 9 requisições para a API pública de busca (`seeMoreJobPostings/search`).
  - **Rate Limits Observados:** 1 ocorrência de HTTP 429 na 4ª página (`start=30`) da Fase 1, causada pelo intervalo agressivo padrão do JobSpy (~0.4s).
  - **Volume e Integridade:** 80 registros brutos obtidos; 30 duplicatas descartadas; 50 vagas únicas consolidadas.
  - **Validação:** 50 de 50 vagas aprovadas pelo normalizador oficial `sources.linkedin._normalize` (100% de taxa de validação sem rejeições).
  - **Distribuição:** 28 vagas presenciais (`on-site`) e 22 vagas remotas (`remote`).
- **Atraso Adaptativo e Tratamento Resiliente de HTTP 429:**
  - `tools/collect_linkedin.py` configurado com `LinkedIn.delay = (2.5, 3.0)` para espaçamento seguro entre páginas.
  - Implementado interceptador de sessão em `jobspy.linkedin.create_session` que captura respostas HTTP 429 e aplica backoff exponencial (5s, 10s, 20s) ou o valor do cabeçalho `Retry-After`, com até 3 tentativas automáticas de recuperação.
  - Caso o rate limit persista após as tentativas, a rotina interrompe a paginação com aviso seguro preservando integralmente todas as vagas já coletadas, impedindo a perda de lotes parciais.
- **Integração de Agendas e Publicação:**
  - A rotina de coleta permanece isolada em `.github/workflows/linkedin-jobs.yml` com disparo automático diário às 10:00 UTC (`0 10 * * *`) e manual via `workflow_dispatch`.
  - A publicação oficial no catálogo e GitHub Pages é acionada automaticamente por `.github/workflows/pages.yml` ao detectar o commit `[linkedin-refresh]`, garantindo publicação única sem duplicação de cron/agendas.
- **Testes Automatizados:**
  - `jobs-dashboard/tests/test_linkedin.py` expandido com `test_jobspy_adaptive_delay_and_429_backoff_handling`, totalizando 11 testes unitários aprovados com sucesso.

## 2026-10-31 — Coleta aberta e não-restritiva no LinkedIn para o Todas as Vagas (histórico retificado em 2026-11-06)

- **Alinhamento e Estratégia Aberta:** Seguindo diretriz do usuário e alinhamento com `@codex` no agent-bus, o coletor deixou de depender de listas fixas de termos de busca. Como o "Todas as Vagas" é um portal amplo e generalista, consultas restritas a palavras-chave específicas de suporte/dev foram substituídas pela busca aberta nacional (`keywords=None`).
- **Estratégia histórica de coleta:**
  - **Fase 1 (Varredura Aberta Geral):** Consulta ampla em todo o Brasil com Easy Apply ativo e janela de 30 dias, trazendo vagas presenciais de múltiplas cidades, vagas híbridas e vagas com escopo nacional em diversas áreas de atuação (Direito, Design, Operações, Engenharia, Finanças, etc.).
  - **Fase 2 original, invalidada:** aplicava `f_WT=2` via patch no JobSpy e tratava os resultados como busca remota. A verificação de 2026-11-06 confirmou que o endpoint guest ignora esse filtro; ele não garante resultados remotos nem é evidência de modalidade.
  - Termos de busca (`--terms`) foram mantidos como filtro opcional via CLI apenas para testes direcionados ou execuções manuais.
- **Workflow e Parâmetros:** O workflow `.github/workflows/linkedin-jobs.yml` foi atualizado para utilizar o parâmetro `results_limit` (padrão 100 vagas na busca geral).
- **Teste histórico substituído:** `test_collect_linkedin_open_unrestricted_collection` originalmente assumia que a busca com `is_remote=True` retornava apenas remotas. A revisão de 2026-11-06 troca essa premissa por busca de candidatos via palavras e exige evidência individual para classificar.

## 2026-10-31 — Estratégia antiga de modalidade remota do LinkedIn (invalidada em 2026-11-06)

- **Diagnóstico e implementação originais, ambos retificados:** o pipeline interpretava localização nacional como sinal de modalidade e adicionava `f_WT=2` ao JobSpy. A busca guest atual ignora o filtro; a localização `Brazil`/`Brasil` também não prova que a vaga seja remota.
- **Status:** o patch de `LinkedIn._search_params`, a classificação baseada em `is_remote=True` e a inferência por localização foram removidos. A política vigente está na entrada de 2026-11-06: palavras de modalidade servem apenas para descobrir candidatos e nunca autorizam `workplaceType`.
- **Expansão de termos e limite seguro:** O limite seguro por termo foi ampliado para 25 no workflow e script. A lista de termos foi expandida para incluir papéis de suporte avançado, operações e atendimento ("Operations Assistant", "Assistente de Operações", "Suporte de Aplicação", "Help Desk").
- **Normalização então publicada, agora supersedida:** localizações `Brazil`/`Brasil` e a participação na etapa remota chegaram a ser usadas para marcar `remote`; essa regra era incorreta. Hoje esses registros ficam sem modalidade até haver evidência verificável por anúncio.
- **Testes de regressão:** A suíte em `jobs-dashboard/tests/test_linkedin.py` foi expandida com 9 testes, incluindo validação específica para localização "Brazil", aceitação de URLs de subdomínio local (`br.linkedin.com`), normalização de modelo de trabalho e teste de regressão direto para a vaga ID `4483475105` (Tryp.com, Operations Assistant).
- **Validação de snapshot:** O snapshot `docs/data/linkedin_vagas.json` foi atualizado e reprocessado: o adaptador `sources.linkedin.fetch()` validou 77 vagas aprovadas no filtro de 30 dias, incluindo 8 vagas remotas e a vaga ID `4483475105`.

## 2026-10-31 — LinkedIn incorporado ao catálogo principal

- A execução isolada [#41215702332](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/41215702332) concluiu com sucesso e coletou 79 vagas públicas com Candidatura Simplificada. A execução anterior usava a janela de 60 dias e publicava somente `docs/data/linkedin_vagas.json`; portanto, esse sucesso não significava alimentação do portal.
- O novo adaptador `jobs-dashboard/sources/linkedin.py` valida schema, origem, Easy Apply, link oficial `linkedin.com/jobs/view/<id>`, localidade brasileira, data máxima de 30 dias e frescor do snapshot. Vagas inválidas, antigas, fora do Brasil ou sem candidatura simplificada são descartadas; descrições não são copiadas.
- O workflow agora usa 720 horas (30 dias), recusa snapshots vazios e valida o arquivo antes de gravá-lo. O commit recebe `[linkedin-refresh]`, marcador reconhecido pelo `pages.yml` para executar a rotina principal completa: histórico, deduplicação, validações, `public-data` e GitHub Pages.
- O snapshot é mantido como entrada intermediária pública, mas a fonte efetiva do portal é o mesmo pipeline das demais origens. Se a coleta falhar, estiver vazia ou ficar desatualizada, ela não sobrescreve o último resultado válido e não bloqueia as outras fontes.
- A rotina continua sem serviço pago, sem login, cookies ou segredo do LinkedIn. A verificação automatizada do adaptador cobre janela, país, Easy Apply, normalização e expiração do snapshot.
- O PR [#170](https://github.com/edsonjunioor32/todas-as-vagas/pull/170) foi mesclado no commit `206ad05fd778b8279c3f5a1f3172e7e5d02768d3`. A verificação integrada [#41227356272](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/41227356272) terminou com sucesso: o LinkedIn entrou com **76 vagas** após a validação de 30 dias, o catálogo consolidou **82.262 vagas** e o ramo `public-data` avançou para `ca2c673`. Os gates de privacidade, preflight, histórico e GitHub Pages passaram.

## 2026-10-29 — Inclusão do portal Gateware

- O portal público da Gateware aponta para a página de carreiras `https://gateware.gupy.io/`.
- A fonte Gupy agora monitora essa página além da busca pública ampla, garantindo que as vagas da Gateware sejam coletadas mesmo quando não aparecem no limite da busca geral.
- A coleta continua sem login e sem chave privada; o contrato existente do coletor Gupy e a validação pública das vagas permanecem aplicáveis.


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
- `.github/workflows/linkedin-jobs.yml` — coleta diária pública do LinkedIn Easy Apply e validação do snapshot intermediário.
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
- `jobs-dashboard/inhire_descriptions.py` — adaptador da API pública de descrições do InHire, com resolução de tenant e classificação de 404/410.
- `jobs-dashboard/description_store.py` — persistência e estado da coleta privada.
- `jobs-dashboard/description_quality.py` — classificação determinística de qualidade, bloqueio, remoção e atualização.
- `jobs-dashboard/description_report.py` — relatório somente leitura por portal e categoria.
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
- `jobs-dashboard/sources/sonda.py` — vagas SONDA.
- `jobs-dashboard/sources/geekhunter.py` — GeekHunter e NTT Data.
- `jobs-dashboard/sources/github_boards.py` — fontes de vagas publicadas no GitHub.
- `jobs-dashboard/sources/gupy.py` — vagas Gupy.
- `jobs-dashboard/sources/infojobs.py` — funções de coleta InfoJobs (fuso Brasil).
- `jobs-dashboard/sources/inhire.py` — vagas InHire.
- `jobs-dashboard/sources/jobii.py` — vagas Jobii.
- `jobs-dashboard/sources/journy.py` — vagas Journy.
- `jobs-dashboard/sources/levva.py` — vagas Levva.
- `jobs-dashboard/sources/linkedin.py` — valida e adapta o snapshot público do LinkedIn para o pipeline principal.
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

## 2026-11-05 — Inclusão do quadro Positivo S+ na Pandapé

- O adaptador existente de quadros Pandapé em `jobs-dashboard/sources/requested_portals_03092026.py` foi generalizado para aceitar mais de uma URL, empresa e identificador de fonte.
- O quadro público `https://positivosmais.pandape.infojobs.com.br/` foi registrado como `positivosmais`, com empresa `Positivo S+`, links oficiais `/Detail/<id>`, localidade e modalidade preservadas. O texto em inglês `Presential` é normalizado para presencial (`on-site`).
- A fonte usa o mesmo navegador renderizado do coletor Pandapé/Minsait e fica isolada das falhas dos demais portais. Ela entra no registro regular e na mesclagem dinâmica, portanto uma falha desse quadro preserva o último estado válido sem bloquear os outros.
- A fonte foi incluída na lista de quadros ativos e no rótulo das mensagens do Telegram; não houve mudança no esquema público nem nos consumidores site, Telegram, WhatsApp ou agente.

### Testes do coletor

Todos os arquivos desta seção são testes automatizados; não são coletores nem devem ser agendados como fontes.

- `jobs-dashboard/tests/test_abler_precision.py` — precisão Abler e formato Telegram.
- `jobs-dashboard/tests/test_catalog_catchup.py` — decisões e falhas do recuperador.
- `jobs-dashboard/tests/test_description_crawler.py` — extração de descrições.
- `jobs-dashboard/tests/test_inhire_descriptions.py` — contrato da API pública do InHire e classificação de anúncio removido.
- `jobs-dashboard/tests/test_description_quality.py` — classificação de conteúdo, bloqueio, remoção e atualização.
- `jobs-dashboard/tests/test_description_report.py` — relatório somente leitura e separação de removidas.
- `jobs-dashboard/tests/test_private_descriptions.py` — persistência, backoff, crawler e integração das descrições privadas.
- `jobs-dashboard/tests/test_dynamic_portals.py` — contratos dos portais dinâmicos.
- `jobs-dashboard/tests/test_eightfold.py` — fonte Eightfold.
- `jobs-dashboard/tests/test_fit_requirements.py` — extração de requisitos.
- `jobs-dashboard/tests/test_gupy.py` — fonte Gupy.
- `jobs-dashboard/tests/test_homepage_cta_styles.py` — CTAs da página inicial.
- `jobs-dashboard/tests/test_linkedin.py` — contrato do snapshot LinkedIn, janela de 30 dias e rejeição de dados inválidos.
- `jobs-dashboard/tests/test_mercadolivre.py` — fonte Mercado Livre.
- `jobs-dashboard/tests/test_merge_dynamic_portals.py` — mesclagem dinâmica.
- `jobs-dashboard/tests/test_new_sources.py` — fontes recém-incorporadas.
- `jobs-dashboard/tests/test_ngcash.py` — fonte NG.CASH.
- `jobs-dashboard/tests/test_notify_telegram.py` — notificação Telegram.
- `jobs-dashboard/tests/test_ntconsult.py` — fonte NTConsult.
- `jobs-dashboard/tests/test_pipeline.py` — orquestração e persistência.
- `jobs-dashboard/tests/test_portal_source_resilience.py` — isolamento de falhas de fontes.
- `jobs-dashboard/tests/test_prepare_fit_assets.py` — valida o ponto público de entrada e os ativos locais do analisador.
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

## 2026-10-20 — Recuperação da atualização interrompida desde 18/10

- A execução de recuperação [#914](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/39432328558) terminou com sucesso em 46m04s. A coleta completa foi executada no runner `serverall-vagas`; não houve segunda coleta concorrente.
- O ramo `public-data` foi atualizado no commit `174db59ef3e131b072091652f33cbdd6af6aae9d`, às 14:25 UTC. O portal confirmou: `Atualizado em 20/10/2026, 11:24`, 63.342 vagas e 308 portais.
- A execução registrou falhas parciais em fontes; o portal exibiu 16 fontes sem resposta e aplicou a retenção operacional de até três dias. O snapshot passou a ser público após a validação estrutural e de volume.
- A rotina de preflight foi entregue pelos PRs [#157](https://github.com/edsonjunioor32/todas-as-vagas/pull/157) e [#158](https://github.com/edsonjunioor32/todas-as-vagas/pull/158), nos commits `d1d0f059` e `5fc21684`. Os checks de catálogo e analisador passaram antes dos merges.
- O recuperador externo da VPS continua com HTTP 401 por credencial inválida. Ele é redundante em relação à agenda do GitHub e não foi alterado nesta ocorrência para não substituir segredo sem uma credencial válida; a pendência fica registrada para renovação operacional separada.

## 2026-10-27 — Correção definitiva do bloqueio de atualização

- A coleta de 27/10 foi bloqueada antes do primeiro portal porque dois testes dependiam da data corrente: os fixtures de 25/08/2026 deixaram de caber na retenção de dois meses após a virada do dia. A mesma revisão havia passado na execução anterior.
- O PR [#163](https://github.com/edsonjunioor32/todas-as-vagas/pull/163) congelou a data nesses testes; os três checks do PR passaram e a correção foi mesclada no commit 2c53c05e4991969c92d435b19ce0b975b84d189a.
- Também foi criado o marcador explícito [catalog-refresh]: ele aciona coleta real no pages.yml, enquanto pushes comuns continuam apenas publicando a interface. Isso evita que uma recuperação seja confundida com simples republicação do snapshot anterior.
- A atualização acionada pela mesclagem concluiu a publicação da interface, mas a coleta real será executada pelo commit de recuperação com esse marcador, após o novo gate ser incorporado.

## 2026-10-27 — Monitor passa a reconhecer recuperações controladas

- O marcador `[catalog-refresh]` foi adicionado ao `pages.yml`, mas o monitor `catalog_catchup.py` ainda classificava apenas `[refresh-fit]` como coleta em eventos `push`.
- Essa divergência podia gerar uma recuperação duplicada depois de uma coleta marcada. O monitor agora reconhece os dois marcadores e possui testes que confirmam que uma recuperação bem-sucedida satisfaz o slot.
- A correção foi preparada no PR de prevenção correspondente e será validada antes da mesclagem.

## 2026-10-27 — Marcador de recuperação tornado explícito

- O monitor e o workflow passaram a aceitar somente `[catalog-refresh:run]` para uma coleta acionada por push.
- O texto genérico `[catalog-refresh]` não aciona mais coleta, evitando que mensagens de changelog ou commits de manutenção gerem uma execução extra.
- Foi adicionado teste negativo para garantir que texto não marcado não seja classificado como coleta.


## 2026-11-03 — Diagnóstico de portais indisponíveis e alerta após 24 horas

### Evidência da execução

A execução completa [41707136337](https://github.com/edsonjunioor32/todas-as-vagas/actions/runs/41707136337) concluiu a publicação do catálogo, mas registrou falha ou indisponibilidade nos portais abaixo. O catálogo não foi substituído por uma fotografia parcial: fontes saudáveis foram publicadas e os últimos dados válidos das fontes indisponíveis permaneceram protegidos pelas regras existentes.

| Portal | Evidência observada | Classificação / consequência |
|---|---|---|
| ASA | O adaptador Selenium do Elevo+ terminou com mensagem vazia ('Message:'); ele não encontrou uma listagem pública utilizável no diagnóstico registrado. | Falha de renderização/diagnóstico insuficiente; dados anteriores preservados. |
| Assefaz | Está em PAUSED_SOURCES; não foi chamado nesta execução. | Pausa operacional explícita; dados anteriores preservados. |
| Atitude | Está em PAUSED_SOURCES; não foi chamado nesta execução. | Pausa operacional explícita; dados anteriores preservados. |
| Azify | Está em PAUSED_SOURCES; não foi chamado nesta execução. | Pausa operacional explícita; dados anteriores preservados. |
| By Moma Group | Tenant Quickin: nenhum link público de vaga após a renderização JavaScript (137,0 s). | Falha do catálogo público/renderizado; dados anteriores preservados. |
| Cprocco | Está em PAUSED_SOURCES; não foi chamado nesta execução. | Pausa operacional explícita; dados anteriores preservados. |
| Entera | Convagas retornou zero registros públicos (2,2 s). | Feed vazio/endpoint público sem registros; não tratado como catálogo saudável. |
| Greenhouse | Três boards falharam, mas os boards 1910genetics, abarca e actpowerservices concluíram; 1.339 vagas Greenhouse foram mantidas. | Falha parcial isolada; resultado saudável preservado e parcial publicado. |
| Grupo EPA | Tenant Quickin aguardou 91,4 s por uma vaga de navegador renderizado. | Contenção/timeout da capacidade compartilhada de Chromium. |
| Harpia IT | Compleo teve 1 de 36 detalhes com HTTP 404; 23 vagas foram consolidadas. | Falha parcial de detalhe; listagem bem-sucedida mantida. |
| Inlog | Retornou zero vagas; o pipeline marcou a fonte como falha e preservou o snapshot anterior. | Feed vazio ou contrato público alterado; não apagar histórico. |
| Jobi-Hub | Tenant Quickin não expôs links públicos após JavaScript (123,5 s). | Falha do catálogo público/renderizado; dados anteriores preservados. |
| Koria | Tenant Quickin aguardou 90,9 s por slot de navegador renderizado. | Contenção/timeout da capacidade compartilhada de Chromium. |
| Metris DHO | Tenant Quickin não expôs links públicos após JavaScript (147,2 s). | Falha do catálogo público/renderizado; dados anteriores preservados. |
| Prolog App | Tenant Quickin aguardou 91,7 s por slot de navegador renderizado. | Contenção/timeout da capacidade compartilhada de Chromium. |
| R2 Ventures | Tenant Quickin não expôs links públicos após JavaScript (135,7 s). | Falha do catálogo público/renderizado; dados anteriores preservados. |
| VOE RH | Tenant Quickin não expôs links públicos após JavaScript (136,7 s). | Falha do catálogo público/renderizado; dados anteriores preservados. |
| Wellfound | O adaptador não encontrou vagas reconhecíveis (44,7 s). | Mudança/ausência do formato público reconhecido; dados anteriores preservados. |

### Causa comum e limites da conclusão

Os registros mostram quatro classes diferentes, e não uma falha única da VPS: (1) quatro fontes pausadas intencionalmente; (2) saturação/timeout do pool de Chromium; (3) páginas JavaScript que não entregaram links no DOM público esperado; e (4) feeds vazios ou respostas parciais. Portanto, aumentar retries indiscriminadamente não corrige todos os casos e pode piorar a contenção do navegador. Greenhouse e Harpia IT comprovam que o pipeline isola falhas de sub-board/detalhe sem descartar as vagas válidas.

### Alteração do alerta de saúde

Antes, docs/app.js mostrava a mensagem sempre que failed_sources não estava vazia. O campo fresh_days=3 não representava 72 horas de falha; ele pertencia à seleção de linhas recentes, e a exceção de fonte falha também protege o histórico até a janela normal de publicação.

A partir desta alteração:

- o banco histórico mantém source_health com last_success_at e failure_started_at;
- o pipeline completo e a mesclagem parcial atualizam esse estado sem alterar a retenção das vagas;
- o snapshot publica source_warning_after_hours=24 e os timestamps sanitizados por portal;
- a interface só apresenta “Alguns portais não responderam...” para a fonte cuja última atualização bem-sucedida (ou início da falha, quando não há sucesso anterior) esteja há pelo menos 24 horas;
- fontes pausadas também entram no mesmo relógio, sem serem reativadas automaticamente;
- a frase sobre preservação por até três dias continua relacionada à tolerância de dados recentes; ela não é mais usada para decidir quando o alerta aparece.

Essa separação evita alertas falsos imediatamente após uma falha transitória e evita esconder por vários dias uma fonte que permaneceu sem atualização. A mudança não altera a cadência da coleta, os limites do navegador, a janela de dois meses nem a política de preservação.

### Validação obrigatória

Foram adicionados testes para preservar o primeiro instante da falha, atualizar o sucesso e exportar os metadados de 24 horas. O teste de interface verifica que o alerta usa sourceWarningSources(data) e source_warning_after_hours, em vez de testar apenas a presença da lista de falhas.
## 2026-11-11 — Média geral do Glassdoor via HasData

- O catálogo passa a exibir somente a média geral da empresa, a quantidade de avaliações quando disponível e o link do perfil do Glassdoor; textos de avaliações não são coletados nem publicados.
- Foi adicionada uma rotina diária de enriquecimento com cache público, perfis canônicos aprovados e fallback opcional via HasData MCP. A chave fica exclusivamente no segredo do ambiente `github-pages`; o código não imprime nem persiste credenciais.
- O fallback permanece desligado por padrão e é limitado por execução. Quando indisponível, a coleta principal continua e publica o catálogo sem o enriquecimento.
- Validação do PR: testes direcionados do Glassdoor/HasData, compilação dos módulos alterados, verificação de sintaxe do JavaScript, leitura do YAML e `git diff --check`.

## 2026-11-11 — Runner hospedado para a atualização diária do Glassdoor

- O workflow `glassdoor-daily.yml` deixou de depender do runner ARM64 da VPS e passou a usar `ubuntu-latest`.
- O checkout foi reduzido para o commit disparador (`github.sha`) com `fetch-depth: 1`; o snapshot anterior continua sendo recuperado exclusivamente do ramo `public-data`.
- A mudança elimina a dependência do espaço, disponibilidade e estado do runner persistente para o enriquecimento diário. A chave HasData continua restrita ao segredo do ambiente `github-pages`.

## 2026-11-12 — Correção da média geral do Glassdoor para todo o catálogo

- Corrigida a renderização dos campos Glassdoor para que `null`/ausente não seja convertido implicitamente em `0,0/5` pelo JavaScript. A regra vale para todas as empresas e para as duas fontes de nota (perfil público e fallback HasData).
- Empresas sem perfil aprovado ou sem resposta válida continuam no catálogo, mas não exibem uma nota falsa; somente um valor numérico retornado e validado pelo provedor pode ser apresentado.
- Incluído teste de regressão e documentação do contrato. A nota da Heineken (esperada em torno de 4,0/5 conforme a fonte) só será exibida após o cache diário ser efetivamente gerado e publicado.

## 2026-11-12 — Endpoint atual do MCP Glassdoor da HasData

- Corrigido o endpoint padrão do cliente HasData de `/mcp?apis=glassdoor` para `/api/mcp?apis=glassdoor`, conforme a interface atual do MCP Glassdoor.
- A execução pontual confirmou que o endpoint legado respondia, mas o conteúdo não era interpretável pelo cliente. O cliente continua validando JSON-RPC, nome da empresa, nota e URL antes de publicar qualquer valor.
- Adicionado teste de regressão para impedir a volta do endpoint antigo; nenhuma chave foi registrada no repositório.

## 2026-11-12 — Alinhamento do cliente HasData ao contrato publicado

- A revisão do contrato público do Glassdoor MCP confirmou o endpoint `https://mcp.hasdata.com/mcp?apis=glassdoor` e o domínio regional `www.glassdoor.com.br`; ambos foram restaurados no cliente e nas quatro consultas aprovadas.
- O parser agora aceita `structuredContent`, campos JSON do item de conteúdo e JSON delimitado por texto/Markdown, mas rejeita texto livre. A validação posterior continua exigindo empresa aprovada, nota numérica e URL Glassdoor HTTPS.
- Testes direcionados, compilação Python e verificação de diff passaram antes da publicação da alteração.

## 2026-11-12 — Correção da allowlist do domínio regional HasData

- A execução pontual confirmou que a allowlist do coletor ainda rejeitava `www.glassdoor.com.br`, embora esse seja o domínio regional documentado pelo provedor. Por isso a chamada nem chegava ao HasData e a nota permanecia ausente.
- A validação agora aceita os domínios oficiais com e sem `www`, mantendo a restrição de host permitido. Foi incluído teste que valida o manifesto brasileiro e a execução preserva a regra de não publicar nota sem retorno numérico validado.

## 2026-11-12 — Correspondência do nome curto retornado pelo HasData

- A chamada remota passou a responder, mas o resultado não era associado à empresa porque o retorno usa `employer.shortName` em alguns anúncios. O coletor agora lê esse campo somente dentro dos aliases canônicos aprovados.
- O perfil da Heineken recebeu o alias explícito `Heineken`, sem alterar a validação exata nem permitir correspondência aproximada entre empresas.

## 2026-11-12 — Consulta dedicada para Heineken

- Como a busca por `Heineken Brasil` não retornou uma vaga associável, a consulta aprovada passou a usar `keyword=Heineken` e `location=Brazil`, mantendo o domínio brasileiro e os aliases canônicos.
- Em falhas de correspondência, o log passa a registrar somente contagem de vagas e até cinco nomes empresariais normalizados; nenhum texto de vaga, credencial ou conteúdo de mensagem é exposto.

## 2026-11-12 — Retentativa controlada de falhas HasData

- Resultados bem-sucedidos continuam protegidos por uma consulta diária; falhas podem ser reprocessadas em uma execução manual para não aguardar o próximo dia após instabilidade ou incompatibilidade do provedor.
- O teto padrão do workflow passou para três chamadas por execução, ainda dentro da franquia gratuita documentada e do limite local. O teste garante que sucessos são ignorados e somente a tentativa falha é refeita.

## 2026-11-12 — Limite de chamadas HasData no ambiente

- A variável não sensível `HASDATA_MCP_MAX_CALLS` do ambiente `github-pages` foi alterada de `1` para `3`, respeitando o teto local e permitindo que as quatro consultas canônicas avancem em execuções pontuais sem tocar na chave `HASDATA_API_KEY`.

## 2026-11-12 — Alias canônico Heineken N.V.

- A execução controlada mostrou que os anúncios brasileiros retornam o empregador como `Heineken N.V.`. Esse alias foi adicionado explicitamente ao perfil Heineken; não foi habilitada correspondência parcial ou aproximada.

## 2026-11-12 — Alias da origem do catálogo Heineken Brazil

- A publicação confirmou que as vagas do catálogo usam a empresa `HEINEKEN Brazil`, enquanto o retorno do Glassdoor/HasData usa `Heineken N.V.`. O alias da origem do catálogo foi adicionado ao perfil canônico para propagar a média geral ao campo público `gfr`.
- Foi incluído teste de regressão cobrindo o mapeamento `HEINEKEN Brazil` → média geral `4,2`.

