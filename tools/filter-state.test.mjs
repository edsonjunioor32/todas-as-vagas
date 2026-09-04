import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const app = fs.readFileSync(path.join(root, 'docs', 'app.js'), 'utf8');

assert.match(
  app,
  /function selectedLabel\(value, formatter\)\s*\{[\s\S]*?return raw \? formatter\(raw\) : '';\s*\}/,
  'A interface deve ignorar valores vazios ao formar chips de filtro.'
);
assert.match(
  app,
  /add\('portal', 'Portal', selectedLabel\(elements\.sourceFilter\.value, sourceLabel\)\)/,
  'O chip de portal deve depender de uma seleção real.'
);
assert.match(
  app,
  /add\('mercado', 'Mercado', selectedLabel\(elements\.marketFilter\.value, marketLabel\)\)/,
  'O chip de mercado deve depender de uma seleção real.'
);
assert.match(
  app,
  /\['nao informado', 'portal nao informado'\]\.includes\(normalize\(value\)\)/,
  'Valores sem informação não devem virar opções de portal ou mercado.'
);

console.log('Filtro sem seleção não gera chips fantasma.');

const html = fs.readFileSync(path.join(root, 'docs', 'index.html'), 'utf8');
assert.doesNotMatch(html, /EMPRESAS MONITORADAS/i, 'O quadro de empresas monitoradas não deve aparecer no portal.');
assert.doesNotMatch(html, /id="monitoredCompanies"/, 'O contêiner de empresas monitoradas deve ser removido.');
assert.doesNotMatch(app, /renderMonitoredCompanies|greenhouse-watchlist/, 'A interface não deve buscar nem renderizar a lista removida.');
assert.match(
  app,
  /const days = Number\(elements\.periodFilter\.value \|\| 0\)/,
  'A consulta padrão deve respeitar o recorte do snapshot sem aplicar um segundo filtro móvel de 60 dias.'
);
assert.match(
  app,
  /function categoryLabel\(value\)/,
  'Categorias de fontes diferentes devem passar por uma taxonomia de exibição comum.'
);
assert.match(html, /<link rel="canonical" href="https:\/\/edsonjunioor32\.github\.io\/todas-as-vagas\/">/);
assert.match(html, /meta property="og:url" content="https:\/\/edsonjunioor32\.github\.io\/todas-as-vagas\/"/);
assert.match(html, /id="resultsTitle" aria-live="polite"/);
assert.match(html, /id="activeFilters" role="status" aria-live="polite"/);
