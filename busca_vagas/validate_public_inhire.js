const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const DATA_DIR = process.env.INHIRE_OUTPUT_DIR
  ? path.resolve(process.env.INHIRE_OUTPUT_DIR)
  : path.join(ROOT, 'jobs-dashboard', 'data', 'inhire');

function fail(message) {
  throw new Error(`Base pública inválida: ${message}`);
}

function readJson(name) {
  const file = path.join(DATA_DIR, name);
  if (!fs.existsSync(file)) fail(`${name} não existe`);
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

const jobs = readJson('vagas.json');
const meta = readJson('meta.json');

if (!Array.isArray(jobs) || jobs.length === 0) fail('vagas.json deve conter ao menos uma vaga');
if (!meta || meta.schemaVersion !== 2) fail('meta.json deve usar schemaVersion 2');
if (meta.totalJobs !== jobs.length) fail('a contagem de vagas não corresponde ao arquivo');
if (!meta.collectedAt || Number.isNaN(Date.parse(meta.collectedAt))) fail('data de atualização ausente');

const ids = new Set();
const forbiddenKeys = new Set(['description', 'descriptionSummary', 'about', 'requirements']);
const requiredStrings = ['id', 'company', 'title', 'category', 'seniority', 'workplaceType', 'location', 'url'];
const allowedWorkplaceTypes = new Set(['Remoto', 'Híbrido', 'Presencial', 'Não informada']);

for (const [index, job] of jobs.entries()) {
  for (const key of requiredStrings) {
    if (typeof job[key] !== 'string' || !job[key].trim()) fail(`vaga ${index + 1}: campo ${key} ausente`);
  }
  if (ids.has(job.id)) fail(`ID duplicado: ${job.id}`);
  ids.add(job.id);
  if (!allowedWorkplaceTypes.has(job.workplaceType)) fail(`vaga ${job.id}: modalidade inválida`);
  if (/^demo$/i.test(job.company.trim())) fail(`vaga ${job.id}: tenant demo não foi excluído`);
  if (!/^https:\/\/[a-z0-9-]+\.inhire\.app\/vagas\//i.test(job.url)) {
    fail(`vaga ${job.id}: link de candidatura inválido`);
  }
  if (!Array.isArray(job.contractTypes) || !Array.isArray(job.alerts)) {
    fail(`vaga ${job.id}: contratos ou alertas inválidos`);
  }
  for (const key of Object.keys(job)) {
    if (forbiddenKeys.has(key)) fail(`vaga ${job.id}: o campo privado ${key} não pode ser publicado`);
  }
}

const companies = new Set(jobs.map(job => job.company)).size;
if (meta.companies !== companies) fail('a contagem de empresas não corresponde ao arquivo');
const workplaceTotal = Object.values(meta.byWorkplace || {}).reduce((sum, value) => sum + Number(value || 0), 0);
if (workplaceTotal !== jobs.length) fail('a contagem por modalidade não corresponde ao arquivo');

const dataSize = fs.statSync(path.join(DATA_DIR, 'vagas.json')).size;
if (dataSize > 15 * 1024 * 1024) fail('vagas.json excede 15 MB');

console.log(`Base validada: ${jobs.length} vagas, ${companies} empresas, ${(dataSize / 1024 / 1024).toFixed(2)} MB.`);
