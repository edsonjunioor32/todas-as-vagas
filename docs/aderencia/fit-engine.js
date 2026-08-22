const STOP_WORDS = new Set(['a','ao','aos','as','com','da','das','de','do','dos','e','em','na','nas','no','nos','o','os','ou','para','por','que','se','um','uma','the','and','or','of','to','in','with','for','on','an','at','is','are','be','as','from']);

export function normalizeText(value) {
  return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[–—]/g, '-').replace(/\s+/g, ' ').trim();
}
function escapeRegExp(value) { return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

export function containsAlias(normalizedResume, alias) {
  const token = normalizeText(alias);
  if (!token) return false;
  if (token === 'sql') return /(^|[^a-z0-9])(?:sql|pl\/sql|plsql)(?=$|[^a-z0-9])/.test(normalizedResume);
  if (token.length <= 4 || /[.+#/-]/.test(token)) {
    return new RegExp(`(^|[^a-z0-9])${escapeRegExp(token)}(?=$|[^a-z0-9])`).test(normalizedResume);
  }
  return normalizedResume.includes(token);
}

export function buildTaxonomyIndex(taxonomy) {
  const byLabel = new Map(), byId = new Map();
  for (const entry of taxonomy?.entries || []) {
    byLabel.set(normalizeText(entry.label), entry);
    byId.set(entry.id, entry);
  }
  return { byLabel, byId, entries: taxonomy?.entries || [] };
}

function supersets(entry, index) {
  const ids = [];
  if (entry?.id === 'english-basic') ids.push('english-intermediate', 'english-advanced', 'english-fluent');
  if (entry?.id === 'english-intermediate') ids.push('english-advanced', 'english-fluent');
  if (entry?.id === 'english-advanced') ids.push('english-fluent');
  if (entry?.id === 'spanish-intermediate') ids.push('spanish-advanced');
  if (entry?.id === 'higher-education') ids.push('higher-education-complete', 'postgraduate');
  if (entry?.id === 'higher-education-complete') ids.push('postgraduate');
  return ids.map(id => index.byId.get(id)).filter(Boolean);
}

function genericPhraseMatch(resume, label) {
  const normalized = normalizeText(label);
  if (!normalized) return false;
  if (resume.includes(normalized)) return true;
  const tokens = normalized.split(/[^a-z0-9+#./-]+/).filter(token => token.length > 1 && !STOP_WORDS.has(token));
  if (!tokens.length) return false;
  if (tokens.length === 1) return containsAlias(resume, tokens[0]);
  return tokens.filter(token => containsAlias(resume, token)).length / tokens.length >= 0.72;
}

function matchNormalized(resume, label, index) {
  const entry = index.byLabel.get(normalizeText(label));
  if (!entry) return genericPhraseMatch(resume, label);
  return [entry, ...supersets(entry, index)].some(item => [item.label, ...(item.aliases || [])].some(alias => containsAlias(resume, alias)));
}

export function matchRequirement(resumeText, label, taxonomyIndex) {
  return matchNormalized(normalizeText(resumeText), label, taxonomyIndex);
}

export function decodeRequirementEntry(entry, terms) {
  const read = key => (entry?.[key] || []).map(index => terms?.[index]).filter(Boolean);
  return { mandatory: read('m'), preferred: read('p'), context: read('c'), manual: read('x'), confidence: Number(entry?.q || 0) };
}

function evaluateList(labels, resume, index) {
  const matched = [], missing = [];
  for (const label of labels) (matchNormalized(resume, label, index) ? matched : missing).push(label);
  return { matched, missing, total: labels.length, ratio: labels.length ? matched.length / labels.length : null };
}

function evaluate(requirements, resume, index, resumeLength) {
  const mandatory = evaluateList(requirements?.mandatory || [], resume, index);
  const preferred = evaluateList(requirements?.preferred || [], resume, index);
  const context = evaluateList(requirements?.context || [], resume, index);
  const manual = [...(requirements?.manual || [])];
  let score = 0, weight = 0;
  if (mandatory.total) { score += mandatory.ratio * 80; weight += 80; }
  if (preferred.total) { score += preferred.ratio * 15; weight += 15; }
  if (context.total) { score += context.ratio * 5; weight += 5; }
  if (weight) score *= 100 / weight;

  if (mandatory.total >= 4 && mandatory.ratio < 0.5) score = Math.min(score, 55);
  else if (mandatory.missing.length >= 2 && mandatory.ratio < 0.75) score = Math.min(score, 69);
  else if (mandatory.missing.length >= 1 && mandatory.total <= 3) score = Math.min(score, 79);
  if (!mandatory.total && Number(requirements?.confidence || 0) < 60) score = Math.min(score, 75);

  const resumeQuality = resumeLength >= 900 ? 100 : resumeLength >= 450 ? 80 : resumeLength >= 220 ? 55 : 30;
  const extractionConfidence = Math.max(0, Math.min(100, Number(requirements?.confidence || 0)));
  const coverage = Math.round(extractionConfidence * resumeQuality / 100);
  const rounded = Math.max(0, Math.min(100, Math.round(score)));
  return {
    score: rounded,
    coverage,
    mandatory,
    preferred,
    context,
    matched: [...new Set([...mandatory.matched, ...preferred.matched, ...context.matched])],
    gaps: [...new Set(mandatory.missing)],
    optionalMissing: [...new Set(preferred.missing)],
    manual,
    label: rounded >= 85 ? 'Aderência muito forte' : rounded >= 70 ? 'Aderência forte' : rounded >= 55 ? 'Aderência parcial' : 'Aderência baixa'
  };
}

export function evaluateCandidateFit(requirements, resumeText, taxonomy) {
  const resume = normalizeText(resumeText);
  return evaluate(requirements, resume, buildTaxonomyIndex(taxonomy), resume.length);
}

export function fallbackRequirements(job) {
  const skills = String(job?.skills || '').split(/\s*[·|;,]\s*/).map(value => value.trim()).filter(value => value.length >= 2 && value.length <= 72);
  return { mandatory: [...new Set(skills)].slice(0, 12), preferred: [], context: [], manual: [], confidence: skills.length ? 40 : 20 };
}

export function rankJobs(jobs, fitData, resumeText, taxonomy, limit = 30) {
  const results = [], terms = fitData?.terms || [], entries = fitData?.jobs || {};
  const resume = normalizeText(resumeText), index = buildTaxonomyIndex(taxonomy);
  for (const job of jobs || []) {
    const packed = entries[job.url];
    const requirements = packed ? decodeRequirementEntry(packed, terms) : fallbackRequirements(job);
    if (!packed && !job.skills) continue;
    results.push({ job, requirements, result: evaluate(requirements, resume, index, resume.length) });
  }
  results.sort((a, b) => b.result.score - a.result.score || b.result.coverage - a.result.coverage || String(a.job.title).localeCompare(String(b.job.title), 'pt-BR'));
  return results.slice(0, Math.max(1, limit));
}
