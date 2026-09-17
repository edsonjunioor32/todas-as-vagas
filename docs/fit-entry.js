(() => {
  'use strict';

  const fitPath = './aderencia/';
  for (const link of document.querySelectorAll('[data-fit-entry]')) {
    if (!(link instanceof HTMLAnchorElement)) continue;
    const href = link.getAttribute('href') || '';
    if (!href.startsWith(fitPath)) link.setAttribute('href', fitPath);
  }
})();
