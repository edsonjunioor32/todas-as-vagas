> 🟢 **OPEN TO WORK:** Sou Analista de Suporte N2 Sênior / Sustentação de Sistemas com vasta experiência em Meios de Pagamentos e APIs. Estou em busca de recolocação. [Conecte-se comigo no LinkedIn](https://www.linkedin.com/in/edson-paiva-jr/)

# Todas as vagas — índice multiportal no GitHub Pages

Este projeto consulta fontes públicas de vagas, converte os formatos diferentes para uma base única e publica um painel pesquisável no GitHub Pages. A atualização ocorre quatro vezes por dia e continua mesmo quando um portal isolado fica temporariamente indisponível.

O painel publica somente vagas anunciadas nos **últimos dois meses**. Quando um portal não fornece uma data de publicação confiável, o sistema usa a primeira data em que encontrou o anúncio e o remove após dois meses.

## Contexto atual e integrações

O `todas-as-vagas` é o repositório central do catálogo: coleta vagas em fontes públicas, normaliza os formatos, elimina duplicidades, aplica as regras de qualidade e publica o painel no GitHub Pages.

O projeto não é apenas uma página estática. Ele mantém a fotografia pública do catálogo para que os canais de distribuição consultem a mesma base, sem duplicar a coleta nem expor credenciais.

### Site e dados publicados

- **Portal público:** [Todas as Vagas](https://edsonjunioor32.github.io/todas-as-vagas/).
- **Código e interface:** a branch `main` contém os adaptadores, o pipeline, os testes e o diretório `docs` publicado no GitHub Pages.
- **Snapshot para consumo:** a branch `public-data` mantém `data/vagas.json` e `data/fit.json`. O snapshot de vagas pode ser lido por integrações pelo endereço [raw do catálogo](https://raw.githubusercontent.com/edsonjunioor32/todas-as-vagas/public-data/data/vagas.json).
- **Histórico:** a branch `history-data` armazena o banco SQLite compactado usado para preservar o histórico entre atualizações.

### Integração com Telegram

O canal do Telegram é uma saída de notificações do catálogo. O workflow [`telegram.yml`](.github/workflows/telegram.yml) deste repositório fica disponível para execução manual, testes pontuais, reenvios e operação controlada. Ele compara o snapshot atual com um snapshot anterior e mantém o estado das notificações para evitar reenvios desnecessários.

A distribuição automática regular do canal é mantida no repositório dedicado do Telegram. Quando este workflow é executado, ele usa somente os secrets `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`; os valores nunca devem ser gravados no código ou no README.

### Integração com WhatsApp

O bot do WhatsApp fica no repositório separado [`botwhats`](https://github.com/edsonjunioor32/botwhats). Ele consulta o snapshot público da branch `public-data` e usa o OpenWA como gateway para receber e enviar mensagens.

Na arquitetura atual:

1. este repositório coleta e publica `data/vagas.json`;
2. o `botwhats` baixa esse snapshot e mantém uma cópia local em seu volume Docker;
3. o OpenWA, executado na VPS Oracle, entrega as mensagens ao WhatsApp;
4. o bot responde às consultas e encaminha a pessoa candidata ao portal oficial.

O bot e o OpenWA não dependem de uma aba do navegador para o catálogo ser atualizado. A comunicação interna entre os containers usa a rede Docker `openwa_net`, com o OpenWA acessível ao bot por `http://openwa:2785`. As chaves do OpenWA, do webhook e demais credenciais pertencem ao ambiente do `botwhats`/VPS e não devem ser adicionadas a este repositório.

### Fluxo completo

```text
Fontes públicas
      ↓
Coleta, normalização, deduplicação e validação
      ↓
Snapshot público (public-data/data/vagas.json)
      ├── GitHub Pages: portal pesquisável
      ├── Telegram: notificações de novas vagas
      └── WhatsApp: consulta interativa pelo botwhats/OpenWA
```

Assim, o catálogo permanece em um único ponto de verdade: uma atualização bem-sucedida alimenta o site e deixa os dados disponíveis para os dois canais, enquanto cada canal mantém sua própria camada de entrega e suas próprias credenciais.

## Portais incluídos

- Brasil: **InHire, Empregare, Gupy, Sólides, Recrut.AI, Taggui RH, GeekHunter, Nerdin e InfoJobs**;
- globais: **The Muse, Remotive, Jobicy, Remote OK, Himalayas, Working Nomads, Arbeitnow e We Work Remotely**;
- páginas públicas de empresas: **Stone, iFood, PicPay, Banco Original, Braskem, GM Financial, Dell Technologies, ArcelorMittal, Grupo Mateus, AutoZone, NOV, Arcor Brasil, Greenhouse Brasil, Lever e Ashby**.

O painel permite combinar pesquisa livre com filtros de cidade, portal, modalidade, mercado, área, senioridade, data, vagas afirmativas para PcD e oportunidades encontradas em mais de um portal. O campo de cidade oferece sugestões a partir das localidades presentes na base e também aceita digitação livre. A exportação CSV respeita os filtros selecionados. O botão de tema no cabeçalho alterna entre os modos claro e escuro, salva a escolha no navegador e, na primeira visita, respeita a preferência do sistema.

## Sólides, Recrut.AI, Taggui RH, GeekHunter e InfoJobs

A Sólides é consultada pelo catálogo público utilizado pelo próprio portal. A interface pública é percorrida em páginas de **20 registros** e cada atualização cobre até as **12.000 vagas mais recentes** (`SOLIDES_MAX_PAGES=600`). Aumentar muito esse valor também aumenta o tempo, a carga da coleta e a possibilidade de limitação temporária pelo portal. A deduplicação pode reduzir a quantidade efetivamente incorporada.

A Recrut.AI é consultada pelas páginas públicas de empresas hospedadas na plataforma: Petlove, Economart, Grupo Savegnago (incluindo a sublistagem do Paulistão Atacadista), Grupo Luck, Grupo Koch, Atakarejo, Grupo Bravante, Supermercados Vianense, Recibom, Atacadão Dia a Dia, Grupo Vanguarda, Laticínios Tirol e Novo Mateus. As rotas individuais `/job/XXXXXX` são apenas detalhes das vagas e não são registradas como portais separados. O coletor usa o código nativo da vaga, remove parâmetros de rastreamento e consolida a sublistagem do Paulistão com o tenant Savegnago.

A página geral da Taggui RH é coletada separadamente. Links incompletos terminados apenas em `/job/` e detalhes que já não estão disponíveis são ignorados; se uma fonte não expuser vagas válidas, a falha fica isolada das demais.

A GeekHunter é consultada pelas páginas públicas de vagas, que já entregam dados estruturados no HTML. O adaptador percorre todas as páginas disponíveis, normaliza modalidade, localização, senioridade, remuneração e tecnologias e não publica a descrição integral.

O InfoJobs é consultado pela busca pública geral, ordenada pelas mais recentes. A integração percorre a paginação pública até o limite configurado, preserva as modalidades indicadas em cada anúncio e deixa o filtro global de dois meses remover vagas antigas. Como o portal exige JavaScript e protege requisições HTTP simples com WAF, a atualização usa o Chrome já disponível no executor do GitHub Actions, sem login e sem acessar dados de candidatos. Os limites podem ser ajustados por `INFOJOBS_MAX_JOBS` e `INFOJOBS_MAX_SCROLLS`.

## Stone e iFood

As páginas de carreiras da **Stone** e do **iFood** utilizam o Greenhouse. O pipeline consulta a API pública dos dois quadros e mantém cada empresa como uma origem própria no filtro de portal. São importados cargo, localidade, modalidade, data original de publicação, área, tipo de contrato quando informado e o link oficial da candidatura. A descrição é usada somente em memória para classificação e não é publicada no painel.

## Greenhouse com vagas brasileiras

O Greenhouse não oferece um endpoint público que enumere todas as empresas. A API oficial exige conhecer previamente o identificador de cada página. Para ampliar a cobertura sem tornar as atualizações diárias pesadas, o projeto usa duas rotinas separadas:

- a coleta normal consulta somente o catálogo já validado de empresas que possuem vagas localizadas explicitamente no Brasil;
- aos domingos, uma descoberta independente verifica um catálogo amplo de identificadores públicos e atualiza a lista brasileira.

O catálogo inicial inclui RD Station, AB InBev, Capco, ClassPass, Coinbase, Delivery Associates, EBANX, Figma, GitLab, Miro, Newsela, Parse Biosciences, Pie Insurance, Pinterest, Ripple, Roofr, Smartly, SumUp, VTEX, Wildlife Studios e Wiz. Stone e iFood continuam como fontes próprias, evitando duplicidades.

Somente anúncios cuja localidade mencione Brasil, Brazil, uma cidade brasileira reconhecida ou uma UF válida entram no painel. Vagas descritas apenas como “Global”, “Worldwide” ou “LATAM” não são importadas. O corte geral de dois meses continua sendo aplicado depois dessa seleção.

A descoberta semanal faz parte do workflow `.github/workflows/pages.yml` e também pode ser executada em uma operação manual pelo **Actions**. A lista resultante fica em `jobs-dashboard/data/greenhouse_br_companies.json`; recuperações automáticas de uma coleta não repetem essa descoberta ampla.

## Empresas no Oracle Recruiting Cloud

O painel consulta páginas públicas no Oracle Recruiting Cloud de **PicPay, Banco Original, Braskem, GM Financial, Dell Technologies, ArcelorMittal, Grupo Mateus, AutoZone, NOV e Arcor Brasil**. Cada empresa permanece como uma origem própria no filtro de portal. O adaptador importa cargo, localidade, modalidade quando informada, data de publicação, categorias estruturadas e o link oficial da candidatura. Como a AutoZone utiliza uma página global, somente anúncios cujo país é confirmado como Brasil são publicados no painel.

A consulta usa páginas de até 200 registros ordenadas da publicação mais recente para a mais antiga. Até quatro páginas são consultadas em paralelo e, ao alcançar uma vaga anterior ao corte de dois meses, a paginação daquela empresa é encerrada imediatamente. Isso reduz o tempo da atualização sem retirar vagas que ainda estejam dentro do período solicitado. O paralelismo pode ser ajustado por `ORACLE_WORKERS` entre 1 e 6. Descrições e outros textos integrais não são gravados na fotografia pública.

## Empregare: API e MCP

A atualização completa usa a API pública oficial:

```text
GET https://www.empregare.com/api/pt-br/vagas/buscar-novo
```

Ela permite percorrer o catálogo ativo com páginas de 100 registros. O adaptador está em `jobs-dashboard/sources/empregare.py`.

O endpoint MCP também está incluído para consultas interativas:

```text
https://www.empregare.com/api/mcp
```

O servidor usa Streamable HTTP, não exige login e disponibiliza a ferramenta `buscar_vagas`. Para testá-la:

```powershell
python jobs-dashboard\empregare_mcp.py --query "suporte" --localidade "João Pessoa" --itens 20
python jobs-dashboard\empregare_mcp.py --list-tools
```

O MCP aceita no máximo 50 resultados por página. Por isso ele é usado para consultas pontuais, enquanto a API REST alimenta a varredura automática completa.

## Publicar no repositório atual

1. Extraia o ZIP no computador.
2. Envie os itens internos para a raiz do repositório `todas-as-vagas`, substituindo a versão anterior.
3. Preserve as pastas `.github`, `busca_vagas`, `jobs-dashboard` e `docs`.
4. No GitHub, abra **Settings → Pages**.
5. Em **Build and deployment → Source**, selecione **GitHub Actions**.
6. Abra **Actions**, selecione **Atualizar vagas multiportal e publicar GitHub Pages** e clique em **Run workflow**.

Mantendo o nome atual do repositório, o endereço esperado continua sendo:

```text
https://edsonjunioor32.github.io/todas-as-vagas/
```

### Se a pasta `.github` não puder ser enviada

Envie primeiro os arquivos visíveis. Depois use **Add file → Create new file** e informe este caminho:

```text
.github/workflows/pages.yml
```

Copie para ele todo o conteúdo do arquivo visível `WORKFLOW_PARA_COPIAR.yml` e confirme a alteração na branch `main`.

## Atualização automática

O workflow é executado diariamente às **08h07**, **11h07**, **15h07** e **20h07**, no horário de Brasília/Fortaleza, além de permitir execução manual. A rotina:

1. usa os catálogos já validados da InHire e do Greenhouse, atualizando as descobertas pesadas semanalmente ou sob acionamento manual;
2. coleta portais independentes com concorrência limitada e isolamento de falhas;
3. normaliza área, senioridade, modalidade, localização, salário e indicadores PcD;
4. elimina duplicidades nativas e identifica anúncios equivalentes entre portais;
5. descarta anúncios publicados há mais de dois meses e atualiza o histórico SQLite;
6. gera um JSON compacto para o navegador e o índice público de aderência;
7. valida links, contagens e privacidade;
8. publica o diretório `docs` no GitHub Pages.

Se um portal falhar, os demais continuam. Resultados vistos recentemente podem permanecer no painel por até três dias, evitando que uma indisponibilidade momentânea esvazie uma fonte inteira.

O monitor `.github/workflows/catalog-catchup.yml` roda em GitHub-hosted Ubuntu cerca de 38 minutos depois de cada horário principal e também verifica a conclusão da coleta. Se não houver execução ativa ou sucesso no horário, ele solicita uma única recuperação automática para aquele horário, reaproveitando checkpoints. Essa recuperação aparece como `repository_dispatch` com o nome **Recuperação automática do catálogo**; se ela também falhar, o monitor abre ou atualiza um alerta em vez de iniciar um ciclo de novas execuções. A tentativa seguinte fica para o próximo horário normal.

As publicações do catálogo principal, dos portais dinâmicos, do Journy e do estado do Telegram compartilham o grupo `catalog-publication`: somente um escritor publica por vez e uma nova execução não cancela a que já está em andamento. Recuperações automáticas não repetem a descoberta semanal de empresas Greenhouse nem a descoberta de novas empresas InHire.

O workflow `.github/workflows/telegram.yml` deste repositório é acionado manualmente (`workflow_dispatch`) para testes, reenvios e operação controlada. Ele compara snapshots e registra o estado das notificações. O envio automático regular do canal é mantido no repositório dedicado do Telegram. O bot do WhatsApp consulta o snapshot público da branch `public-data` por meio do repositório `botwhats`.

### Otimizações do pipeline

- até cinco fontes independentes são consultadas em paralelo, sem alterar a ordem determinística da consolidação;
- a Sólides mantém a cobertura de até 12.000 vagas mais recentes (600 páginas de 20 registros) e usa até oito requisições simultâneas;
- detalhes da InHire são reutilizados por até 24 horas por meio do cache do GitHub Actions; vagas novas ou com título, local ou modalidade alterados são consultadas imediatamente;
- o Nerdin participa da coleta geral e, por isso, usa a mesma transação SQLite e a mesma exportação JSON das demais fontes;
- todos os publicadores compartilham uma trava de concorrência: uma execução ativa por vez, sem cancelar uma coleta em andamento;
- a política de reinício do runner self-hosted na VPS é mantida em `ops/systemd/actions-runner-restart.conf` e reinicia o serviço após falha inesperada;
- cada execução mostra no resumo do GitHub Actions o tempo por etapa, a duração de cada fonte, suas contagens e eventuais falhas.

## Índice privado de descrições (VPS)

O catálogo público continua sem descrições integrais. Para viabilizar a futura busca por aderência, o projeto agora inclui um coletor opcional que lê o snapshot público, acessa os links oficiais das vagas em baixa velocidade e guarda as descrições somente em um SQLite privado no VPS.

- O arquivo fica fora do checkout por padrão, em `~/todas-as-vagas-private/descriptions.sqlite3`, e possui índice FTS5 quando disponível.
- Cada vaga é processada com checkpoint, hash, data da última tentativa, status, código HTTP e próxima tentativa. Uma falha não interrompe a fila nem apaga uma descrição já armazenada.
- O coletor respeita `robots.txt`, processa uma requisição por vez com intervalo mínimo configurado de 1 segundo e grava checkpoints. Falhas ou páginas sem descrição não interrompem a fila.
- A carga inicial na VPS é contínua, sem limite artificial de itens ou duração, e segue até esgotar as vagas elegíveis pendentes. O timer horário em UTC retoma itens cujo prazo de nova tentativa venceu e recupera a coleta após reinicializações ou interrupções; o lock impede duas coletas simultâneas. O tempo real depende da latência e dos controles de acesso dos portais.
- O conteúdo bruto não é enviado para GitHub Pages, `public-data`, `history-data`, logs, Telegram ou WhatsApp.

Instalação no VPS (após atualizar o checkout):

```bash
sudo install -d -o ubuntu -g ubuntu -m 700 /home/ubuntu/todas-as-vagas-private
sudo install -m 644 ops/systemd/todas-as-vagas-descriptions.service /etc/systemd/system/
sudo install -m 644 ops/systemd/todas-as-vagas-descriptions.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now todas-as-vagas-descriptions.timer
systemctl status todas-as-vagas-descriptions.timer --no-pager
```

Para uma execução controlada antes de ativar a madrugada:

```bash
cd /home/ubuntu/todas-as-vagas
python3 jobs-dashboard/description_crawler.py --limit 10 --max-seconds 120 --min-interval 1
```

O resultado dessa primeira etapa é uma base privada pronta para a próxima etapa: comparar o currículo com requisitos extraídos das descrições e ranquear as vagas. Nenhuma tela pública é alterada nesta fase.

## Privacidade e conteúdo

O site publica apenas metadados: cargo, empresa, portal, modalidade, localização, classificação, datas, salário quando disponível e link original. Descrições completas não são gravadas no JSON público nem no banco versionado.

O painel é um índice independente e não possui vínculo com os portais ou empresas. A pessoa candidata deve confirmar disponibilidade e requisitos no anúncio original.

## Teste local

Para atualizar tudo:

```powershell
node busca_vagas\build_public_inhire.js
node busca_vagas\validate_public_inhire.js
python jobs-dashboard\pipeline_fit.py --max-age-months 2
python jobs-dashboard\validate_snapshot.py
python jobs-dashboard\validate_fit.py
python -m unittest discover -s jobs-dashboard\tests -v
npm run test:fit
```

Para abrir o painel:

```powershell
python -m http.server 8000 --directory docs
```

Depois acesse `http://localhost:8000`. O arquivo `index.html` não deve ser aberto diretamente por duplo clique, pois o navegador bloqueia a leitura local do JSON.
