# SmartRecruiters Brasil

A fonte smartrecruiters_brazil usa a página pública
https://jobs.smartrecruiters.com/?keyword=brazil somente como índice de
descoberta. Os identificadores de empresa são extraídos dos links públicos no
formato /{empresa}/{id}-{slug}.

Depois da descoberta, a coleta consulta o catálogo público da empresa:

GET https://api.smartrecruiters.com/v1/companies/{empresa}/postings?country=br&limit=100&offset=...

A paginação avança pelo número de registros recebidos e pelo campo totalFound.
Cada vaga é filtrada novamente para o Brasil, deduplicada por empresa e
identificador nativo e publicada com a URL canônica:

https://jobs.smartrecruiters.com/{empresa}/{id}-{slug}

## Resiliência e limites

- Timeout de 45 segundos e até três tentativas por requisição da API.
- Uma empresa com erro é registrada no log e não impede as demais.
- Por segurança, a execução considera no máximo 100 empresas descobertas e 500
  requisições de catálogo por ciclo.
- Os limites podem ser ajustados no ambiente com
  SMARTRECRUITERS_MAX_COMPANIES e SMARTRECRUITERS_MAX_REQUESTS, respeitando os
  tetos codificados.
- Se a página global não entregar links no HTML, há fallback para links visíveis
  renderizados. Se ambos falharem, a fonte falha sem apagar o snapshot anterior.
- DBC e Bosch continuam usando seus coletores existentes e não são redirecionados
  para esta fonte.
