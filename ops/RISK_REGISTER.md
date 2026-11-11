# Registro de riscos operacionais — Todas as Vagas

Revisão: 2026-11-11. Este registro complementa o mapa operacional. Ele não autoriza mudanças; cada mitigação deve ser validada contra código, testes, execução e impacto nos consumidores.

| ID | Risco | Impacto | Sinal de alerta | Mitigação atual | Próximo tratamento |
| --- | --- | --- | --- | --- | --- |
| R-001 | O enriquecimento privado falhar e ser tratado como falha do catálogo público | Telegram, WhatsApp e portal podem deixar de receber uma atualização válida | crawler privado encerra com erro ou aumenta backlog | Fluxos são separados; o snapshot público não depende do SQLite privado | Manter teste de isolamento e alertas separados |
| R-002 | Portal bloquear acesso com 403, robots, CAPTCHA ou 429 | Descrições ausentes ou desatualizadas | aumento de blocked/http_403/robots_denied/http_429 | Backoff, cache de robots, limite de requisições e registro de motivo | Estratégias específicas por portal; não tentar contornar controles |
| R-003 | Falha de atualização ser confundida com stale | Diagnóstico e priorização incorretos | status stale com http_status ou error preenchidos | Classificador usa status, HTTP e erro para preservar o bloqueio | Separar definitivamente qualidade e estado da última tentativa |
| R-004 | Texto curto ser contado como descrição completa | Busca por aderência recebe evidência insuficiente | qualidade short ou empty | Limiares explícitos e complete_candidate exige texto longo e múltiplas seções | Criar política de uso para currículo e aderência |
| R-005 | Relatório de diagnóstico alterar o banco | Corrupção, WAL inesperado ou alteração de estado | mtime/WAL mudam após relatório | description_report.py usa mode=ro e query_only; há teste de somente leitura | Monitorar execução diária e manter cópia de evidência |
| R-006 | Fila de descrições crescer sem limite | Consumo de disco e atraso de backfill | pending/backlog e espaço livre em queda | SQLite privado separado e métricas de bytes/caracteres | Fila priorizada, alerta de armazenamento e retenção controlada |
| R-007 | VPS ficar indisponível | OpenWA, fallback e armazenamento privado deixam de operar | SSH/Docker/systemd indisponíveis | Coleta pública roda em runner hospedado; bots têm fluxos independentes | Completar monitoramento externo dos canais e recuperação |
| R-008 | Dependência opcional ausente na VPS | Testes ou portal específico falham sem afetar outras fontes | UnlockCareer exige Selenium e o pacote não existe | Falha isolada no portal; não bloquear demais fontes | Documentar dependências por fonte e instalar somente quando necessário |
| R-009 | Mudança de schema ou métrica quebrar consumidores | Workflow ou runbook interpreta números errados | testes de compatibilidade falham | Fase 1 não altera schema; métricas antigas são preservadas | Migração explícita somente com testes de upgrade |
| R-010 | Fallback de navegador ser usado como caminho universal | Lentidão, saturação e maior risco operacional | aumento de timeout/Obscura e duração do crawler | Fallback limitado por status, bytes e timeout | Estratégias por família e orçamento por portal |

## Critério de prioridade

1. R-001 e R-007: disponibilidade dos canais e do catálogo.
2. R-002 e R-006: fontes bloqueadas e pressão de armazenamento.
3. R-003, R-004 e R-009: integridade da informação e compatibilidade.
4. R-005 e R-008: segurança operacional e dependências específicas.
