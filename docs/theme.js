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
})();
