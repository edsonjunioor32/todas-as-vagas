(() => {
  'use strict';

  const key = 'todas-as-vagas-theme';
  let stored = '';
  try {
    stored = localStorage.getItem(key) || '';
  } catch {
    // Storage may be unavailable in strict privacy modes.
  }

  const systemDark = window.matchMedia
    && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = stored === 'dark' || stored === 'light'
    ? stored
    : (systemDark ? 'dark' : 'light');
  document.documentElement.dataset.theme = theme;

  const RECENT_COMPANIES = [
    { name: 'CI&T', added: '21/08/2026' },
    { name: 'Nubank', added: '21/08/2026' },
    { name: 'Creditas', added: '21/08/2026' },
    { name: 'CloudWalk', added: '21/08/2026' }
  ];

  function toneClass(value) {
    let hash = 0;
    const text = String(value || '');
    for (let index = 0; index < text.length; index += 1) {
      hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0;
    }
    return `company-tone-${Math.abs(hash) % 8}`;
  }

  function initials(value) {
    const pieces = String(value || '')
      .replace(/[&.]/g, ' ')
      .split(/\s+/)
      .filter(Boolean);
    if (!pieces.length) return 'TV';
    if (pieces.length === 1) return pieces[0].slice(0, 2).toUpperCase();
    return `${pieces[0][0] || ''}${pieces[1][0] || ''}`.toUpperCase();
  }

  function searchCompany(company) {
    const search = document.querySelector('#searchInput');
    const results = document.querySelector('#resultados');
    if (!search) return;
    search.value = company;
    search.dispatchEvent(new Event('input', { bubbles: true }));
    if (results) results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function ensureRedesignStyles() {
    const styles = [
      ['redesign-2026', './redesign.css?v=1'],
      ['redesign-grid-2026', './redesign-grid.css?v=1']
    ];
    for (const [id, href] of styles) {
      if (document.querySelector(`link[data-redesign="${id}"]`)) continue;
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = href;
      link.dataset.redesign = id;
      document.head.append(link);
    }
  }

  function enhanceHeroTitle() {
    const title = document.querySelector('.hero h1');
    if (!title || title.querySelector('.hero-accent')) return;
    const phrase = 'em um só lugar.';
    const text = title.textContent || '';
    const index = text.indexOf(phrase);
    if (index < 0) return;
    const before = text.slice(0, index);
    const accent = document.createElement('span');
    accent.className = 'hero-accent';
    accent.textContent = phrase;
    title.replaceChildren(document.createTextNode(before), accent);
  }

  function renderRecentCompanies() {
    const filters = document.querySelector('.filters');
    if (!filters || filters.querySelector('.recent-companies')) return;

    const section = document.createElement('section');
    section.className = 'recent-companies';
    section.setAttribute('aria-labelledby', 'recentCompaniesTitle');

    const title = document.createElement('h3');
    title.id = 'recentCompaniesTitle';
    title.textContent = 'Empresas adicionadas recentemente';

    const list = document.createElement('ul');
    list.className = 'recent-company-list';

    for (const company of RECENT_COMPANIES) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.className = 'recent-company-item';
      button.type = 'button';
      button.title = `Filtrar vagas de ${company.name} · adicionada em ${company.added}`;
      button.addEventListener('click', () => searchCompany(company.name));

      const logo = document.createElement('span');
      logo.className = `recent-company-logo ${toneClass(company.name)}`;
      logo.setAttribute('aria-hidden', 'true');
      logo.textContent = initials(company.name);

      const name = document.createElement('span');
      name.className = 'recent-company-name';
      name.textContent = company.name;

      const badge = document.createElement('span');
      badge.className = 'new-badge';
      badge.textContent = 'Novo';

      button.append(logo, name, badge);
      item.append(button);
      list.append(item);
    }

    const footer = document.createElement('button');
    footer.className = 'recent-companies-footer';
    footer.type = 'button';
    footer.textContent = 'Ver todas as empresas →';
    footer.addEventListener('click', () => {
      const search = document.querySelector('#searchInput');
      if (search) {
        search.value = '';
        search.dispatchEvent(new Event('input', { bubbles: true }));
        search.focus();
      }
    });

    section.append(title, list, footer);

    const note = filters.querySelector('.filter-note');
    if (note) note.before(section);
    else filters.append(section);
  }

  function decorateJobCard(card) {
    if (!(card instanceof HTMLElement) || card.dataset.decorated === '1') return;
    const company = card.querySelector('.company-name');
    if (!company) return;

    const logo = document.createElement('span');
    logo.className = `company-monogram ${toneClass(company.textContent)}`;
    logo.setAttribute('aria-hidden', 'true');
    logo.textContent = initials(company.textContent);

    card.prepend(logo);
    card.dataset.decorated = '1';
  }

  function decorateJobCards(root = document) {
    root.querySelectorAll('.job-card').forEach(decorateJobCard);
  }

  function observeJobs() {
    const list = document.querySelector('#jobList');
    if (!list) return;
    decorateJobCards(list);

    const observer = new MutationObserver(() => decorateJobCards(list));
    observer.observe(list, { childList: true });
  }

  document.addEventListener('DOMContentLoaded', () => {
    ensureRedesignStyles();
    enhanceHeroTitle();
    renderRecentCompanies();
    observeJobs();
  }, { once: true });
})();
