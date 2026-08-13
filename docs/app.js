(() => {
  'use strict';

  const PAGE_SIZE = 24;
  const collator = new Intl.Collator('pt-BR', { sensitivity: 'base', numeric: true });
  const numberFormatter = new Intl.NumberFormat('pt-BR');
  const dateTimeFormatter = new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: 'America/Fortaleza'
  });
  const dateFormatter = new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'America/Fortaleza'
  });
  const CONTRACT_MODELS = [
    { value: 'CLT', sourceValue: 'CLT' },
    { value: 'CNPJ', sourceValue: 'PJ' },
    { value: 'Cooperado', sourceValue: 'Cooperado' }
  ];

  const SOURCE_LABELS = {
    inhire: 'InHire',
    empregare: 'Empregare',
    gupy: 'Gupy',
    solides: 'Sólides',
    geekhunter: 'GeekHunter',
    stone: 'Stone',
    ifood: 'iFood',
    picpay: 'PicPay',
    bancooriginal: 'Banco Original',
    braskem: 'Braskem',
    gmfinancial: 'GM Financial',
    dell: 'Dell Technologies',
    arcelormittal: 'ArcelorMittal',
    grupomateus: 'Grupo Mateus',
    autozone: 'AutoZone',
    nov: 'NOV',
    arcorbrasil: 'Arcor Brasil',
    themuse: 'The Muse',
    remotive: 'Remotive',
    jobicy: 'Jobicy',
    remoteok: 'Remote OK',
    himalayas: 'Himalayas',
    workingnomads: 'Working Nomads',
    arbeitnow: 'Arbeitnow',
    weworkremotely: 'We Work Remotely',
    greenhouse: 'Greenhouse',
    lever: 'Lever',
    ashby: 'Ashby'
  };

  const state = { jobs: [], filtered: [], meta: null, page: 1 };
  const elements = {
    totalJobs: document.querySelector('#totalJobs'),
    totalCompanies: document.querySelector('#totalCompanies'),
    totalSources: document.querySelector('#totalSources'),
    updatedLabel: document.querySelector('#updatedLabel'),
    sourceWarning: document.querySelector('#sourceWarning'),
    filtersForm: document.querySelector('#filtersForm'),
    searchInput: document.querySelector('#searchInput'),
    sourceFilter: document.querySelector('#sourceFilter'),
    workplaceFilter: document.querySelector('#workplaceFilter'),
    contractFilter: document.querySelector('#contractFilter'),
    cityFilter: document.querySelector('#cityFilter'),
    cityOptions: document.querySelector('#cityOptions'),
    marketFilter: document.querySelector('#marketFilter'),
    categoryFilter: document.querySelector('#categoryFilter'),
    seniorityFilter: document.querySelector('#seniorityFilter'),
    periodFilter: document.querySelector('#periodFilter'),
    pcdOnly: document.querySelector('#pcdOnly'),
    duplicatesOnly: document.querySelector('#duplicatesOnly'),
    sortFilter: document.querySelector('#sortFilter'),
    clearFilters: document.querySelector('#clearFilters'),
    downloadCsv: document.querySelector('#downloadCsv'),
    resultCount: document.querySelector('#resultCount'),
    statusMessage: document.querySelector('#statusMessage'),
    jobList: document.querySelector('#jobList'),
    pagination: document.querySelector('#pagination'),
    previousPage: document.querySelector('#previousPage'),
    nextPage: document.querySelector('#nextPage'),
    pageLabel: document.querySelector('#pageLabel'),
    resultsTitle: document.querySelector('#resultsTitle')
  };

  function normalize(value) {
    return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  }

  function sourceLabel(value) {
    return SOURCE_LABELS[value] || String(value || 'Portal não informado');
  }

  function workplaceLabel(value) {
    const key = normalize(value);
    if (key === 'remote' || key === 'remoto') return 'Remoto';
    if (key === 'hybrid' || key === 'hibrido') return 'Híbrido';
    if (key === 'on-site' || key === 'onsite' || key === 'presencial') return 'Presencial';
    return 'Não informada';
  }

  function marketLabel(value) {
    if (value === 'BR') return 'Brasil';
    if (value === 'Global remote') return 'Global remoto';
    return value || 'Não informado';
  }

  function contractLabel(value) {
    return normalize(value) === 'pj' ? 'CNPJ' : String(value || '');
  }

  function extractCityNames(value) {
    const genericLocations = new Set([
      'anywhere', 'br', 'brasil', 'brazil', 'global', 'hybrid', 'hibrido',
      'nao informada', 'presencial', 'remote', 'remoto', 'united states',
      'usa', 'worldwide'
    ]);
    return String(value || '')
      .split(/\s+[·|;]\s+/)
      .map(part => part.trim())
      .filter(Boolean)
      .map(part => part.split(',')[0].trim().replace(/^(?:br|us|usa)\s*-\s*/i, ''))
      .filter(city => city && !genericLocations.has(normalize(city)));
  }

  function toTime(value) {
    if (!value) return 0;
    const text = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00Z` : value;
    const parsed = Date.parse(text);
    return Number.isNaN(parsed) ? 0 : parsed;
  }

  function activityTime(job) {
    const time = toTime(job.publishedAt) || toTime(job.lastSeenAt);
    return Math.min(time, Date.now());
  }

  function publicationClock(value) {
    const time = toTime(value);
    if (!time || time > Date.now()) return '';
    const match = String(value || '').match(/T(\d{2}:\d{2})/);
    return match ? ` às ${match[1]}` : '';
  }

  function activityLabel(job) {
    const time = activityTime(job);
    if (!time) return 'Data não informada';
    const today = new Date();
    today.setHours(12, 0, 0, 0);
    const current = new Date(time);
    current.setHours(12, 0, 0, 0);
    const days = Math.round((today - current) / 86400000);
    const prefix = job.publishedAt ? 'Publicada' : 'Vista';
    const clock = job.publishedAt ? publicationClock(job.publishedAt) : '';
    if (days === 0) return `${prefix} hoje${clock}`;
    if (days === 1) return `${prefix} ontem${clock}`;
    if (days > 1 && days < 7) return `${prefix} há ${days} dias`;
    return `${prefix} em ${dateFormatter.format(time)}`;
  }

  function decode(data) {
    const dictionaries = data.dict || {};
    const jobs = data.jobs || {};
    const get = (name, code) => (dictionaries[name] || [])[code] || '';
    const output = [];
    for (let index = 0; index < data.count; index += 1) {
      const source = get('source', jobs.src[index]);
      const contracts = String(jobs.ct[index] || '').split(' · ').filter(Boolean);
      const rawLocation = jobs.city[index] || '';
      const item = {
        title: jobs.title[index] || '',
        source,
        sourceLabel: sourceLabel(source),
        company: get('company', jobs.cmp[index]) || 'Empresa não informada',
        category: get('area', jobs.area[index]) || 'Outros',
        seniority: get('seniority', jobs.sen[index]) || 'Não informado',
        workplaceType: workplaceLabel(get('work_model', jobs.wm[index])),
        market: marketLabel(get('market', jobs.mk[index])),
        country: get('country', jobs.co[index]),
        location: rawLocation || get('country', jobs.co[index]) || 'Local não informado',
        cities: extractCityNames(rawLocation),
        publishedAt: jobs.pub[index] || '',
        lastSeenAt: jobs.seen[index] || '',
        expiresAt: jobs.exp[index] || '',
        url: jobs.url[index] || '',
        portals: Number(jobs.np[index] || 1),
        skills: jobs.sk[index] || '',
        salaryMin: jobs.smin[index],
        salaryMax: jobs.smax[index],
        currency: get('currency', jobs.cur[index]),
        pcd: Boolean(jobs.pcd[index]),
        blindSelection: Boolean(jobs.blind[index]),
        contractTypes: contracts
      };
      item._location = normalize(rawLocation);
      item._search = normalize([
        item.title, item.company, item.sourceLabel, item.category, item.seniority,
        item.workplaceType, item.market, item.location, item.skills,
        ...contracts, ...contracts.map(contractLabel)
      ].join(' '));
      output.push(item);
    }
    return output;
  }

  function appendOption(select, value, label) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    select.append(option);
  }

  function countValues(values) {
    const counts = new Map();
    for (const value of values.filter(Boolean)) counts.set(value, (counts.get(value) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || collator.compare(a[0], b[0]));
  }

  function countCities(jobs) {
    const cities = new Map();
    for (const job of jobs) {
      const seen = new Set();
      for (const city of job.cities) {
        const key = normalize(city);
        if (!key || seen.has(key)) continue;
        seen.add(key);
        const current = cities.get(key);
        if (!current) {
          cities.set(key, { label: city, count: 1 });
          continue;
        }
        current.count += 1;
        const currentAccents = (current.label.match(/[^\x00-\x7F]/g) || []).length;
        const candidateAccents = (city.match(/[^\x00-\x7F]/g) || []).length;
        if (candidateAccents > currentAccents) current.label = city;
      }
    }
    return [...cities.values()].sort((a, b) => collator.compare(a.label, b.label));
  }

  function populateFilters() {
    for (const [value, count] of countValues(state.jobs.map(job => job.source))) {
      appendOption(elements.sourceFilter, value, `${sourceLabel(value)} (${numberFormatter.format(count)})`);
    }
    for (const [value, count] of countValues(state.jobs.map(job => job.workplaceType))) {
      appendOption(elements.workplaceFilter, value, `${value} (${numberFormatter.format(count)})`);
    }
    for (const model of CONTRACT_MODELS) {
      const key = normalize(model.sourceValue);
      const count = state.jobs.filter(job => job.contractTypes.some(type => normalize(type) === key)).length;
      appendOption(elements.contractFilter, model.value, `${model.value} (${numberFormatter.format(count)})`);
    }
    for (const city of countCities(state.jobs)) {
      const option = document.createElement('option');
      option.value = city.label;
      option.label = `${numberFormatter.format(city.count)} ${city.count === 1 ? 'vaga' : 'vagas'}`;
      elements.cityOptions.append(option);
    }
    for (const [value, count] of countValues(state.jobs.map(job => job.market))) {
      appendOption(elements.marketFilter, value, `${value} (${numberFormatter.format(count)})`);
    }
    for (const [value, count] of countValues(state.jobs.map(job => job.category))) {
      appendOption(elements.categoryFilter, value, `${value} (${numberFormatter.format(count)})`);
    }
    for (const [value, count] of countValues(state.jobs.map(job => job.seniority))) {
      appendOption(elements.seniorityFilter, value, `${value} (${numberFormatter.format(count)})`);
    }
  }

  function loadParams() {
    const params = new URLSearchParams(window.location.search);
    elements.searchInput.value = params.get('q') || '';
    elements.sourceFilter.value = params.get('portal') || '';
    elements.workplaceFilter.value = params.get('modalidade') || '';
    const requestedContract = params.get('contratacao') || '';
    elements.contractFilter.value = normalize(requestedContract) === 'pj' ? 'CNPJ' : requestedContract;
    elements.cityFilter.value = params.get('cidade') || '';
    elements.marketFilter.value = params.get('mercado') || '';
    elements.categoryFilter.value = params.get('area') || '';
    elements.seniorityFilter.value = params.get('senioridade') || '';
    elements.periodFilter.value = params.get('dias') || '';
    elements.pcdOnly.checked = params.get('pcd') === '1';
    elements.duplicatesOnly.checked = params.get('duplicadas') === '1';
    elements.sortFilter.value = params.get('ordem') || 'recent';
    const requestedPage = Number(params.get('pagina'));
    state.page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  }

  function updateParams() {
    const params = new URLSearchParams();
    const mappings = [
      ['q', elements.searchInput.value.trim()],
      ['portal', elements.sourceFilter.value],
      ['modalidade', elements.workplaceFilter.value],
      ['contratacao', elements.contractFilter.value],
      ['cidade', elements.cityFilter.value.trim()],
      ['mercado', elements.marketFilter.value],
      ['area', elements.categoryFilter.value],
      ['senioridade', elements.seniorityFilter.value],
      ['dias', elements.periodFilter.value],
      ['ordem', elements.sortFilter.value === 'recent' ? '' : elements.sortFilter.value],
      ['pagina', state.page > 1 ? String(state.page) : '']
    ];
    for (const [key, value] of mappings) if (value) params.set(key, value);
    if (elements.pcdOnly.checked) params.set('pcd', '1');
    if (elements.duplicatesOnly.checked) params.set('duplicadas', '1');
    const query = params.toString();
    history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`);
  }

  function filterJobs() {
    const queryTokens = normalize(elements.searchInput.value).split(/\s+/).filter(Boolean);
    const source = elements.sourceFilter.value;
    const workplace = elements.workplaceFilter.value;
    const requestedContract = normalize(elements.contractFilter.value);
    const contract = requestedContract === 'cnpj' ? 'pj' : requestedContract;
    const city = normalize(elements.cityFilter.value);
    const market = elements.marketFilter.value;
    const category = elements.categoryFilter.value;
    const seniority = elements.seniorityFilter.value;
    const days = Number(elements.periodFilter.value);
    const threshold = days ? Date.now() - days * 86400000 : 0;

    state.filtered = state.jobs.filter(job => {
      if (queryTokens.length && !queryTokens.every(token => job._search.includes(token))) return false;
      if (source && job.source !== source) return false;
      if (workplace && job.workplaceType !== workplace) return false;
      if (contract && !job.contractTypes.some(type => normalize(type) === contract)) return false;
      if (city && !job._location.includes(city)) return false;
      if (market && job.market !== market) return false;
      if (category && job.category !== category) return false;
      if (seniority && job.seniority !== seniority) return false;
      if (threshold && activityTime(job) < threshold) return false;
      if (elements.pcdOnly.checked && !job.pcd) return false;
      if (elements.duplicatesOnly.checked && job.portals < 2) return false;
      return true;
    });

    const sort = elements.sortFilter.value;
    state.filtered.sort((a, b) => {
      if (sort === 'portals') return b.portals - a.portals || activityTime(b) - activityTime(a);
      if (sort === 'company') return collator.compare(a.company, b.company) || collator.compare(a.title, b.title);
      if (sort === 'title') return collator.compare(a.title, b.title) || collator.compare(a.company, b.company);
      return activityTime(b) - activityTime(a) || collator.compare(a.company, b.company);
    });
  }

  function tag(text, className = '') {
    const span = document.createElement('span');
    span.className = `tag ${className}`.trim();
    span.textContent = text;
    return span;
  }

  function workplaceClass(value) {
    if (value === 'Remoto') return 'tag-remote';
    if (value === 'Híbrido') return 'tag-hybrid';
    if (value === 'Presencial') return 'tag-onsite';
    return 'tag-unknown';
  }

  function formatSalary(job) {
    if (!job.salaryMin && !job.salaryMax) return '';
    const currency = job.currency || 'BRL';
    const formatter = new Intl.NumberFormat('pt-BR', {
      style: 'currency', currency, maximumFractionDigits: currency === 'BRL' ? 2 : 0
    });
    const low = job.salaryMin ? formatter.format(job.salaryMin) : '';
    const high = job.salaryMax ? formatter.format(job.salaryMax) : '';
    if (low && high) return `${low} a ${high}`;
    return low ? `A partir de ${low}` : `Até ${high}`;
  }

  function renderJob(job) {
    const article = document.createElement('article');
    article.className = 'job-card';
    const top = document.createElement('div');
    top.className = 'job-topline';
    const company = document.createElement('p');
    company.className = 'company-name';
    company.textContent = job.company;
    const date = document.createElement('span');
    date.className = 'job-date';
    date.textContent = activityLabel(job);
    top.append(company, date);

    const title = document.createElement('h3');
    title.textContent = job.title;
    const tags = document.createElement('div');
    tags.className = 'tags';
    tags.append(
      tag(job.sourceLabel, 'tag-source'),
      tag(job.workplaceType, workplaceClass(job.workplaceType)),
      tag(job.category),
      tag(job.seniority)
    );
    if (job.location && job.location !== 'Local não informado') tags.append(tag(job.location));
    for (const contract of job.contractTypes) tags.append(tag(contractLabel(contract)));
    if (job.pcd) tags.append(tag('Afirmativa PcD', 'tag-pcd'));
    if (job.blindSelection) tags.append(tag('Seleção às cegas', 'tag-pcd'));
    if (job.portals > 1) tags.append(tag(`Encontrada em ${job.portals} portais`, 'tag-source'));
    article.append(top, title, tags);

    const footer = document.createElement('div');
    footer.className = 'job-footer';
    const note = document.createElement('span');
    note.className = 'language-note';
    const salary = formatSalary(job);
    note.textContent = salary || job.skills || `${job.market}${job.country ? ` · ${job.country}` : ''}`;
    const link = document.createElement('a');
    link.className = 'primary-link';
    link.href = job.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Ver vaga original ↗';
    link.setAttribute('aria-label', `Ver vaga ${job.title} no portal ${job.sourceLabel}`);
    footer.append(note, link);
    article.append(footer);
    return article;
  }

  function render() {
    filterJobs();
    const totalPages = Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE));
    state.page = Math.min(Math.max(1, state.page), totalPages);
    const start = (state.page - 1) * PAGE_SIZE;
    const pageJobs = state.filtered.slice(start, start + PAGE_SIZE);
    elements.resultCount.textContent = numberFormatter.format(state.filtered.length);
    elements.jobList.replaceChildren(...pageJobs.map(renderJob));
    const empty = state.filtered.length === 0;
    elements.statusMessage.hidden = !empty;
    elements.statusMessage.textContent = empty
      ? 'Nenhuma vaga corresponde a esses filtros. Tente remover um ou mais critérios.'
      : '';
    elements.pagination.hidden = empty || totalPages <= 1;
    elements.previousPage.disabled = state.page <= 1;
    elements.nextPage.disabled = state.page >= totalPages;
    elements.pageLabel.textContent = `Página ${numberFormatter.format(state.page)} de ${numberFormatter.format(totalPages)}`;
    updateParams();
  }

  function resetFilters() {
    elements.filtersForm.reset();
    elements.sortFilter.value = 'recent';
    state.page = 1;
    render();
    elements.searchInput.focus();
  }

  function csvCell(value) {
    let text = Array.isArray(value) ? value.join(' | ') : String(value ?? '');
    if (/^[=+\-@]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  }

  function downloadCsv() {
    const headers = ['Cargo', 'Empresa', 'Portal', 'Área', 'Senioridade', 'Modalidade', 'Mercado', 'Local', 'Contrato', 'PcD', 'Seleção às cegas', 'Salário', 'Publicada em', 'Vista em', 'Link'];
    const rows = state.filtered.map(job => [
      job.title, job.company, job.sourceLabel, job.category, job.seniority,
      job.workplaceType, job.market, job.location, job.contractTypes, job.pcd ? 'Sim' : 'Não',
      job.blindSelection ? 'Sim' : 'Não', formatSalary(job), job.publishedAt,
      job.lastSeenAt, job.url
    ]);
    const csv = `\uFEFF${[headers, ...rows].map(row => row.map(csvCell).join(';')).join('\r\n')}`;
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `radar-vagas-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  let searchTimer;
  function scheduleRender() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.page = 1; render(); }, 180);
  }

  function bindEvents() {
    elements.searchInput.addEventListener('input', scheduleRender);
    elements.cityFilter.addEventListener('input', scheduleRender);
    elements.filtersForm.addEventListener('change', () => { state.page = 1; render(); });
    elements.sortFilter.addEventListener('change', () => { state.page = 1; render(); });
    elements.clearFilters.addEventListener('click', resetFilters);
    elements.downloadCsv.addEventListener('click', downloadCsv);
    elements.previousPage.addEventListener('click', () => {
      state.page -= 1;
      render();
      elements.resultsTitle.scrollIntoView({ block: 'start' });
    });
    elements.nextPage.addEventListener('click', () => {
      state.page += 1;
      render();
      elements.resultsTitle.scrollIntoView({ block: 'start' });
    });
  }

  async function init() {
    try {
      const response = await fetch(`./data/vagas.json?v=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('A base de vagas não respondeu.');
      const data = await response.json();
      if (data.schema_version !== 3 || !data.jobs || !Number.isInteger(data.count)) {
        throw new Error('O formato da base de vagas é inválido.');
      }
      state.meta = data;
      state.jobs = decode(data);
      elements.totalJobs.textContent = numberFormatter.format(data.count);
      elements.totalCompanies.textContent = numberFormatter.format(data.companies || new Set(state.jobs.map(job => job.company)).size);
      elements.totalSources.textContent = numberFormatter.format(new Set(state.jobs.map(job => job.source)).size);
      elements.updatedLabel.textContent = data.generated_at
        ? `Atualizado em ${dateTimeFormatter.format(new Date(data.generated_at))} (horário de Brasília)`
        : 'Data da última atualização não informada';
      if ((data.failed_sources || []).length) {
        elements.sourceWarning.hidden = false;
        elements.sourceWarning.textContent = `Alguns portais não responderam nesta atualização: ${data.failed_sources.map(sourceLabel).join(', ')}. Resultados vistos recentemente podem ser preservados por até ${data.fresh_days || 3} dias.`;
      }
      populateFilters();
      loadParams();
      bindEvents();
      elements.statusMessage.hidden = true;
      render();
    } catch (error) {
      elements.statusMessage.hidden = false;
      elements.statusMessage.textContent = 'Não foi possível carregar as vagas agora. Tente atualizar a página em alguns minutos.';
      elements.updatedLabel.textContent = 'A atualização não pôde ser confirmada';
      elements.downloadCsv.disabled = true;
      console.error(error);
    }
  }

  init();
})();
