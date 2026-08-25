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
