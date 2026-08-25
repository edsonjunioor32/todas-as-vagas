(() => {
  'use strict';

  const PAGE_SIZE = 24;
  const THEME_KEY = 'todas-as-vagas-theme';
  const themePreference = window.matchMedia('(prefers-color-scheme: dark)');
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
    ashby: 'Ashby',
    abler: 'Abler',
    accenture: 'Accenture',
    bradesco: 'Bradesco',
    cloudwalk: 'CloudWalk',
    dbccompany: 'DBC Company',
    digisystem: 'Digisystem',
    docusign: 'DocuSign',
    experian: 'Experian',
    fiserv: 'Fiserv',
    github: 'GitHub',
    infojobs: 'InfoJobs',
    inlog: 'Inlog',
    metalfrio: 'Metalfrio',
    nerdin: 'Nerdin',
    nestle: 'Nestlé',
    providerit: 'Provider IT',
    recrutei: 'Recrutei',
    revolut: 'Revolut',
    sankhya: 'Sankhya',
    senior: 'Senior',
    totvs: 'TOTVS',
    wise: 'Wise'
  };

  const state = {
    jobs: [],
    filtered: [],
    meta: null,
    fit: null,
    fitPromise: null,
    monitoredCompanies: [],
    page: 1,
    showingAllRecentCompanies: false,
    filtersCollapsed: false,
    initialized: false
  };
  const elements = {
    totalJobs: document.querySelector('#totalJobs'),
    totalCompanies: document.querySelector('#totalCompanies'),
    totalSources: document.querySelector('#totalSources'),
    updatedLabel: document.querySelector('#updatedLabel'),
    sourceWarning: document.querySelector('#sourceWarning'),
    themeToggle: document.querySelector('#themeToggle'),
    themeIcon: document.querySelector('#themeIcon'),
    themeLabel: document.querySelector('#themeLabel'),
    filtersForm: document.querySelector('#filtersForm'),
    filtersPanel: document.querySelector('.filters'),
    filtersContent: document.querySelector('#filtersContent'),
    filterToggle: document.querySelector('#filterToggle'),
    shareSearch: document.querySelector('#shareSearch'),
    activeFilters: document.querySelector('#activeFilters'),
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
    statusText: document.querySelector('#statusText'),
    retryLoad: document.querySelector('#retryLoad'),
    jobList: document.querySelector('#jobList'),
    pagination: document.querySelector('#pagination'),
    previousPage: document.querySelector('#previousPage'),
    nextPage: document.querySelector('#nextPage'),
    pageLabel: document.querySelector('#pageLabel'),
    resultsTitle: document.querySelector('#resultsTitle'),
    recentCompanies: document.querySelector('#recentCompanies'),
    recentCompaniesList: document.querySelector('#recentCompaniesList'),
    recentCompaniesMore: document.querySelector('#recentCompaniesMore'),
    monitoredCompanies: document.querySelector('#monitoredCompanies'),
    monitoredCompaniesList: document.querySelector('#monitoredCompaniesList')
  };

  function normalize(value) {
    return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  }

  function storedTheme() {
    try {
      const value = localStorage.getItem(THEME_KEY);
      return value === 'dark' || value === 'light' ? value : '';
    } catch {
      return '';
    }
  }

  function applyTheme(theme, persist = false) {
    const selected = theme === 'light' ? 'light' : 'dark';
    const dark = selected === 'dark';
    document.documentElement.dataset.theme = selected;
    if (elements.themeToggle) {
      elements.themeToggle.setAttribute('aria-pressed', String(dark));
      elements.themeToggle.setAttribute('aria-label', dark ? 'Ativar tema claro' : 'Ativar tema escuro');
    }
    if (elements.themeIcon) elements.themeIcon.textContent = dark ? '☾' : '☀';
    if (elements.themeLabel) elements.themeLabel.textContent = 'Mudar Tema';
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.content = dark ? '#061317' : '#ffffff';
    if (persist) {
      try {
        localStorage.setItem(THEME_KEY, selected);
      } catch {
        // ignore
      }
    }
  }

  function initTheme() {
    const initial = document.documentElement.dataset.theme || storedTheme() || 'dark';
    applyTheme(initial);
    if (elements.themeToggle) {
      elements.themeToggle.addEventListener('click', () => {
        applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark', true);
      });
    }
    const followSystem = event => {
      if (!storedTheme()) applyTheme(event.matches ? 'dark' : 'light');
    };
    if (typeof themePreference.addEventListener === 'function') {
      themePreference.addEventListener('change', followSystem);
    } else if (typeof themePreference.addListener === 'function') {
      themePreference.addListener(followSystem);
    }
  }

  function sourceLabel(value) {
    const raw = String(value || '').trim();
    return SOURCE_LABELS[raw] || SOURCE_LABELS[normalize(raw)] || raw || 'Portal não informado';
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

  function selectedLabel(value, formatter) {
    const raw = String(value || '').trim();
    return raw ? formatter(raw) : '';
  }

  function contractLabel(value) {
    return normalize(value) === 'pj' ? 'CNPJ' : String(value || '');
  }

  function normalizeUrl(value) {
    return String(value || '').trim().replace(/^http:\/\//i, 'https://');
  }

  function buildSearchText(job) {
    return normalize([
      job.title, job.company, job.sourceLabel, job.category, job.seniority,
      job.workplaceType, job.market, job.location, job.skills,
      ...(job.keywords || []), ...(job.contractTypes || []),
      ...(job.contractTypes || []).map(contractLabel)
    ].join(' '));
  }

  function isRecentlyPublished(value, days = 1) {
    const time = typeof value === 'number' ? value : toTime(value);
    return Boolean(time && Date.now() - time <= days * 86400000);
  }

  function extractCityNames(value) {
    const genericLocations = new Set(['anywhere', 'br', 'brasil', 'brazil', 'global', 'hybrid', 'hibrido', 'nao informada', 'presencial', 'remote', 'remoto', 'united states', 'usa', 'worldwide']);
    return String(value || '')
      .split(/\s+[·|;]\s+/)
      .map(part => part.trim())
      .filter(Boolean)
      .map(part => part.split(',')[0].trim().replace(/^(?:br|us|usa)\s*-\s*/i, ''))
      .filter(city => city && !genericLocations.has(normalize(city)));
  }

  function toTime(value) {
    if (!value) return 0;
    if (typeof value === 'number') return value;
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
    return ` às ${new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Fortaleza',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23'
    }).format(time)}`;
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
        url: normalizeUrl(jobs.url[index] || ''),
        portals: Number(jobs.np[index] || 1),
        skills: jobs.sk[index] || '',
        keywords: [],
        keywordGroups: { mandatory: [], preferred: [], context: [], manual: [] },
        fitConfidence: 0,
        salaryMin: jobs.smin[index],
        salaryMax: jobs.smax[index],
        currency: get('currency', jobs.cur[index]),
        pcd: Boolean(jobs.pcd[index]),
        blindSelection: Boolean(jobs.blind[index]),
        contractTypes: contracts
      };
      item._location = normalize(rawLocation);
      item._search = buildSearchText(item);
      output.push(item);
    }
    return output;
  }

  function decodeFitEntry(entry, terms) {
    if (!entry || !Array.isArray(terms)) return null;
    const read = key => (entry[key] || [])
      .map(index => terms[index])
      .filter(Boolean);
    const keywordGroups = {
      mandatory: read('m'),
      preferred: read('p'),
      context: read('c'),
      manual: read('x')
    };
    const keywords = [...new Set([
      ...keywordGroups.mandatory,
      ...keywordGroups.preferred,
      ...keywordGroups.context,
      ...keywordGroups.manual
    ])];
    return { keywordGroups, keywords, fitConfidence: Number(entry.q || 0) };
  }

  function attachFitData(payload) {
    const terms = Array.isArray(payload?.terms) ? payload.terms : [];
    const entries = payload?.jobs && typeof payload.jobs === 'object' ? payload.jobs : {};
    for (const job of state.jobs) {
      const fit = decodeFitEntry(entries[normalizeUrl(job.url)], terms);
      if (!fit) continue;
      Object.assign(job, fit);
      job._search = buildSearchText(job);
    }
    state.fit = payload;
  }

  function loadFitIndex() {
    if (state.fitPromise) return state.fitPromise;
    const version = encodeURIComponent(state.meta?.generated_at || state.meta?.generated_date || 'current');
    state.fitPromise = fetch(`./data/fit.json?v=${version}`, { cache: 'no-cache' })
      .then(response => {
        if (!response.ok) throw new Error('Índice de palavras-chave indisponível.');
        return response.json();
      })
      .then(payload => {
        if (payload.schema_version !== 1 || !Array.isArray(payload.terms) || !payload.jobs) {
          throw new Error('Formato do índice de palavras-chave inválido.');
        }
        attachFitData(payload);
        render();
        return payload;
      })
      .catch(error => {
        console.warn(error);
        state.fit = null;
        return null;
      });
    return state.fitPromise;
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
      }
    }
    return [...cities.values()].sort((a, b) => collator.compare(a.label, b.label));
  }

  function countContracts(jobs) {
    const counts = new Map();
    for (const job of jobs) {
      for (const value of job.contractTypes || []) {
        const raw = String(value || '').trim();
        if (!raw) continue;
        const key = normalize(raw === 'CNPJ' ? 'PJ' : raw);
        const current = counts.get(key) || { value: raw === 'CNPJ' ? 'PJ' : raw, count: 0 };
        current.count += 1;
        counts.set(key, current);
      }
    }
    return [...counts.values()].sort((a, b) => b.count - a.count || collator.compare(contractLabel(a.value), contractLabel(b.value)));
  }

  function populateFilters() {
    for (const [value, count] of countValues(state.jobs.map(job => job.source))) {
      if (['nao informado', 'portal nao informado'].includes(normalize(value))) continue;
      appendOption(elements.sourceFilter, value, `${sourceLabel(value)} (${numberFormatter.format(count)})`);
    }
    for (const [value, count] of countValues(state.jobs.map(job => job.workplaceType))) {
      appendOption(elements.workplaceFilter, value, `${value} (${numberFormatter.format(count)})`);
    }
    for (const contract of countContracts(state.jobs)) {
      appendOption(
        elements.contractFilter,
        contract.value,
        `${contractLabel(contract.value)} (${numberFormatter.format(contract.count)})`
      );
    }
    for (const city of countCities(state.jobs)) {
      const option = document.createElement('option');
      option.value = city.label;
      option.label = `${numberFormatter.format(city.count)} ${city.count === 1 ? 'vaga' : 'vagas'}`;
      elements.cityOptions.append(option);
    }
    for (const [value, count] of countValues(state.jobs.map(job => job.market))) {
      if (['nao informado', 'portal nao informado'].includes(normalize(value))) continue;
      appendOption(elements.marketFilter, value, `${marketLabel(value)} (${numberFormatter.format(count)})`);
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
    const values = {
      q: elements.searchInput.value.trim(),
      portal: elements.sourceFilter.value,
      modalidade: elements.workplaceFilter.value,
      contratacao: elements.contractFilter.value,
      cidade: elements.cityFilter.value.trim(),
      mercado: elements.marketFilter.value,
      area: elements.categoryFilter.value,
      senioridade: elements.seniorityFilter.value,
      dias: elements.periodFilter.value,
      pcd: elements.pcdOnly.checked ? '1' : '',
      duplicadas: elements.duplicatesOnly.checked ? '1' : '',
      ordem: elements.sortFilter.value !== 'recent' ? elements.sortFilter.value : '',
      pagina: state.page > 1 ? String(state.page) : ''
    };
    for (const [key, value] of Object.entries(values)) {
      if (value) params.set(key, value);
    }
    const url = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`;
    window.history.replaceState({}, '', url);
  }

  function activeFilterEntries() {
    const entries = [];
    const add = (key, label, value) => {
      if (value) entries.push({ key, label, value });
    };
    add('q', 'Busca', elements.searchInput.value.trim());
    add('cidade', 'Local', elements.cityFilter.value.trim());
    add('modalidade', 'Modalidade', elements.workplaceFilter.value);
    add('contratacao', 'Contrato', contractLabel(elements.contractFilter.value));
    add('area', 'Área', elements.categoryFilter.value);
    add('senioridade', 'Senioridade', elements.seniorityFilter.value);
    add('portal', 'Portal', selectedLabel(elements.sourceFilter.value, sourceLabel));
    add('mercado', 'Mercado', selectedLabel(elements.marketFilter.value, marketLabel));
    if (elements.periodFilter.value) {
      const labels = { '1': 'Últimas 24 horas', '7': 'Últimos 7 dias', '30': 'Últimos 30 dias' };
      add('dias', 'Publicação', labels[elements.periodFilter.value] || elements.periodFilter.value);
    }
    if (elements.pcdOnly.checked) add('pcd', 'Inclusão', 'PcD');
    if (elements.duplicatesOnly.checked) add('duplicadas', 'Duplicidade', 'Mais de um portal');
    return entries;
  }

  function renderActiveFilters() {
    if (!elements.activeFilters) return;
    const entries = activeFilterEntries();
    elements.activeFilters.replaceChildren(...entries.map(entry => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'filter-chip';
      button.dataset.filterKey = entry.key;
      button.setAttribute('aria-label', `Remover filtro ${entry.label}: ${entry.value}`);
      const label = document.createElement('span');
      label.textContent = `${entry.label}: ${entry.value}`;
      const close = document.createElement('span');
      close.className = 'filter-chip-close';
      close.setAttribute('aria-hidden', 'true');
      close.textContent = '×';
      button.append(label, close);
      return button;
    }));
    elements.activeFilters.hidden = entries.length === 0;
  }

  function clearFilter(key) {
    const fields = {
      q: elements.searchInput,
      cidade: elements.cityFilter,
      modalidade: elements.workplaceFilter,
      contratacao: elements.contractFilter,
      area: elements.categoryFilter,
      senioridade: elements.seniorityFilter,
      portal: elements.sourceFilter,
      mercado: elements.marketFilter,
      dias: elements.periodFilter
    };
    if (fields[key]) fields[key].value = '';
    if (key === 'pcd') elements.pcdOnly.checked = false;
    if (key === 'duplicadas') elements.duplicatesOnly.checked = false;
    state.page = 1;
    render();
  }

  function currentShareUrl() {
    updateParams();
    return window.location.href;
  }

  async function shareSearch() {
    const url = currentShareUrl();
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        copied = true;
      }
    } catch {
      copied = false;
    }
    if (!copied) {
      const helper = document.createElement('textarea');
      helper.value = url;
      helper.setAttribute('readonly', '');
      helper.style.position = 'fixed';
      helper.style.opacity = '0';
      document.body.append(helper);
      helper.select();
      try { copied = document.execCommand('copy'); } catch { copied = false; }
      helper.remove();
    }
    if (elements.shareSearch) {
      const previous = elements.shareSearch.textContent;
      elements.shareSearch.textContent = copied ? 'Link copiado!' : 'Copie o link da página';
      window.setTimeout(() => { elements.shareSearch.textContent = previous; }, 1800);
    }
  }

  function setFilterPanelCollapsed(collapsed) {
    state.filtersCollapsed = Boolean(collapsed);
    if (!elements.filtersPanel || !elements.filterToggle) return;
    elements.filtersPanel.classList.toggle('is-collapsed', state.filtersCollapsed);
    elements.filterToggle.setAttribute('aria-expanded', String(!state.filtersCollapsed));
    elements.filterToggle.textContent = state.filtersCollapsed ? 'Mostrar' : 'Ocultar';
  }

  function initFilterPanel() {
    if (!elements.filterToggle) return;
    const mobile = window.matchMedia('(max-width: 680px)').matches;
    setFilterPanelCollapsed(mobile);
    elements.filterToggle.addEventListener('click', () => setFilterPanelCollapsed(!state.filtersCollapsed));
  }

  function filterJobs() {
    const search = normalize(elements.searchInput.value);
    const source = elements.sourceFilter.value;
    const workplace = elements.workplaceFilter.value;
    const contract = elements.contractFilter.value;
    const city = normalize(elements.cityFilter.value);
    const market = elements.marketFilter.value;
    const category = elements.categoryFilter.value;
    const seniority = elements.seniorityFilter.value;
    const days = Number(elements.periodFilter.value || 60);
    const pcdOnly = elements.pcdOnly.checked;
    const duplicatesOnly = elements.duplicatesOnly.checked;
    const now = Date.now();

    state.filtered = state.jobs.filter(job => {
      if (search && !job._search.includes(search)) return false;
      if (source && job.source !== source) return false;
      if (workplace && job.workplaceType !== workplace) return false;
      if (contract) {
        const target = normalize(contract === 'CNPJ' ? 'PJ' : contract);
        if (!job.contractTypes.some(type => normalize(type) === target)) return false;
      }
      if (city) {
        const cityMatch = job.cities.some(item => normalize(item).includes(city)) || job._location.includes(city);
        if (!cityMatch) return false;
      }
      if (market && job.market !== market) return false;
      if (category && job.category !== category) return false;
      if (seniority && job.seniority !== seniority) return false;
      if (pcdOnly && !job.pcd) return false;
      if (duplicatesOnly && job.portals <= 1) return false;
      if (days) {
        const activity = activityTime(job);
        if (!activity || (now - activity) > days * 86400000) return false;
      }
      return true;
    });

    const sort = elements.sortFilter.value;
    state.filtered.sort((a, b) => {
      if (sort === 'company') return collator.compare(a.company, b.company) || activityTime(b) - activityTime(a);
      if (sort === 'title') return collator.compare(a.title, b.title) || activityTime(b) - activityTime(a);
      if (sort === 'portals') return (b.portals - a.portals) || activityTime(b) - activityTime(a);
      return activityTime(b) - activityTime(a) || collator.compare(a.title, b.title);
    });
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

  function shortTimeLabel(job) {
    const time = activityTime(job);
    if (!time) return 'Agora';
    const delta = Math.max(0, Date.now() - time);
    const hours = Math.floor(delta / 3600000);
    if (hours < 1) return 'Há pouco';
    if (hours < 24) return `Há ${hours} hora${hours > 1 ? 's' : ''}`;
    const days = Math.floor(delta / 86400000);
    if (days < 30) return `Há ${days} dia${days > 1 ? 's' : ''}`;
    return `Publicada em ${dateFormatter.format(time)}`;
  }

  function publicationLabel(job) {
    const value = job.publishedAt || job.lastSeenAt;
    const time = toTime(value);
    if (!time) return 'Data não informada';
    if (job.publishedAt) {
      return `Publicada em ${dateFormatter.format(time)}${publicationClock(value)}`;
    }
    return `Vista em ${dateFormatter.format(time)}`;
  }

  function keywordLabel(job) {
    return (job.keywords || []).filter(Boolean).slice(0, 3);
  }

  function initials(company) {
    const parts = String(company || '').split(/\s+/).filter(Boolean);
    return parts.slice(0, 2).map(part => part[0]).join('').toUpperCase() || 'TV';
  }

  function logoClass(company) {
    return `logo-${normalize(company).replace(/[^a-z0-9]+/g, '-')}`;
  }

  function logoText(company) {
    const name = normalize(company);
    if (name === 'ifood') return 'ifood';
    if (name === 'stone') return 'stone';
    if (name === 'nubank') return 'nu';
    if (name === 'c6 bank') return 'C6';
    if (name === 'xp inc.') return 'xp';
    if (name === 'rd station') return '◥◣';
    return initials(company);
  }

  function tag(text, variant = '') {
    const span = document.createElement('span');
    span.className = `tag${variant ? ` tag-${variant}` : ''}`;
    span.textContent = text;
    return span;
  }

  function workplaceVariant(value) {
    const normalized = normalize(value);
    if (normalized === 'remoto') return 'remote';
    if (normalized === 'hibrido') return 'hybrid';
    if (normalized === 'presencial') return 'on-site';
    return 'unknown';
  }

  function renderJob(job) {
    const article = document.createElement('article');
    article.className = 'job-card';

    const head = document.createElement('div');
    head.className = 'job-card-head';

    const logo = document.createElement('div');
    const normalizedLogo = logoClass(job.company).replace('logo-', '');
    const knownClass = ['ifood', 'stone', 'nubank', 'c6-bank', 'xp-inc', 'rd-station'].includes(normalizedLogo) ? logoClass(job.company) : 'logo-default';
    logo.className = `company-logo ${knownClass}`;
    const logoTextEl = document.createElement('span');
    logoTextEl.className = 'company-logo-text';
    logoTextEl.textContent = logoText(job.company);
    logo.append(logoTextEl);

    const body = document.createElement('div');

    const source = document.createElement('p');
    source.className = 'job-source';
    source.textContent = job.sourceLabel;

    const top = document.createElement('div');
    top.className = 'job-topline';
    const title = document.createElement('h3');
    title.textContent = job.title;
    const badge = document.createElement('span');
    badge.className = 'job-badge-new';
    badge.textContent = 'Novo';
    badge.hidden = !isRecentlyPublished(job.publishedAt, 1);
    top.append(title);
    if (!badge.hidden) top.append(badge);

    const company = document.createElement('p');
    company.className = 'company-name';
    company.textContent = job.company;

    const meta = document.createElement('div');
    meta.className = 'company-meta';
    const location = document.createElement('span');
    location.textContent = `⌖ ${job.location || 'Não informado'}`;
    const verified = document.createElement('span');
    verified.className = 'verified';
    verified.textContent = '✦';
    verified.setAttribute('aria-label', `Vaga direcionada ao mercado ${job.market || 'Brasil'}`);
    company.append(' ', verified);
    meta.append(location);
    if (job.market && job.market !== 'Não informado') {
      const market = document.createElement('span');
      market.textContent = `◉ ${job.market}`;
      meta.append(market);
    }

    const tags = document.createElement('div');
    tags.className = 'tags';
    // Keep the work model as the first, high-contrast tag. It is the quickest
    // way for a visitor to distinguish remote, hybrid and on-site jobs.
    tags.append(tag(job.workplaceType, `workplace ${workplaceVariant(job.workplaceType)}`));
    const tagsToShow = [];
    if (job.category && job.category !== 'Outros') tagsToShow.push(job.category);
    if (job.seniority && job.seniority !== 'Não informado') tagsToShow.push(job.seniority);
    if (job.contractTypes.length) tagsToShow.push(...job.contractTypes.slice(0, 2).map(contractLabel));
    tagsToShow.slice(0, 4).forEach(item => tags.append(tag(item)));
    for (const keyword of keywordLabel(job).slice(0, 2)) {
      tags.append(tag(keyword, 'keyword'));
    }

    body.append(source, top, company, meta, tags);
    head.append(logo, body);

    const footer = document.createElement('div');
    footer.className = 'job-footer';
    const date = document.createElement('span');
    date.className = 'job-date';
    date.textContent = publicationLabel(job);
    date.title = activityLabel(job);
    date.setAttribute('aria-label', publicationLabel(job));
    const link = document.createElement('a');
    link.className = 'primary-link';
    link.href = job.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Ver vaga original ↗';
    link.setAttribute('aria-label', `Ver vaga ${job.title} no portal ${job.sourceLabel}`);
    footer.append(date, link);

    article.append(head, footer);
    return article;
  }

  function recentCompaniesData() {
    const unique = new Map();
    const sorted = [...state.jobs].sort((a, b) => activityTime(b) - activityTime(a));
    for (const job of sorted) {
      const key = normalize(job.company);
      if (!key || unique.has(key)) continue;
      unique.set(key, { company: job.company, activity: activityTime(job) });
    }
    return [...unique.values()];
  }

  function renderRecentCompanies() {
    if (!elements.recentCompanies || !elements.recentCompaniesList) return;
    const all = recentCompaniesData();
    if (!all.length) {
      elements.recentCompanies.hidden = true;
      return;
    }
    const visible = state.showingAllRecentCompanies ? all.slice(0, 16) : all.slice(0, 6);
    elements.recentCompaniesList.replaceChildren(...visible.map((item, index) => {
      const li = document.createElement('li');
      li.className = 'recent-company-item';
      const logo = document.createElement('span');
      logo.className = `recent-company-logo company-tone-${index % 8}`;
      logo.textContent = initials(item.company);
      const name = document.createElement('button');
      name.type = 'button';
      name.className = 'recent-company-button';
      name.textContent = item.company;
      name.setAttribute('aria-label', `Filtrar vagas da empresa ${item.company}`);
      name.addEventListener('click', () => {
        elements.searchInput.value = item.company;
        state.page = 1;
        render();
        elements.searchInput.focus();
        elements.resultsTitle.scrollIntoView({ block: 'start' });
      });
      const badge = document.createElement('span');
      badge.className = 'new-badge';
      if (isRecentlyPublished(item.activity, 1)) badge.textContent = 'Novo';
      else badge.hidden = true;
      li.append(logo, name, badge);
      return li;
    }));
    elements.recentCompanies.hidden = false;
    if (elements.recentCompaniesMore) {
      elements.recentCompaniesMore.hidden = all.length <= 6;
      elements.recentCompaniesMore.textContent = state.showingAllRecentCompanies ? 'Mostrar menos' : 'Ver todas as empresas';
    }
  }

  function renderMonitoredCompanies() {
    if (!elements.monitoredCompanies || !elements.monitoredCompaniesList) return;
    const companies = state.monitoredCompanies || [];
    if (!companies.length) {
      elements.monitoredCompanies.hidden = true;
      return;
    }
    elements.monitoredCompaniesList.replaceChildren(...companies.map((item, index) => {
      const li = document.createElement('li');
      li.className = 'recent-company-item';
      const logo = document.createElement('span');
      logo.className = `recent-company-logo company-tone-${index % 8}`;
      logo.textContent = initials(item.company);
      const name = document.createElement('span');
      name.className = 'recent-company-name';
      name.textContent = item.company;
      const link = document.createElement('a');
      link.className = 'monitor-link';
      link.href = item.url || '#';
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'Board oficial ↗';
      link.setAttribute('aria-label', `Abrir o board oficial de ${item.company}`);
      li.append(logo, name, link);
      return li;
    }));
    elements.monitoredCompanies.hidden = false;
  }

  function setStatus(message, { hidden = false, retry = false, error = false } = {}) {
    if (!elements.statusMessage) return;
    elements.statusMessage.hidden = hidden;
    elements.statusMessage.classList.toggle('status-error', error);
    if (elements.statusText) elements.statusText.textContent = message;
    if (elements.retryLoad) elements.retryLoad.hidden = !retry;
  }

  function renderLoading() {
    if (!elements.jobList) return;
    const cards = Array.from({ length: 6 }, () => {
      const article = document.createElement('article');
      article.className = 'job-card skeleton-card';
      article.setAttribute('aria-hidden', 'true');
      article.innerHTML = '<span class="skeleton skeleton-logo"></span><span class="skeleton skeleton-line skeleton-line-long"></span><span class="skeleton skeleton-line"></span><span class="skeleton skeleton-tags"></span>';
      return article;
    });
    elements.jobList.replaceChildren(...cards);
    elements.jobList.setAttribute('aria-busy', 'true');
  }

  function render() {
    filterJobs();
    const totalPages = Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE));
    state.page = Math.min(Math.max(1, state.page), totalPages);
    const start = (state.page - 1) * PAGE_SIZE;
    const pageJobs = state.filtered.slice(start, start + PAGE_SIZE);
    elements.resultCount.textContent = numberFormatter.format(state.filtered.length);
    elements.jobList.replaceChildren(...pageJobs.map(renderJob));
    elements.jobList.setAttribute('aria-busy', 'false');
    const empty = state.filtered.length === 0;
    setStatus(
      empty ? 'Nenhuma vaga corresponde a esses filtros. Tente remover um ou mais critérios.' : '',
      { hidden: !empty }
    );
    elements.pagination.hidden = empty || totalPages <= 1;
    elements.previousPage.disabled = state.page <= 1;
    elements.nextPage.disabled = state.page >= totalPages;
    elements.pageLabel.textContent = `Página ${numberFormatter.format(state.page)} de ${numberFormatter.format(totalPages)}`;
    updateParams();
    renderActiveFilters();
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
    const headers = ['Cargo', 'Empresa', 'Portal', 'Área', 'Senioridade', 'Modalidade', 'Mercado', 'Local', 'Contrato', 'Palavras-chave', 'PcD', 'Seleção às cegas', 'Salário', 'Publicada em', 'Vista em', 'Link'];
    const rows = state.filtered.map(job => [
      job.title, job.company, job.sourceLabel, job.category, job.seniority,
      job.workplaceType, job.market, job.location, job.contractTypes, job.keywords,
      job.pcd ? 'Sim' : 'Não',
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
    elements.shareSearch?.addEventListener('click', shareSearch);
    elements.downloadCsv.addEventListener('click', downloadCsv);
    elements.retryLoad?.addEventListener('click', () => loadData(true));
    elements.activeFilters?.addEventListener('click', event => {
      const button = event.target.closest('[data-filter-key]');
      if (button) clearFilter(button.dataset.filterKey);
    });
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
    if (elements.recentCompaniesMore) {
      elements.recentCompaniesMore.addEventListener('click', () => {
        state.showingAllRecentCompanies = !state.showingAllRecentCompanies;
        renderRecentCompanies();
      });
    }
    initFilterPanel();
  }

  function resetFilterOptions() {
    const selects = [
      elements.sourceFilter, elements.workplaceFilter, elements.contractFilter,
      elements.marketFilter, elements.categoryFilter, elements.seniorityFilter
    ];
    for (const select of selects) {
      while (select.options.length > 1) select.remove(1);
    }
    elements.cityOptions.replaceChildren();
  }

  function scheduleFitLoad() {
    const start = () => loadFitIndex();
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(start, { timeout: 2500 });
    } else {
      window.setTimeout(start, 650);
    }
  }

  async function loadData(force = false) {
    renderLoading();
    setStatus('Carregando vagas…', { hidden: false });
    if (force) {
      state.fit = null;
      state.fitPromise = null;
    }
    try {
      const suffix = force ? `?retry=${Date.now()}` : '';
      const [response, watchlistResponse] = await Promise.all([
        fetch(`./data/vagas.json${suffix}`, { cache: force ? 'no-store' : 'no-cache' }),
        fetch(`./data/greenhouse-watchlist.json${suffix}`, { cache: force ? 'no-store' : 'no-cache' })
      ]);
      if (!response.ok) throw new Error('A base de vagas não respondeu.');
      const data = await response.json();
      if (data.schema_version !== 3 || !data.jobs || !Number.isInteger(data.count)) {
        throw new Error('O formato da base de vagas é inválido.');
      }
      state.meta = data;
      state.jobs = decode(data);
      resetFilterOptions();
      if (watchlistResponse.ok) {
        try {
          const watchlist = await watchlistResponse.json();
          state.monitoredCompanies = Array.isArray(watchlist.companies) ? watchlist.companies : [];
        } catch {
          state.monitoredCompanies = [];
        }
      }
      elements.totalJobs.textContent = numberFormatter.format(data.count);
      elements.totalCompanies.textContent = numberFormatter.format(data.companies || new Set(state.jobs.map(job => job.company)).size);
      elements.totalSources.textContent = numberFormatter.format(new Set(state.jobs.map(job => job.source)).size);
      elements.updatedLabel.textContent = data.generated_at
        ? `Atualizado em ${dateTimeFormatter.format(new Date(data.generated_at))}`
        : 'Data da última atualização não informada';
      if ((data.failed_sources || []).length) {
        elements.sourceWarning.hidden = false;
        elements.sourceWarning.textContent = `Alguns portais não responderam nesta atualização: ${data.failed_sources.map(sourceLabel).join(', ')}. Resultados vistos recentemente podem ser preservados por até ${data.fresh_days || 3} dias.`;
      } else {
        elements.sourceWarning.hidden = true;
      }
      populateFilters();
      loadParams();
      renderRecentCompanies();
      renderMonitoredCompanies();
      if (!state.initialized) {
        bindEvents();
        state.initialized = true;
      }
      elements.downloadCsv.disabled = false;
      setStatus('', { hidden: true });
      render();
      scheduleFitLoad();
    } catch (error) {
      elements.jobList.replaceChildren();
      elements.jobList.setAttribute('aria-busy', 'false');
      setStatus('Não foi possível carregar as vagas agora. Tente novamente em alguns instantes.', { retry: true, error: true });
      elements.updatedLabel.textContent = 'A atualização não pôde ser confirmada';
      elements.downloadCsv.disabled = true;
      console.error(error);
    }
  }

  async function init() {
    await loadData();
  }

  initTheme();
  init();
})();
