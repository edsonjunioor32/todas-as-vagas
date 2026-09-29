import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const html = fs.readFileSync(path.join(root, 'docs', 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(root, 'docs', 'app.js'), 'utf8');

assert.match(html, /<label for="excludeTerms">Não exibir vagas com:<\/label>/i);
assert.match(html, /<input id="excludeTerms" name="excluir" type="text" placeholder="Cargo, empresa ou palavra-chave"/);
assert.match(html, /Separe os termos por vírgula[\s\S]*qualquer termo/i);
assert.match(html, /filter-terms\.js[^\n]*defer[\s\S]*app\.js/);

const { parseExcludedTerms, matchesExcludedTerm } = require(path.join(root, 'docs', 'filter-terms.js'));
const terms = parseExcludedTerms(' vitru, estágio, , VITRU, sem experiência ');
assert.deepEqual(terms, ['vitru', 'estagio', 'sem experiencia']);
assert.equal(matchesExcludedTerm('Analista de Suporte • VITRU • Belo Horizonte', terms), true);
assert.equal(matchesExcludedTerm('Estágio em Administração', terms), true);
assert.equal(matchesExcludedTerm('Analista de Suporte em Belo Horizonte', terms), false);
assert.equal(matchesExcludedTerm('Analista de Suporte • VITRU', []), false);

assert.match(app, /excludeTerms: document\.querySelector\('#excludeTerms'\)/);
assert.match(app, /params\.get\('excluir'\)/);
assert.match(app, /excluir: elements\.excludeTerms\.value\.trim\(\)/);
assert.match(app, /add\('excluir', 'Não exibir vagas com'/);
assert.match(app, /excluir: elements\.excludeTerms/);
assert.match(app, /matchesExcludedTerm\(job\._search, excludedTerms\)/);
assert.match(app, /elements\.excludeTerms\.addEventListener\('input', scheduleRender\)/);

console.log('Filtro de exclusão por termos separados por vírgula validado.');
