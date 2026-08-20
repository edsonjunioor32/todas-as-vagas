/**
 * Gera a base pública usada pelo GitHub Pages.
 *
 * A saída contém somente metadados essenciais da vaga. A descrição completa é
 * lida apenas em memória para identificar contradições e idioma; ela nunca é
 * gravada em docs/data.
 */
const fs = require('fs');
const path = require('path');

const DIR = __dirname;
const ROOT = path.resolve(DIR, '..');
const OUTPUT_DIR = process.env.INHIRE_OUTPUT_DIR
  ? path.resolve(process.env.INHIRE_OUTPUT_DIR)
  : path.join(ROOT, 'jobs-dashboard', 'data', 'inhire');
const API = 'https://api.inhire.app/job-posts/public/pages';
const HEADERS = {
  'X-Inhire-Client': 'web-inhire',
  'Content-Type': 'application/json',
  'User-Agent': 'radar-vagas/3.0 (indice publico multiportal)'
};
const INFRA = new Set([
  'www', 'api', 'auth', 'app', 'status', 'mcp', 'mcp-dev', 'inhub', 'login',
  'admin', 'inhire-admin', 'saml-setup', 'sso-setup', 'preview', 'senior',
  'files', 'portal', 'board', 'people', 'new', 'novo', 'conteudo', 'docs',
  'email', 'lp', 'hub', 'webinar', 'analytics', 'analytics-ss'
]);
const DEMO_TENANTS = new Set(['demo']);
const DETAIL_TTL_HOURS = Math.min(
  168,
  Math.max(1, Number(process.env.INHIRE_DETAIL_TTL_HOURS) || 24)
);
const DETAIL_WORKERS = Math.min(
  32,
  Math.max(1, Number(process.env.INHIRE_DETAIL_WORKERS) || 24)
);

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(path.join(DIR, file), 'utf8').replace(/^\uFEFF/, ''));
  } catch {
    return fallback;
  }
}

function writeJsonAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = `${file}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  fs.renameSync(temporary, file);
}

function normalize(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

function cleanText(value, maxLength = 500) {
  return String(value || '')
    .replace(/[\u0000-\u001F\u007F]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLength);
}

function decodeHtml(value) {
  const entities = {
    amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
    aacute: 'á', agrave: 'à', acirc: 'â', atilde: 'ã', auml: 'ä',
    eacute: 'é', ecirc: 'ê', euml: 'ë', iacute: 'í', oacute: 'ó',
    ocirc: 'ô', otilde: 'õ', uacute: 'ú', ccedil: 'ç',
    Aacute: 'Á', Agrave: 'À', Acirc: 'Â', Atilde: 'Ã',
    Eacute: 'É', Ecirc: 'Ê', Iacute: 'Í', Oacute: 'Ó',
    Ocirc: 'Ô', Otilde: 'Õ', Uacute: 'Ú', Ccedil: 'Ç'
  };
  return String(value || '')
    .replace(/<\s*br\s*\/?\s*>/gi, '\n')
    .replace(/<\/(p|li|div|h[1-6]|ul|ol)>/gi, '\n')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&#(x?[0-9a-f]+);/gi, (match, code) => {
      const radix = code[0].toLowerCase() === 'x' ? 16 : 10;
      const number = parseInt(radix === 16 ? code.slice(1) : code, radix);
      return Number.isFinite(number) ? String.fromCodePoint(number) : match;
    })
    .replace(/&([a-z]+);/gi, (match, name) => entities[name] ?? match)
    .replace(/[\t\r ]+/g, ' ')
    .replace(/ *\n+ */g, '\n')
    .trim();
}

function slugify(value) {
  return normalize(value)
    .replace(/&/g, ' e ')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'vaga';
}

function collectSlugs() {
  const slugs = new Set();
  const addSlug = value => {
    const slug = String(value || '').toLowerCase().trim();
    if (/^[a-z0-9-]{2,}$/.test(slug) && !INFRA.has(slug)) slugs.add(slug);
  };
  const addUrl = value => {
    const match = String(value || '').match(/https?:\/\/([a-z0-9-]+)\.inhire\.app/i);
    if (match) addSlug(match[1]);
  };

  for (const file of [
    'inhire_tenants_seed.json',
    'inhire_tenants.json',
    'inhire_all_tenants.json'
  ]) {
    for (const tenant of readJson(file, [])) addSlug(tenant && tenant.slug);
  }

  for (const file of ['us_app.json', 'us_app_paged.json']) {
    const data = readJson(file, {});
    for (const row of data.results || []) {
      const host = row.page && row.page.domain;
      const hostMatch = String(host || '').match(/^([a-z0-9-]+)\.inhire\.app$/i);
      if (hostMatch) addSlug(hostMatch[1]);
      addUrl(row.page && row.page.url);
      addUrl(row.task && row.task.url);
    }
  }

  for (const file of ['cc_app.jsonl', 'wb_app.txt']) {
    try {
      const content = fs.readFileSync(path.join(DIR, file), 'utf8');
      for (const match of content.matchAll(/https?:\/\/([a-z0-9-]+)\.inhire\.app/gi)) {
        addSlug(match[1]);
      }
    } catch {}
  }

  return [...slugs].sort();
}

async function fetchJson(url, headers, retries = 3) {
  let lastError;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers,
        signal: AbortSignal.timeout(20000)
      });
      if (!response.ok) {
        const error = new Error(`HTTP ${response.status}`);
        error.status = response.status;
        error.retryAfter = Number(response.headers.get('retry-after')) || 0;
        throw error;
      }
      return await response.json();
    } catch (error) {
      lastError = error;
      if (attempt === retries) break;
      const retryAfter = error.retryAfter ? error.retryAfter * 1000 : 0;
      const backoff = Math.max(retryAfter, 450 * attempt) + Math.floor(Math.random() * 250);
      await sleep(backoff);
    }
  }
  return { __error: cleanText(lastError && lastError.message, 120) || 'Falha desconhecida' };
}

async function pool(items, worker, concurrency) {
  const output = new Array(items.length);
  let cursor = 0;
  async function run() {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      try {
        output[index] = await worker(items[index], index);
      } catch (error) {
        output[index] = { __error: cleanText(error && error.message, 120) };
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, run));
  return output;
}

async function fetchTenant(slug) {
  const data = await fetchJson(API, { ...HEADERS, 'X-Tenant': slug });
  if (!data || data.__error || Array.isArray(data) || data.tenantName === undefined) return null;
  return {
    slug,
    tenantName: cleanText(data.tenantName || slug, 180),
    jobs: Array.isArray(data.jobsPage) ? data.jobsPage : []
  };
}

async function fetchDetail(slug, jobId) {
  const data = await fetchJson(`${API}/${encodeURIComponent(jobId)}`, {
    ...HEADERS,
    'X-Tenant': slug
  });
  return data && !data.__error && !Array.isArray(data) ? data : null;
}

function categoryFor(title) {
  const text = ` ${normalize(title).replace(/[^a-z0-9]+/g, ' ')} `;
  const rules = [
    ['Dados, BI e IA', /\b(data|dados|analytics|bi|business intelligence|cientista|machine learning|ml|artificial intelligence|inteligencia artificial|ia|ai|genai|llm|etl|databricks)\b/],
    ['Suporte, Atendimento e CS', /\b(suporte|support|service desk|help desk|atendimento|customer success|customer experience|cx|sac|implantacao|implementation)\b/],
    ['Produto e Projetos', /\b(produto|product|product owner|product manager|projetos|project|pmo|scrum|agile|business analyst|analista de negocios)\b/],
    ['TI e Desenvolvimento', /\b(desenvolvedor|desenvolvedora|developer|software|programador|engenheiro de software|arquiteto|devops|cloud|infraestrutura|cybersecurity|seguranca da informacao|sap|salesforce|qa|quality assurance|automacao|rpa|sre|backend|frontend|fullstack)\b/],
    ['Vendas e Comercial', /\b(vendas|sales|comercial|account executive|executivo de contas|sdr|bdr|pre vendas|inside sales|closer|key account)\b/],
    ['Marketing e Comunicação', /\b(marketing|growth|conteudo|content|social media|comunicacao|copywriter|seo|midia|designer|design|brand|crm)\b/],
    ['RH e Recrutamento', /\b(recursos humanos|rh|people|gente|talent|recrut|departamento pessoal|dp|remuneracao|beneficios)\b/],
    ['Financeiro e Contábil', /\b(financeiro|finance|contabil|contabilidade|fiscal|tesouraria|controladoria|billing|cobranca|credito|risco)\b/],
    ['Jurídico e Compliance', /\b(juridic|legal|advogad|compliance|privacidade|lgpd|contratos)\b/],
    ['Operações e Administrativo', /\b(operacoes|operations|administrativ|backoffice|back office|logistica|supply|compras|procurement|processos|qualidade)\b/],
    ['Engenharia e Indústria', /\b(engenheiro|engenheira|engenharia|manutencao|producao|industrial|civil|eletric|mecanic|obra|tecnico de campo)\b/],
    ['Saúde', /\b(medic|enferm|psicolog|nutric|farmac|saude|clinica|terapeut)\b/],
    ['Educação', /\b(professor|educacao|pedagog|instrutor|tutor|ensino|escola|academico)\b/]
  ];
  for (const [category, pattern] of rules) if (pattern.test(text)) return category;
  return 'Outros';
}

function seniorityFor(title) {
  const text = ` ${normalize(title).replace(/[^a-z0-9]+/g, ' ')} `;
  if (/\b(estagio|estagiario|internship|intern)\b/.test(text)) return 'Estágio';
  if (/\b(trainee|aprendiz)\b/.test(text)) return 'Trainee/Aprendiz';
  if (/\b(head|diretor|diretora|gerente|manager|coordenador|coordenadora|lead|lider|supervisor|supervisora)\b/.test(text)) return 'Liderança';
  if (/\b(senior|sr|especialista|specialist|staff|principal)\b/.test(text)) return 'Sênior/Especialista';
  if (/\b(pleno|pl|mid|mid level)\b/.test(text)) return 'Pleno';
  if (/\b(junior|jr|assistente|auxiliar)\b/.test(text)) return 'Júnior/Assistente';
  return 'Não informado';
}

function languageFor(description) {
  const text = normalize(description);
  if (!/\b(ingles|english)\b/.test(text)) return 'Não identificado';
  if (/\b(ingles|english)\b.{0,45}\b(fluente|avancado|advanced|fluent|c1|c2)\b/.test(text)) return 'Avançado/fluente';
  if (/\b(ingles|english)\b.{0,45}\b(intermediario|intermediate|b1|b2)\b/.test(text)) return 'Intermediário';
  if (/\b(ingles|english)\b.{0,45}\b(basico|basic|a1|a2)\b/.test(text)) return 'Básico';
  if (/\b(ingles|english)\b.{0,60}\b(diferencial|desejavel|nice to have)\b/.test(text)) return 'Diferencial';
  return 'Mencionado';
}

function contractTypesFor(value) {
  const raw = Array.isArray(value) ? value : [value];
  const contracts = raw.map(item => {
    if (typeof item === 'string') return cleanText(item, 60);
    if (!item || typeof item !== 'object') return '';
    return cleanText(item.label || item.name || item.value, 60);
  }).filter(Boolean);
  return [...new Set(contracts)];
}

function workplaceTypeFor(value) {
  const raw = typeof value === 'object' && value
    ? value.label || value.name || value.value
    : value;
  const text = normalize(raw);
  if (/\b(remote|remoto|home office|teletrabalho)\b/.test(text)) return 'Remoto';
  if (/\b(hybrid|hibrid)\b/.test(text)) return 'Híbrido';
  if (/\b(on site|onsite|on-site|presencial|office)\b/.test(text)) return 'Presencial';
  return 'Não informada';
}

function explicitModality(text) {
  const normalized = normalize(text).slice(0, 12000);
  if (/\b(modelo|regime|modalidade|atuacao|trabalho)\b.{0,55}\b(hybrid|hibrid)\b/.test(normalized)) return 'Híbrido';
  if (/\b(modelo|regime|modalidade|atuacao|trabalho)\b.{0,55}\b(on site|onsite|presencial)\b/.test(normalized)) return 'Presencial';
  if (/\b(modelo|regime|modalidade|atuacao|trabalho)\b.{0,55}\b(remote|remoto|home office|teletrabalho)\b/.test(normalized)) return 'Remoto';
  return '';
}

function alertsFor(title, location, description, workplaceType, detailLoaded) {
  const alerts = [];
  const titleModality = explicitModality(`modalidade ${title}`);
  const descriptionModality = explicitModality(description);
  if (workplaceType === 'Não informada') alerts.push('A modalidade não foi informada pela plataforma');
  if (titleModality && workplaceType !== 'Não informada' && titleModality !== workplaceType) {
    alerts.push(`O título indica ${titleModality.toLowerCase()}, mas a plataforma classifica como ${workplaceType.toLowerCase()}`);
  }
  if (descriptionModality && workplaceType !== 'Não informada' && descriptionModality !== workplaceType) {
    alerts.push(`A descrição pode indicar modalidade ${descriptionModality.toLowerCase()}`);
  }
  const normalizedLocation = normalize(location);
  if (workplaceType === 'Remoto' && normalizedLocation && !/^(br|brasil|brazil|remot|remote|home office|anywhere|global)$/.test(normalizedLocation)) {
    alerts.push(`Confirme a elegibilidade para: ${cleanText(location, 100)}`);
  }
  if (!detailLoaded) alerts.push('Os detalhes não foram recuperados nesta atualização');
  return [...new Set(alerts)];
}

function validIso(value) {
  if (!value || Number.isNaN(Date.parse(value))) return '';
  return new Date(value).toISOString();
}

function cachedJobs() {
  const file = path.join(OUTPUT_DIR, 'vagas.json');
  try {
    const rows = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
    return Array.isArray(rows) ? rows : [];
  } catch {
    return [];
  }
}

function canReuseDetail(cached, tenant, job, now) {
  if (!cached || !cached.detailFetchedAt) return false;
  const fetchedAt = Date.parse(cached.detailFetchedAt);
  if (!Number.isFinite(fetchedAt) || now - fetchedAt >= DETAIL_TTL_HOURS * 3600000) return false;
  const listingTitle = cleanText(job.displayName, 260);
  const listingLocation = cleanText(job.location, 140);
  const listingWorkplace = workplaceTypeFor(job.workplaceType);
  if (listingTitle && normalize(cached.title) !== normalize(listingTitle)) return false;
  if (listingLocation && normalize(cached.location) !== normalize(listingLocation)) return false;
  if (listingWorkplace !== 'Não informada' && cached.workplaceType !== listingWorkplace) return false;
  return normalize(cached.company) === normalize(tenant.tenantName);
}

(async () => {
  const startedAt = new Date();
  const now = Date.now();
  const cache = new Map(cachedJobs().map(item => [item.id, item]));
  const candidateSlugs = collectSlugs();
  if (!candidateSlugs.length) throw new Error('Nenhum tenant candidato foi encontrado.');

  console.log(`Tenants candidatos: ${candidateSlugs.length}`);
  const tenantResults = await pool(candidateSlugs, fetchTenant, 10);
  const tenants = tenantResults.filter(Boolean);
  console.log(`Tenants públicos confirmados: ${tenants.length}`);

  const publishedCandidates = [];
  let excludedDemoJobs = 0;
  for (const tenant of tenants) {
    const isDemo = DEMO_TENANTS.has(tenant.slug) || normalize(tenant.tenantName) === 'demo';
    for (const job of tenant.jobs) {
      if (String(job.status || '').toLowerCase() !== 'published') continue;
      if (isDemo) {
        excludedDemoJobs += 1;
        continue;
      }
      publishedCandidates.push({ tenant, job });
    }
  }

  const uniqueCandidates = [...new Map(
    publishedCandidates.map(item => [`${item.tenant.slug}:${item.job.jobId}`, item])
  ).values()];
  console.log(`Vagas publicadas para detalhar: ${uniqueCandidates.length}`);

  let detailCount = 0;
  let detailsFetched = 0;
  let detailsReused = 0;
  const jobs = await pool(uniqueCandidates, async ({ tenant, job }, index) => {
    const id = `${tenant.slug}:${cleanText(job.jobId, 80)}`;
    const cached = cache.get(id);
    if (canReuseDetail(cached, tenant, job, now)) {
      detailCount += 1;
      detailsReused += 1;
      return {
        ...cached,
        id,
        url: `https://${tenant.slug}.inhire.app/vagas/${encodeURIComponent(job.jobId)}/${slugify(cached.title)}`,
        careerPage: `https://${tenant.slug}.inhire.app/vagas`
      };
    }

    const detail = await fetchDetail(tenant.slug, job.jobId);
    const title = cleanText((detail && detail.displayName) || job.displayName, 260);
    const company = cleanText((detail && detail.tenantName) || tenant.tenantName, 180);
    const location = cleanText((detail && detail.location) || job.location, 140);
    const workplaceType = workplaceTypeFor((detail && detail.workplaceType) || job.workplaceType);
    const description = detail ? decodeHtml(detail.description) : '';
    if (detail) {
      detailCount += 1;
      detailsFetched += 1;
    }
    if ((index + 1) % 100 === 0) console.log(`  Detalhes ${index + 1}/${uniqueCandidates.length}`);

    return {
      id,
      company,
      title,
      category: categoryFor(title),
      seniority: seniorityFor(title),
      workplaceType,
      location: location || 'Não informada',
      contractTypes: contractTypesFor(detail && detail.contractType),
      languageRequirement: languageFor(description),
      publishedAt: validIso(detail && (detail.publishedAt || detail.createdAt)),
      lastPublishedAt: validIso(detail && (detail.lastPublishedAt || detail.publishedAt || detail.createdAt)),
      updatedAt: validIso(detail && detail.updatedAt),
      detailFetchedAt: detail ? new Date().toISOString() : '',
      alerts: alertsFor(title, location, description, workplaceType, Boolean(detail)),
      url: `https://${tenant.slug}.inhire.app/vagas/${encodeURIComponent(job.jobId)}/${slugify(title)}`,
      careerPage: `https://${tenant.slug}.inhire.app/vagas`
    };
  }, DETAIL_WORKERS);

  jobs.sort((a, b) => {
    const dateA = a.lastPublishedAt || a.publishedAt;
    const dateB = b.lastPublishedAt || b.publishedAt;
    const dateCompare = dateB.localeCompare(dateA);
    if (dateCompare) return dateCompare;
    const companyCompare = a.company.localeCompare(b.company, 'pt-BR');
    return companyCompare || a.title.localeCompare(b.title, 'pt-BR');
  });

  const byCategory = {};
  const byContract = {};
  const byWorkplace = {};
  for (const job of jobs) {
    byCategory[job.category] = (byCategory[job.category] || 0) + 1;
    byWorkplace[job.workplaceType] = (byWorkplace[job.workplaceType] || 0) + 1;
    for (const contract of job.contractTypes.length ? job.contractTypes : ['Não informado']) {
      byContract[contract] = (byContract[contract] || 0) + 1;
    }
  }

  const finishedAt = new Date();
  const companies = new Set(jobs.map(job => job.company));
  const meta = {
    schemaVersion: 2,
    collectedAt: finishedAt.toISOString(),
    durationSeconds: Math.round((finishedAt - startedAt) / 1000),
    candidateTenants: candidateSlugs.length,
    confirmedTenants: tenants.length,
    totalJobs: jobs.length,
    companies: companies.size,
    detailsLoaded: detailCount,
    detailsFetched,
    detailsReused,
    detailCacheHours: DETAIL_TTL_HOURS,
    jobsWithAlerts: jobs.filter(job => job.alerts.length).length,
    excludedDemoJobs,
    source: 'Páginas públicas de carreiras da InHire',
    coverageNote: 'A InHire não oferece um catálogo global. A cobertura corresponde aos tenants públicos descobertos e confirmados pela rotina.',
    byWorkplace: Object.fromEntries(Object.entries(byWorkplace).sort((a, b) => b[1] - a[1])),
    byCategory: Object.fromEntries(Object.entries(byCategory).sort((a, b) => b[1] - a[1])),
    byContract: Object.fromEntries(Object.entries(byContract).sort((a, b) => b[1] - a[1]))
  };

  writeJsonAtomic(path.join(OUTPUT_DIR, 'vagas.json'), jobs);
  writeJsonAtomic(path.join(OUTPUT_DIR, 'meta.json'), meta);
  console.log(JSON.stringify(meta, null, 2));
})().catch(error => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
