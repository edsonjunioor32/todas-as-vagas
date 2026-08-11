# Radar de Vagas — índice multiportal no GitHub Pages

Este projeto consulta fontes públicas de vagas, converte os formatos diferentes para uma base única e publica um painel pesquisável no GitHub Pages. A atualização ocorre duas vezes por dia e continua mesmo quando um portal isolado fica temporariamente indisponível.

O painel publica somente vagas anunciadas nos **últimos três meses**. Quando um portal não fornece uma data de publicação confiável, o sistema usa a primeira data em que encontrou o anúncio e o remove após três meses.

## Portais incluídos

- Brasil: **InHire, Empregare, Gupy, Sólides e GeekHunter**;
- globais: **The Muse, Remotive, Jobicy, Remote OK, Himalayas, Working Nomads, Arbeitnow e We Work Remotely**;
- páginas públicas de empresas: **Greenhouse, Lever e Ashby**.

O painel permite combinar pesquisa livre com filtros de cidade, portal, modalidade, mercado, área, senioridade, data, vagas afirmativas para PcD e oportunidades encontradas em mais de um portal. O campo de cidade oferece sugestões a partir das localidades presentes na base e também aceita digitação livre. A exportação CSV respeita os filtros selecionados.

## Sólides e GeekHunter

A Sólides é consultada pelo catálogo público utilizado pelo próprio portal. Como a interface pública limita cada página a 10 registros e o catálogo possui dezenas de milhares de anúncios, cada atualização percorre até as **3.000 vagas mais recentes**. O limite pode ser alterado pela variável `SOLIDES_MAX_PAGES`; aumentar muito esse valor também aumenta o tempo e a carga da coleta. A deduplicação pode reduzir a quantidade efetivamente incorporada.

A GeekHunter é consultada pelas páginas públicas de vagas, que já entregam dados estruturados no HTML. O adaptador percorre todas as páginas disponíveis, normaliza modalidade, localização, senioridade, remuneração e tecnologias e não publica a descrição integral.

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

O workflow é executado diariamente às **08h17** e **20h17**, no horário de Brasília/Fortaleza, além de permitir execução manual. A rotina:

1. atualiza a descoberta de páginas públicas da InHire;
2. coleta cada portal de forma isolada;
3. normaliza área, senioridade, modalidade, localização, salário e indicadores PcD;
4. elimina duplicidades nativas e identifica anúncios equivalentes entre portais;
5. descarta anúncios publicados há mais de três meses e atualiza o histórico SQLite;
6. gera um JSON compacto para o navegador;
7. valida links, contagens e privacidade;
8. publica o diretório `docs` no GitHub Pages.

Se um portal falhar, os demais continuam. Resultados vistos recentemente podem permanecer no painel por até três dias, evitando que uma indisponibilidade momentânea esvazie uma fonte inteira.

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
```

Para abrir o painel:

```powershell
python -m http.server 8000 --directory docs
```

Depois acesse `http://localhost:8000`. O arquivo `index.html` não deve ser aberto diretamente por duplo clique, pois o navegador bloqueia a leitura local do JSON.

## Origem e créditos

A arquitetura multiportal foi adaptada do projeto público [Job-Market Explorer, de Rodrigo Carvalho](https://github.com/rodrigo-carfon/rodrigo-carfon.github.io/tree/master/jobs-dashboard), disponibilizado sob Unlicense. A integração InHire e a interface em português foram incorporadas ao mesmo fluxo; Empregare, Sólides e GeekHunter foram acrescentadas por suas interfaces públicas.
