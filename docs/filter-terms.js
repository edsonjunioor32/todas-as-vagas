(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.TodasAsVagasFilterTerms = api;
  }
})(globalThis, function () {
  'use strict';

  function normalize(value) {
    return String(value || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .trim();
  }

  function parseExcludedTerms(value) {
    return [...new Set(String(value || '')
      .split(',')
      .map(normalize)
      .filter(Boolean))];
  }

  function matchesExcludedTerm(searchableText, terms) {
    if (!Array.isArray(terms) || terms.length === 0) return false;
    const normalizedText = normalize(searchableText);
    return Boolean(normalizedText && terms.some(term => normalizedText.includes(term)));
  }

  return Object.freeze({ parseExcludedTerms, matchesExcludedTerm });
});
