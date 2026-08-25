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

  const state = {
    jobs: [],
    filtered: [],
    meta: null,
    monitoredCompanies: [],
    page: 1,
    showingAllRecentCompanies: false
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
    return `Em ${dateFormatter.format(time)}`;
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
    top.append(title, badge);

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

    const tags = document.createElement('div');
    tags.className = 'tags';
    // Keep the work model as the first, high-contrast tag. It is the quickest
    // way for a visitor to distinguish remote, hybrid and on-site jobs.
    tags.append(tag(job.workplaceType, `workplace ${workplaceVariant(job.workplaceType)}`));
    const tagsToShow = [];
    if (job.category && job.category !== 'Outros') tagsToShow.push(job.category);
    if (job.seniority && job.seniority !== 'Não informado') tagsToShow.push(job.seniority);
    if (job.contractTypes[0]) tagsToShow.push(contractLabel(job.contractTypes[0]));
    tagsToShow.slice(0, 3).forEach(item => tags.append(tag(item)));

    body.append(source, top, company, meta, tags);
    head.append(logo, body);

    const footer = document.createElement('div');
    footer.className = 'job-footer';
    const date = document.createElement('span');
    date.className = 'job-date';
    date.textContent = shortTimeLabel(job);
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
      const name = document.createElement('span');
      name.className = 'recent-company-name';
      name.textContent = item.company;
      const badge = document.createElement('span');
      badge.className = 'new-badge';
      badge.textContent = 'Novo';
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
    elements.statusMessage.textContent = empty ? 'Nenhuma vaga corresponde a esses filtros. Tente remover um ou mais critérios.' : '';
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
    if (elements.recentCompaniesMore) {
      elements.recentCompaniesMore.addEventListener('click', () => {
        state.showingAllRecentCompanies = !state.showingAllRecentCompanies;
        renderRecentCompanies();
      });
    }
  }

  async function init() {
    try {
      const [response, watchlistResponse] = await Promise.all([
        fetch(`./data/vagas.json?v=${Date.now()}`, { cache: 'no-store' }),
        fetch(`./data/greenhouse-watchlist.json?v=${Date.now()}`, { cache: 'no-store' })
      ]);
      if (!response.ok) throw new Error('A base de vagas não respondeu.');
      const data = await response.json();
      if (data.schema_version !== 3 || !data.jobs || !Number.isInteger(data.count)) {
        throw new Error('O formato da base de vagas é inválido.');
      }
      state.meta = data;
      state.jobs = decode(data);
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
      }
      populateFilters();
      loadParams();
      renderRecentCompanies();
      renderMonitoredCompanies();
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

  initTheme();
  init();
})();
