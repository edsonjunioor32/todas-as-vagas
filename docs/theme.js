(() => {
  'use strict';

  // Start with the dark approved visual identity and preserve explicit choices.
  let selected = 'dark';
  try {
    const stored = localStorage.getItem('todas-as-vagas-theme');
    if (stored === 'dark' || stored === 'light') selected = stored;
  } catch {
    // Restricted browser storage must not prevent the page from rendering.
  }
  document.documentElement.dataset.theme = selected;
})();
