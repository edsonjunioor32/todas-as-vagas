# Contrato e limitações do Glassdoor

## Fonte de configuração

`jobs-dashboard/data/glassdoor_profiles.json` é o manifesto explícito de perfis aprovados. Cada entrada ativa precisa de `approved: true`, um `id`, uma lista manual de `company_names` e uma URL HTTPS pública do Glassdoor. O primeiro lote contém Skeelo, Heineken Brasil, Sicredi e Accenture. Novas entradas continuam exigindo conferência manual para evitar inferência de perfis, URLs ou notas.

O cache gerado em `jobs-dashboard/data/glassdoor_cache.json` é publicado junto do snapshot no ramo `public-data`. Ele retém `rating`, `review_count`, `checked_at` e o marcador interno da última tentativa do dia. O cache é filtrado novamente pelo manifesto a cada execução; perfis removidos ou remapeados não continuam associados às vagas.

Exemplo de entrada aprovada (substitua a URL pelo perfil público correto e valide o nome antes de habilitar):

```json
{
  "schema_version": 1,
  "profiles": [
    {
      "id": "empresa-exemplo",
      "approved": true,
      "enabled": true,
      "company_names": ["Empresa Exemplo", "Empresa Exemplo S.A."],
      "url": "https://www.glassdoor.com.br/Visao-geral/Trabalhar-na-Empresa-Exemplo-EI_IE123.htm"
    }
  ]
}
```

O manifesto não faz descoberta automática: isso evita associar uma empresa à página errada. Empresas que ainda não estiverem aprovadas continuam aparecendo normalmente, mas sem nota e sem link específico do Glassdoor.

## Fallback opcional HasData Glassdoor MCP

`jobs-dashboard/data/glassdoor_mcp_queries.json` é uma allowlist separada para o
fallback remoto HasData. Cada query precisa apontar para um `profile_id` já
aprovado no manifesto principal, declarar os nomes aceitos da empresa, cargo,
localidade e domínio. Queries desabilitadas ficam no arquivo como referência,
mas não geram chamadas.

O repositório da HasData fornece um launcher npm/PyPI que apenas encaminha a
sessão para o serviço remoto; ele não faz a coleta localmente. Para o workflow
Python, o projeto usa diretamente o endpoint remoto com a biblioteca padrão,
sem instalar o launcher nem expor a chave na linha de comando. A sessão usa
`https://mcp.hasdata.com/mcp?apis=glassdoor` e faz `initialize`,
`notifications/initialized`, `tools/list` e somente `tools/call` da busca de
vagas. A rotina diária não chama `getJobDetails`. O resultado é aceito tanto
como JSON quanto como SSE; `result.structuredContent`, campos JSON do item de
conteúdo ou texto contendo JSON são interpretados, enquanto texto livre continua
sendo rejeitado.

Para habilitar no GitHub Actions:

1. Cadastre `HASDATA_API_KEY` como secret do repositório ou do environment
   usado pelo workflow. Nunca coloque a chave em arquivo, log ou argumento de
   comando.
2. Defina a variável de repositório `HASDATA_MCP_ENABLED` como `true`.
3. Habilite somente as queries desejadas no manifesto MCP e mantenha
   `HASDATA_MCP_MAX_CALLS` em um limite compatível com o orçamento da conta.

O padrão é desabilitado (`false`), concorrência efetiva de uma chamada por vez,
timeout de 15 segundos, no máximo duas novas tentativas para HTTP 429/5xx e
até três chamadas por execução por padrão. O limite pode ser ajustado por
`HASDATA_MCP_TIMEOUT`, `HASDATA_MCP_RETRIES`, `HASDATA_MCP_BACKOFF` e
`HASDATA_MCP_MAX_CALLS`, respeitando o teto local de três chamadas. Esse teto
mantém o uso diário compatível com a franquia gratuita documentada pela
HasData mesmo em meses de 31 dias. Um resultado bem-sucedido continua sendo
consultado no máximo uma vez por dia; tentativas que falharam podem ser
reprocessadas em execução manual, sempre dentro do teto de três chamadas.

O MCP fornece somente a avaliação agregada associada a uma vaga do Glassdoor;
ele não fornece `review_count` nem substitui os perfis canônicos. O fallback
exige correspondência exata do nome normalizado da empresa e uma URL HTTPS
Glassdoor válida. A avaliação e a URL de referência são gravadas em campos
separados (`gfr`, `gfu`, `gft`); uma falha, resposta vazia, divergência de
empresa, falta de chave, timeout, 401, 429, 5xx ou JSON inválido preserva o
cache anterior e não interrompe a coleta principal.

## Snapshot compartilhado

As propriedades opcionais ficam em `jobs` e têm exatamente `count` posições quando presentes:

| Campo | Modelo do portal | Conteúdo |
|---|---|---|
| `gdr` | `glassdoor_rating` | número entre 0 e 5 ou `null` |
| `gdc` | `glassdoor_review_count` | quantidade inteira exata ou `null` |
| `gdu` | `glassdoor_url` | URL HTTPS canônica pública ou `null` |
| `gdt` | `glassdoor_checked_at` | data ISO da última verificação bem-sucedida ou `null` |

A associação é feita somente por nomes exatos normalizados e declarados no manifesto. Empresas sem perfil aprovado ficam sem avaliação. A interface mostra nota, quantidade e link somente quando o respectivo valor existe e nunca converte `null` em `0,0/5`; portanto, uma nota zero só pode aparecer quando o provedor realmente retornar o valor numérico zero.

## Limitações operacionais

- A rotina diária é independente da coleta principal e usa uma consulta sequencial por perfil, com no máximo uma tentativa lógica por perfil em cada data local.
- `robots.txt` é consultado antes da página; bloqueio, timeout, HTTP não permitido ou falha de parser não removem vagas nem apagam o último valor válido.
- Mesmo quando a leitura é bloqueada, o link canônico aprovado pode continuar sendo exibido; a nota só aparece depois de uma leitura estruturada bem-sucedida.
- Uma verificação visual pelo navegador automatizado também pode encontrar a proteção "Humans only"/Cloudflare; esse desafio não deve ser contornado automaticamente.
- A leitura aceita apenas metadados estruturados públicos, como JSON-LD e `itemprop`; texto visível ambíguo não é transformado em nota.
- Não há login, cookies, bypass de bloqueio, automação de navegador, endpoint privado ou API de terceiros.
- Uma verificação parcial atualiza somente o campo que trouxe valor; campos válidos anteriores não são apagados por ausência momentânea de marcação.
- O fallback HasData nunca grava a URL de uma vaga no campo do perfil canônico e nunca inventa quantidade de avaliações. A referência é validada e mantida separadamente.
