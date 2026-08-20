# Radar de Vagas — índice multiportal no GitHub Pages

Este projeto consulta fontes públicas de vagas, converte os formatos diferentes para uma base única e publica um painel pesquisável no GitHub Pages. A atualização ocorre quatro vezes por dia e continua mesmo quando um portal isolado fica temporariamente indisponível.

O painel publica somente vagas anunciadas nos **últimos dois meses**. Quando um portal não fornece uma data de publicação confiável, o sistema usa a primeira data em que encontrou o anúncio e o remove após dois meses.

## Portais incluídos

- Brasil: **InHire, Empregare, Gupy, Sólides, GeekHunter, Nerdin e InfoJobs**;
- globais: **The Muse, Remotive, Jobicy, Remote OK, Himalayas, Working Nomads, Arbeitnow e We Work Remotely**;
- páginas públicas de empresas: **Stone, iFood, PicPay, Banco Original, Braskem, GM Financial, Dell Technologies, ArcelorMittal, Grupo Mateus, AutoZone, NOV, Arcor Brasil, Greenhouse Brasil, Lever e Ashby**.

O painel permite combinar pesquisa livre com filtros de cidade, portal, modalidade, mercado, área, senioridade, data, vagas afirmativas para PcD e oportunidades encontradas em mais de um portal. O campo de cidade oferece sugestões a partir das localidades presentes na base e também aceita digitação livre. A exportação CSV respeita os filtros selecionados. O botão de tema no cabeçalho alterna entre os modos claro e escuro, salva a escolha no navegador e, na primeira visita, respeita a preferência do sistema.

## Sólides, GeekHunter e InfoJobs

A Sólides é consultada pelo catálogo público utilizado pelo próprio portal. Como a interface pública limita cada página a 10 registros e o catálogo possui dezenas de milhares de anúncios, cada atualização percorre até as **3.000 vagas mais recentes**. O limite pode ser alterado pela variável `SOLIDES_MAX_PAGES`; aumentar muito esse valor também aumenta o tempo e a carga da coleta. A deduplicação pode reduzir a quantidade efetivamente incorporada.

A GeekHunter é consultada pelas páginas públicas de vagas, que já entregam dados estruturados no HTML. O adaptador percorre todas as páginas disponíveis, normaliza modalidade, localização, senioridade, remuneração e tecnologias e não publica a descrição integral.

O InfoJobs é consultado pela busca pública geral, ordenada pelas mais recentes. A integração percorre a paginação pública até o limite configurado, preserva as modalidades indicadas em cada anúncio e deixa o filtro global de dois meses remover vagas antigas. Como o portal exige JavaScript e protege requisições HTTP simples com WAF, a atualização usa o Chrome já disponível no executor do GitHub Actions, sem login e sem acessar dados de candidatos. Os limites podem ser ajustados por `INFOJOBS_MAX_JOBS` e `INFOJOBS_MAX_PAGES`.

## Stone e iFood

As páginas de carreiras da **Stone** e do **iFood** utilizam o Greenhouse. O pipeline consulta a API pública dos dois quadros e mantém cada empresa como uma origem própria no filtro de portal. São importados cargo, localidade, modalidade, data original de publicação, área, tipo de contrato quando informado e o link oficial da candidatura. A descrição é usada somente em memória para classificação e não é publicada no painel.

## Greenhouse com vagas brasileiras

O Greenhouse não oferece um endpoint público que enumere todas as empresas. A API oficial exige conhecer previamente o identificador de cada página. Para ampliar a cobertura sem tornar as atualizações diárias pesadas, o projeto usa duas rotinas separadas:

- a coleta normal consulta somente o catálogo já validado de empresas que possuem vagas localizadas explicitamente no Brasil;
- aos domingos, uma descoberta independente verifica um catálogo amplo de identificadores públicos e atualiza a lista brasileira.

O catálogo inicial inclui RD Station, AB InBev, Capco, ClassPass, Coinbase, Delivery Associates, EBANX, Figma, GitLab, Miro, Newsela, Parse Biosciences, Pie Insurance, Pinterest, Ripple, Roofr, Smartly, SumUp, VTEX, Wildlife Studios e Wiz. Stone e iFood continuam como fontes próprias, evitando duplicidades.

Somente anúncios cuja localidade mencione Brasil, Brazil, uma cidade brasileira reconhecida ou uma UF válida entram no painel. Vagas descritas apenas como “Global”, “Worldwide” ou “LATAM” não são importadas. O corte geral de dois meses continua sendo aplicado depois dessa seleção.

A descoberta semanal faz parte do workflow `.github/workflows/pages.yml` e também é executada quando a atualização é iniciada manualmente em **Actions**. A lista resultante fica em `jobs-dashboard/data/greenhouse_br_companies.json`; as atualizações normais não refazem as milhares de consultas de descoberta.

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

O workflow é executado diariamente às **08h17**, **11h17**, **15h17** e **20h17**, no horário de Brasília/Fortaleza, além de permitir execução manual. A rotina:

1. usa os catálogos já validados da InHire e do Greenhouse, atualizando as descobertas pesadas semanalmente ou sob acionamento manual;
2. coleta portais independentes com concorrência limitada e isolamento de falhas;
3. normaliza área, senioridade, modalidade, localização, salário e indicadores PcD;
4. elimina duplicidades nativas e identifica anúncios equivalentes entre portais;
5. descarta anúncios publicados há mais de dois meses e atualiza o histórico SQLite;
6. gera um JSON compacto para o navegador;
7. valida links, contagens e privacidade;
8. publica o diretório `docs` no GitHub Pages.

Se um portal falhar, os demais continuam. Resultados vistos recentemente podem permanecer no painel por até três dias, evitando que uma indisponibilidade momentânea esvazie uma fonte inteira.

### Otimizações do pipeline

- até cinco fontes independentes são consultadas em paralelo, sem alterar a ordem determinística da consolidação;
- a Sólides mantém a cobertura das 3.000 vagas mais recentes e usa até oito requisições simultâneas;
- detalhes da InHire são reutilizados por até 24 horas por meio do cache do GitHub Actions; vagas novas ou com título, local ou modalidade alterados são consultadas imediatamente;
- o Nerdin participa da coleta geral e, por isso, usa a mesma transação SQLite e a mesma exportação JSON das demais fontes;
- uma atualização nova cancela outra ainda em andamento antes do commit, evitando a fila de execuções equivalentes;
- cada execução mostra no resumo do GitHub Actions o tempo por etapa, a duração de cada fonte, suas contagens e eventuais falhas.

## Privacidade e conteúdo

O site publica apenas metadados: cargo, empresa, portal, modalidade, localização, classificação, datas, salário quando disponível e link original. Descrições completas não são gravadas no JSON público nem no banco versionado.

O painel é um índice independente e não possui vínculo com os portais ou empresas. A pessoa candidata deve confirmar disponibilidade e requisitos no anúncio original.

## Teste local

Para atualizar tudo:

```powershell
node busca_vagas\build_public_inhire.js
node busca_vagas\validate_public_inhire.js
python jobs-dashboard\pipeline.py
python jobs-dashboard\validate_snapshot.py
python -m unittest discover -s jobs-dashboard\tests -v
```

Para abrir o painel:

```powershell
python -m http.server 8000 --directory docs
```

Depois acesse `http://localhost:8000`. O arquivo `index.html` não deve ser aberto diretamente por duplo clique, pois o navegador bloqueia a leitura local do JSON.

## Origem e créditos

A arquitetura multiportal foi adaptada do projeto público [Job-Market Explorer, de Rodrigo Carvalho](https://github.com/rodrigo-carfon/rodrigo-carfon.github.io/tree/master/jobs-dashboard), disponibilizado sob Unlicense. A integração InHire e a interface em português foram incorporadas ao mesmo fluxo; Empregare, Sólides, GeekHunter, Stone, iFood, Greenhouse Brasil e as páginas de empresas no Oracle Recruiting Cloud foram acrescentadas por suas interfaces públicas.
