(() => {
  'use strict';
  let theme = 'dark';
  try { theme = window.localStorage.getItem('humcode.theme.v2') === 'light' ? 'light' : 'dark'; } catch (_) {}
  document.documentElement.dataset.theme = theme;
})();
