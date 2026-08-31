/**
 * Atualiza a lista de possíveis subdomínios InHire usando fontes da web aberta.
 * Falhas isoladas não interrompem a rotina: o coletor principal também usa a
 * lista-base versionada em inhire_tenants_seed.json.
 */
const fs = require('fs');
const path = require('path');

const DIR = __dirname;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

const SEED_FILE = 'inhire_tenants_seed.json';
const INFRA = new Set([
  'www', 'api', 'auth', 'app', 'status', 'mcp', 'mcp-dev', 'inhub', 'login',
  'admin', 'inhire-admin', 'saml-setup', 'sso-setup', 'preview', 'senior',
  'files', 'portal', 'board', 'people', 'new', 'novo', 'conteudo', 'docs',
  'email', 'lp', 'hub', 'webinar', 'analytics', 'analytics-ss'
]);
const discovered = new Set();

function addDiscoveredSlug(value) {
  const slug = String(value || '').toLowerCase().trim();
  if (!/^[a-z0-9-]{2,}$/.test(slug) || INFRA.has(slug)) return false;
  discovered.add(slug);
  return true;
}

function collectFromText(value) {
  const text = String(value || '').replace(/\\\//g, '/');
  for (const match of text.matchAll(/\b([a-z0-9-]+)\.inhire\.app\b/gi)) {
    addDiscoveredSlug(match[1]);
  }
}

function mergeDiscoveredIntoSeed() {
  let current = [];
  try {
    current = JSON.parse(fs.readFileSync(path.join(DIR, SEED_FILE), 'utf8').replace(/^\uFEFF/, ''));
  } catch {}

  const bySlug = new Map();
  for (const item of Array.isArray(current) ? current : []) {
    const slug = String(item && item.slug || '').toLowerCase().trim();
    if (!/^[a-z0-9-]{2,}$/.test(slug) || INFRA.has(slug)) continue;
    const tenantName = String(item && item.tenantName || slug).trim() || slug;
    bySlug.set(slug, { slug, tenantName });
  }

  const before = bySlug.size;
  for (const slug of [...discovered].sort()) {
    if (!bySlug.has(slug)) bySlug.set(slug, { slug, tenantName: slug });
  }

  const merged = [...bySlug.values()].sort((a, b) => a.slug.localeCompare(b.slug));
  const changed = JSON.stringify(current) !== JSON.stringify(merged);
  if (changed) {
    writeIfUseful(SEED_FILE, JSON.stringify(merged, null, 2) + '\n');
  }
  console.log('[Seed] ' + (merged.length - before) + ' novos candidatos; ' + merged.length + ' tenants candidatos persistidos.');
}


async function getText(url, timeout = 45000) {
  const response = await fetch(url, {
    headers: { 'User-Agent': 'radar-vagas/3.0' },
    signal: AbortSignal.timeout(timeout)
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.text();
}

function writeIfUseful(file, content) {
  if (!content || !String(content).trim()) return false;
  fs.writeFileSync(path.join(DIR, file), content, 'utf8');
  return true;
}

async function wayback() {
  console.log('[Wayback] procurando subdomínios...');
  try {
    const url = 'https://web.archive.org/cdx/search/cdx?url=*.inhire.app/*&output=text&fl=original&collapse=urlkey&filter=statuscode:200&limit=200000';
    const text = await getText(url, 60000);
    writeIfUseful('wb_app.txt', text);
    collectFromText(text);
    const hosts = new Set(
      (text.match(/https?:\/\/[a-z0-9-]+\.inhire\.app/gi) || [])
        .map(value => value.replace(/^https?:\/\//, '').toLowerCase())
    );
    console.log('[Wayback] ' + hosts.size + ' hosts únicos; acumulados: ' + discovered.size + '.');
  } catch (error) {
    console.log(`[Wayback] indisponível: ${error.message}`);
  }
}

async function urlscan() {
  console.log('[urlscan] procurando subdomínios...');
  const base = 'https://urlscan.io/api/v1/search/?q=domain:inhire.app&size=100';
  let searchAfter = '';
  const all = [];
  try {
    const pageLimit = Math.min(30, Math.max(1, Number(process.env.INHIRE_URLSCAN_PAGES) || 20));
    for (let page = 0; page < pageLimit; page += 1) {
      const url = `${base}${searchAfter ? `&search_after=${encodeURIComponent(searchAfter)}` : ''}`;
      const response = JSON.parse(await getText(url, 30000));
      collectFromText(JSON.stringify(response));
      const results = Array.isArray(response.results) ? response.results : [];
      all.push(...results);
      if (results.length < 100) break;
      const sort = results.at(-1) && results.at(-1).sort;
      if (!Array.isArray(sort) || !sort.length) break;
      searchAfter = sort.join(',');
      await sleep(1400);
    }
    writeIfUseful('us_app_paged.json', JSON.stringify({ results: all }));
    console.log('[urlscan] ' + all.length + ' resultados; acumulados: ' + discovered.size + '.');
  } catch (error) {
    console.log(`[urlscan] indisponível: ${error.message}`);
  }
}

async function crtSh() {
  console.log('[crt.sh] procurando certificados para subdomínios...');
  try {
    const text = await getText('https://crt.sh/?q=%25.inhire.app&output=json', 60000);
    writeIfUseful('crt_inhire.json', text);
    collectFromText(text);
    console.log('[crt.sh] acumulados: ' + discovered.size + '.');
  } catch (error) {
    console.log('[crt.sh] indisponível: ' + error.message);
  }
}

async function commonCrawl(indexLimit = Math.min(48, Math.max(1, Number(process.env.INHIRE_COMMONCRAWL_INDEXES) || 24))) {
  console.log('[Common Crawl] procurando subdomínios...');
  let indexes;
  try {
    const info = JSON.parse(await getText('https://index.commoncrawl.org/collinfo.json', 30000));
    indexes = info.slice(0, indexLimit).map(item => item.id);
  } catch (error) {
    console.log(`[Common Crawl] índices indisponíveis: ${error.message}`);
    return;
  }

  const chunks = [];
  for (const index of indexes) {
    try {
      const text = await getText(
        `https://index.commoncrawl.org/${index}-index?url=*.inhire.app/*&output=json&fl=url`,
        45000
      );
      collectFromText(text);
      if (text.trim()) chunks.push(text.trim());
      console.log(`  ${index}: ok`);
    } catch (error) {
      console.log(`  ${index}: sem resposta útil`);
    }
    await sleep(350);
  }
  writeIfUseful('cc_app.jsonl', `${chunks.join('\n')}\n`);
}

(async () => {
  await wayback();
  await urlscan();
  await crtSh();
  await commonCrawl();
  mergeDiscoveredIntoSeed();
  console.log('[Descoberta] concluída; ' + discovered.size + ' hosts públicos candidatos encontrados.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
