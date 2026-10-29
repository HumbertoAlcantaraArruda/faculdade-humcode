(() => {
  const csrf = document.currentScript.dataset.csrf;
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, options = {}) => {
    const target = new URL(typeof input === 'string' ? input : input.url, document.baseURI);
    if (target.origin === location.origin && (options.method || 'GET').toUpperCase() === 'POST') {
      const headers = new Headers(options.headers || {});
      headers.set('X-CSRF-Token', csrf);
      options = { ...options, headers };
    }
    return originalFetch(input, options);
  };
})();
