/**
 * Atualiza a lista de possíveis subdomínios InHire usando fontes da web aberta.
 * Falhas isoladas não interrompem a rotina: o coletor principal também usa a
 * lista-base versionada em inhire_tenants_seed.json.
 */
const fs = require('fs');
const path = require('path');

const DIR = __dirname;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

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
    const url = 'https://web.archive.org/cdx/search/cdx?url=*.inhire.app&output=text&fl=original&collapse=urlkey&filter=statuscode:200&limit=200000';
    const text = await getText(url, 60000);
    writeIfUseful('wb_app.txt', text);
    const hosts = new Set(
      (text.match(/https?:\/\/[a-z0-9-]+\.inhire\.app/gi) || [])
        .map(value => value.replace(/^https?:\/\//, '').toLowerCase())
    );
    console.log(`[Wayback] ${hosts.size} hosts únicos.`);
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
    for (let page = 0; page < 6; page += 1) {
      const url = `${base}${searchAfter ? `&search_after=${encodeURIComponent(searchAfter)}` : ''}`;
      const response = JSON.parse(await getText(url, 30000));
      const results = Array.isArray(response.results) ? response.results : [];
      all.push(...results);
      if (results.length < 100) break;
      const sort = results.at(-1) && results.at(-1).sort;
      if (!Array.isArray(sort) || !sort.length) break;
      searchAfter = sort.join(',');
      await sleep(1400);
    }
    writeIfUseful('us_app_paged.json', JSON.stringify({ results: all }));
    console.log(`[urlscan] ${all.length} resultados.`);
  } catch (error) {
    console.log(`[urlscan] indisponível: ${error.message}`);
  }
}

async function commonCrawl(indexLimit = 8) {
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
        `https://index.commoncrawl.org/${index}-index?url=*.inhire.app&output=json&fl=url`,
        45000
      );
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
  await commonCrawl();
  console.log('[Descoberta] concluída.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
