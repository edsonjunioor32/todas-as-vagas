# Description Quality and Portal Reliability Implementation Plan
> For implementers: execute this plan in the listed order. Each phase must leave the existing public catalog and scheduled publication path working. Private description enrichment is an auxiliary path and must never block the public snapshot.

**Goal:** Aumentar a cobertura e a confiabilidade das descrições privadas sem transformar uma falha de portal, navegador, robots.txt, limite de requisições ou falta de espaço em falha da atualização pública. O sistema deve mostrar, por portal, o que foi coletado, o que é utilizável, o que é curto, o que está bloqueado e o que está pendente, com evidência suficiente para orientar a próxima ação.

**Architecture:** Separar quatro responsabilidades: (1) coleta do catálogo público; (2) armazenamento privado das tentativas e descrições; (3) classificação de qualidade baseada em evidências, sem chamar uma descrição curta de completa; e (4) estratégias específicas por portal, com fila/retry e fallback de navegador controlados. A camada de relatório será somente leitura e não alterará o snapshot público. O publicador continuará independente do crawler privado.

**Tech Stack:** Python 3.12, SQLite, urllib e parser já existentes, Obscura como fallback opcional, testes Python existentes, GitHub Actions e systemd na VPS. Não será adicionada dependência paga nem um novo serviço externo nesta etapa.

## Baseline confirmado

A medição privada atual encontrou 87.321 registros. Os estados principais são: 68.862 fetched, 6.027 no_description, 3.824 HTTP 403, 3.579 HTTP 404, 2.568 robots_denied, 1.365 stale e 417 HTTP 429. Há 17.094 registros sem texto, 5.638 textos de 1–199 caracteres, 10.315 de 200–999, 13.344 de 1.000–1.999 e 40.930 com pelo menos 2.000 caracteres.

Essa distribuição não será tratada como um único problema. 403/robots/429 exigem estratégia de acesso e ritmo; 404/410 exigem validação de URL ou vaga encerrada; no_description exige melhoria de extração; stale exige agenda; e textos curtos exigem classificação honesta, não preenchimento artificial.

## Phase 1 delivery note

A primeira onda foi implementada na branch feat/description-quality-20261111. O relatório foi executado contra o SQLite privado em modo somente leitura e produziu uma classificação integral do banco atual. A Fase 1 não altera schema, não executa coleta, não publica mensagens e não remove registros. A suíte direcionada passou com 31 testes; a suíte completa da cópia da VPS revelou somente os dois problemas pré-existentes do UnlockCareer registrados no changelog.

## Phase Overview

| Phase | Name | Scope | Status |
|---|---|---|---|
| 1 | Contrato de qualidade e observabilidade | Classificação derivada, relatório por portal, métricas compatíveis e testes | Pending |
| 2 | Estratégias específicas por portal | Resolver URLs canônicas, APIs públicas, HTML, JSON-LD e fallback de navegador por família | Pending |
| 3 | Backfill resiliente e operação | Fila priorizada, limites, retomada, alertas de armazenamento e execução diária | Pending |
| 4 | Validação de produção | Reprocessamento controlado, comparação antes/depois e documentação operacional | Pending |

### Epic: Phase 1 — Contrato de qualidade e observabilidade

**Status:** Pending

**Objective:** Tornar o levantamento verificável e orientar decisões por portal sem modificar o catálogo público.

**Tasks:**

- [x] **1.1 Criar o classificador puro de qualidade**
  - **Context:** Hoje `fetched` não significa que a descrição esteja completa, e os totais misturam bloqueios, páginas curtas, páginas vazias e registros antigos.
  - **Implementation vision:** Criar `jobs-dashboard/description_quality.py` com classificação determinística e explicável:
    - `complete_candidate`: texto com pelo menos 1.000 caracteres e sinais de múltiplas seções, sem afirmar completude semântica;
    - `usable`: texto com pelo menos 200 caracteres;
    - `short`: texto entre 1 e 199 caracteres;
    - `empty`: texto vazio ou somente ruído;
    - `blocked`: estados HTTP, robots, rede ou limite que impedem leitura;
    - `stale`: registro que possui conteúdo, mas excedeu a janela de atualização;
    - `pending`: registro ainda não tentado ou sem próxima tentativa vencida.
    A precedência deve ser documentada para que um registro não seja contado simultaneamente como saudável e bloqueado.
  - **Files:** `jobs-dashboard/description_quality.py` (novo); `jobs-dashboard/tests/test_description_quality.py` (novo).
  - **Verification:** Testes unitários cobrindo limites 0/1/199/200/999/1.000, estados 403/404/410/429, robots, stale, conteúdo de JSON-LD e conteúdo curto.
  - **Done when:** Cada combinação relevante recebe uma única categoria e um motivo legível; nenhum teste depende de rede ou da VPS.

- [x] **1.2 Criar relatório somente leitura por portal**
  - **Context:** A consulta atual permite contar estados globais, mas não entrega um diagnóstico operacional repetível por fonte.
  - **Implementation vision:** Criar `jobs-dashboard/description_report.py`, reutilizando o esquema de `job_descriptions`, para produzir JSON e Markdown com total por portal, qualidade, status, `content_kind`, última verificação, última coleta, tamanho total e filas vencidas. O relatório deve incluir amostras de URLs por motivo, com limite configurável, e retornar código de saída não zero somente para erro do relatório, não para a existência de bloqueios.
  - **Files:** `jobs-dashboard/description_report.py` (novo); `jobs-dashboard/tests/test_description_report.py` (novo); `jobs-dashboard/description_store.py` (alteração mínima apenas se forem necessários helpers de consulta).
  - **Verification:** Executar contra SQLite temporário com dados sintéticos e contra uma cópia somente leitura do banco privado; conferir que o relatório reproduz os totais baseline e não altera o arquivo.
  - **Done when:** Uma execução gera um relatório por portal que diferencia conteúdo utilizável, texto curto, vazio, bloqueado, stale e pendente, sem exigir o crawler.

- [x] **1.3 Integrar métricas de qualidade ao crawler sem quebrar o contrato existente**
  - **Context:** O crawler já emite `DESCRIPTION_CRAWLER_METRICS`, e consumidores podem depender dos campos atuais.
  - **Implementation vision:** Manter todos os campos existentes e acrescentar contagens de qualidade, por fonte, status e motivo. A classificação deve ocorrer após a extração/fallback; falhas continuam registradas no store. Nenhum erro do relatório ou da classificação pode abortar o loop principal.
  - **Files:** `jobs-dashboard/description_crawler.py`; `jobs-dashboard/tests/test_description_crawler.py`; `jobs-dashboard/description_quality.py`.
  - **Verification:** Primeiro executar testes que falham para o novo contrato; depois implementar até passarem. Executar uma coleta limitada com timeout e confirmar que o snapshot público permanece inalterado quando o crawler privado falha.
  - **Done when:** Logs mostram as novas categorias, os campos antigos continuam presentes e uma falha individual continua isolada da execução geral.

- [x] **1.4 Documentar o contrato e os limites**
  - **Context:** Operadores precisam saber que “descrição completa” é uma classificação de qualidade, não uma garantia sobre o conteúdo original.
  - **Implementation vision:** Registrar critérios, exemplos, códigos de erro, limites de retry, relação com o portal público e procedimento para investigar uma fonte.
  - **Files:** `ops/ECOSYSTEM_MAP.md`; `ops/RISK_REGISTER.md` (novo); `ops/OPERATIONS_CHANGELOG.md`.
  - **Verification:** Revisão cruzada com o código, os testes e o esquema SQLite; confirmar que os riscos de 403, robots, 429, 404, stale e armazenamento aparecem com mitigação e impacto.
  - **Done when:** Um operador consegue interpretar o relatório e escolher a ação sem consultar o código-fonte.

**Acceptance criteria:**
- A atualização do catálogo público não depende da execução bem-sucedida do enriquecimento privado.
- 100% das linhas analisadas aparecem em exatamente uma categoria de qualidade.
- O relatório identifica o portal e o motivo, não apenas um total global.
- Os testes existentes passam e os novos testes cobrem o contrato de classificação.
- Nenhuma descrição é marcada como “completa” apenas por ter sido baixada.
- O relatório é executável sem rede, sem Obscura e sem credenciais.

### Epic: Phase 2 — Estratégias específicas por portal

**Status:** Pending

**Objective:** Reduzir vazios e falsos negativos atacando as causas por família de portal.

**Scope:**
- Sólides: resolver a URL canônica da vaga e distinguir `vagas.solides.com.br` de subdomínios RHGestor; seguir apenas links oficiais já associados ao registro.
- InHire: validar o endpoint público/HTML efetivamente usado e comparar o texto retornado no navegador com o texto persistido.
- Portais com 403/429/robots: aplicar ritmo, cache de robots, backoff e reprocessamento sem tentar burlar controles.
- Portais dinâmicos: usar Obscura somente quando HTML/API/JSON-LD não forem suficientes, com timeout, limite de tamanho e registro de evidência.
- Portais 404/410: confirmar encerramento ou URL quebrada antes de descartá-los.
- LinkedIn: manter separado da coleta principal e classificar a modalidade somente quando a evidência estiver presente.

**Files:** `jobs-dashboard/description_crawler.py`, novos módulos de estratégia em `jobs-dashboard/portal_strategies/`, testes por estratégia e documentação operacional existente.

**Verification:** Fixtures HTML/JSON por portal, testes de regressão, amostras manuais e comparação de taxa de `no_description` antes/depois.

**Done when:** Cada família prioritária tem uma estratégia testada, uma política de fallback e uma explicação do que continua impossível por bloqueio externo.

### Epic: Phase 3 — Backfill resiliente e operação

**Status:** Pending

**Objective:** Processar o estoque sem monopolizar recursos, retomando após interrupções e mantendo o disco sob controle.

**Scope:**
- Fila priorizada por portal, idade e estado; uma vaga defeituosa não interrompe o lote.
- Lease/retomada para evitar duas execuções concorrentes.
- Limites de tempo, bytes, requisições e concorrência conservadores.
- Retenção e compactação de logs/cache sem remover evidência necessária.
- Relatório diário com alertas quando a cobertura cair, a fila crescer, 403/429 aumentarem ou o disco atingir limiar.
- Execução do relatório e do crawler privado desacoplada de publicação e dos bots.

**Files:** `jobs-dashboard/description_crawler.py`, `jobs-dashboard/description_store.py`, unidades systemd em `ops/systemd/`, workflows de diagnóstico e runbooks.

**Verification:** Simulação de interrupção, execução concorrente, disco quase cheio, portal indisponível e recuperação de agenda.

**Done when:** Uma falha de portal ou da VPS deixa uma fila retomável e não impede a próxima atualização pública.

### Epic: Phase 4 — Validação de produção

**Status:** Pending

**Objective:** Confirmar ganhos reais antes de considerar a melhoria concluída.

**Scope:**
- Sincronizar a cópia da VPS com o commit validado.
- Executar relatório inicial e guardar baseline.
- Reprocessar primeiro fontes com maior retorno provável: Sólides/RHGestor, InHire, Empregare e portais dinâmicos.
- Comparar qualidade por portal, não somente quantidade total.
- Confirmar espaço livre, tempo de execução e ausência de regressão no catálogo, Telegram e WhatsApp.
- Atualizar mapa operacional, riscos e runbooks com resultados observados.

**Verification:** Dois ciclos completos de atualização e pelo menos sete dias de métricas diárias.

**Done when:** O relatório diário é estável, a cobertura melhora ou a limitação externa fica explicitamente comprovada, e nenhum fluxo público depende do crawler privado.

## Riscos, dependências e decisões

- **Bloqueios externos:** 403, robots, CAPTCHA e 429 não devem ser tratados como bugs internos nem contornados. A saída será registrar o motivo, respeitar limites e buscar fonte oficial alternativa.
- **Sólides/RHGestor:** uma URL do agregador pode não ser a origem da descrição; a resolução canônica precisa preservar identidade da vaga e evitar duplicidade.
- **Obscura/navegador:** navegador é fallback caro e frágil; não será usado como caminho universal.
- **Armazenamento:** o SQLite e os artefatos de recuperação precisam de medição antes de qualquer limpeza; manutenção não pode apagar evidência sem backup verificável.
- **Operação:** a cópia da VPS estava atrás do `main`; o deploy deve ocorrer somente após sincronização fast-forward e validação do commit.
- **Compatibilidade:** o publicador legado do WhatsApp permanece desativado para não gerar duplicidade.
- **Custo:** a proposta usa Python, SQLite, GitHub Actions, systemd, SSH e ferramentas já disponíveis; não introduz serviço pago.

## Self-review checklist

- [x] O objetivo separa qualidade de quantidade e preserva o catálogo público.
- [x] A Phase 1 contém tarefas detalhadas com contexto, arquivos, verificação e critério de conclusão.
- [x] As fases posteriores estão em nível de épico e cada uma termina com software testável.
- [x] O plano explicita riscos de portal, armazenamento, concorrência, dependências e impacto.
- [x] O plano exige RED → GREEN → REFACTOR para o novo contrato.
- [x] O plano não promete extrair páginas bloqueadas nem chama textos curtos de completos.
- [ ] A execução ainda precisa de escolha explícita do modo de lotes antes de alterar código.
