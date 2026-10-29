(() => {
  'use strict';
  const basePath = document.documentElement.dataset.basePath || '';
  const portalRoute = target => {
    if (target.origin !== location.origin || !target.pathname.startsWith(`${basePath}/`)) return null;
    const path = target.pathname.slice(basePath.length).replace(/\/$/, '') || '/';
    if (path === '/index.php') return target.searchParams.get('route') || 'home';
    if (path === '/' || path === '/biblioteca') return 'home';
    if (/^\/materias\/\d+$/.test(path)) return 'subject';
    if (/^\/pastas\/\d+$/.test(path)) return 'folder';
    if (path === '/materiais/sem-materia') return 'unassigned';
    if (path === '/entrar') return 'login';
    return null;
  };
  const jq = window.jQuery;
  let nextSelectId = 0;
  const initSelects = (scope = document) => {
    if (!jq?.fn.select2) return;
    scope.querySelectorAll('select').forEach(select => {
      if (select.classList.contains('select2-hidden-accessible')) return;
      if (!select.id) select.id = `humcode-select-${++nextSelectId}`;
      const label = select.getAttribute('aria-label') || [...(select.closest('label')?.childNodes || [])]
        .filter(node => node.nodeType === Node.TEXT_NODE).map(node => node.textContent).join(' ').trim() || 'Selecionar opção';
      jq(select).select2({
        theme: 'humcode', width: '100%', language: 'pt-BR',
        dropdownParent: jq(select.closest('dialog') || document.body),
        minimumResultsForSearch: 0,
        maximumSelectionLength: Number(select.dataset.maxSelections) || 0
      }).on('change.humcodeSelects', event => {
        // Select2 emits a jQuery event; the rest of the portal uses DOM events.
        if (!event.originalEvent) select.dispatchEvent(new Event('change', {bubbles: true}));
        select.nextElementSibling?.querySelector('[role="combobox"]')?.removeAttribute('aria-invalid');
      }).on('select2:open.humcodeSelects', () => {
        const parent = select.closest('dialog') || document.body;
        const search = parent.querySelector('.select2-container--open .select2-search__field');
        if (search) {
          search.setAttribute('aria-label', `Buscar em ${label.toLocaleLowerCase('pt-BR')}`);
          search.placeholder = 'Digite para buscar…';
          search.focus();
        }
      });
      const control = select.nextElementSibling.querySelector('[role="combobox"]');
      control.removeAttribute('aria-labelledby');
      control.setAttribute('aria-label', label);
      if (select.required) control.setAttribute('aria-required', 'true');
    });
  };
  const destroySelects = scope => {
    if (!jq?.fn.select2) return;
    scope.querySelectorAll('select.select2-hidden-accessible').forEach(select => {
      jq(select).off('.humcodeSelects').select2('destroy');
    });
  };
  const folderChoices = new WeakMap();
  const updateFolderChoices = (form, selected = '') => {
    const select = form.querySelector('[data-folder-select]');
    const subject = form.querySelector('select[name="subject_id"]');
    if (!select || !subject) return;
    if (!folderChoices.has(select)) folderChoices.set(select, [...select.options].map(option => option.cloneNode(true)));
    const choices = folderChoices.get(select).filter(option => !option.value || option.dataset.subject === subject.value);
    select.replaceChildren(...choices.map(option => option.cloneNode(true)));
    select.value = choices.some(option => option.value === selected) ? selected : '';
    if (jq?.fn.select2) jq(select).trigger('change.select2');
  };
  document.querySelectorAll('form').forEach(form => {
    const select = form.querySelector('[data-folder-select]');
    if (select) updateFolderChoices(form, select.value);
  });
  document.addEventListener('change', event => {
    if (event.target.matches('select[name="subject_id"]')) updateFolderChoices(event.target.form);
  });
  initSelects();
  const initEventForms = scope => scope.querySelectorAll('[data-event-form]').forEach(eventForm => {
    const updateEventTimes = () => {
      const timed = eventForm.elements.all_day.value === '0';
      eventForm.querySelector('[data-event-times]').hidden = !timed;
      ['starts_at', 'ends_at'].forEach(name => {
        eventForm.elements[name].disabled = !timed;
        eventForm.elements[name].required = timed;
      });
    };
    eventForm.elements.all_day.addEventListener('change', updateEventTimes);
    updateEventTimes();
  });
  initEventForms(document);
  document.addEventListener('click', event => {
    document.querySelectorAll('[data-notification-menu][open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('[data-notification-menu][open]').forEach(menu => {
      menu.open = false;
      menu.querySelector('summary').focus();
    });
  });
  document.querySelectorAll('dialog').forEach(dialog => {
    dialog.addEventListener('close', () => {
      if (!jq?.fn.select2) return;
      dialog.querySelectorAll('select.select2-hidden-accessible').forEach(select => jq(select).select2('close'));
    });
  });
  document.addEventListener('invalid', event => {
    const select = event.target;
    if (!select.matches('select.select2-hidden-accessible')) return;
    event.preventDefault();
    select.nextElementSibling.querySelector('[role="combobox"]').setAttribute('aria-invalid', 'true');
    jq(select).select2('open');
  }, true);
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-open]');
    if (button) {
      const dialog = document.getElementById(button.dataset.open);
      if (dialog) dialog.showModal();
    }
    const close = event.target.closest('[data-close]');
    if (close) close.closest('dialog')?.close();
  });
  document.addEventListener('click', event => {
    const dialog = event.target.closest('dialog');
    if (dialog) {
      if (event.target === dialog) {
        const rect = dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
      }
    }
  });
  const menuToggle = document.querySelector('[data-sidebar-toggle]');
  if (menuToggle) {
    const sidebar = document.getElementById('sidebar');
    const mobileMenu = window.matchMedia('(max-width: 760px)');
    const preferenceKey = 'humcode.sidebar.collapsed';
    let desktopCollapsed = false;
    try { desktopCollapsed = window.localStorage.getItem(preferenceKey) === 'true'; } catch (_) {}
    const updateMenu = () => {
      const open = mobileMenu.matches ? document.body.classList.contains('sidebar-open') : !desktopCollapsed;
      document.body.classList.toggle('sidebar-collapsed', !mobileMenu.matches && desktopCollapsed);
      menuToggle.setAttribute('aria-expanded', String(open));
      const label = open ? 'Recolher menu' : 'Abrir menu';
      menuToggle.setAttribute('aria-label', label);
      menuToggle.setAttribute('title', label);
      sidebar.inert = !open;
      sidebar.setAttribute('aria-hidden', String(!open));
    };
    const closeMenu = () => {
      document.body.classList.remove('sidebar-open');
      updateMenu();
    };
    const saveDesktopPreference = () => {
      try { window.localStorage.setItem(preferenceKey, String(desktopCollapsed)); } catch (_) {}
    };
    menuToggle.addEventListener('click', () => {
      if (mobileMenu.matches) {
        document.body.classList.toggle('sidebar-open');
      } else {
        desktopCollapsed = !desktopCollapsed;
        saveDesktopPreference();
      }
      updateMenu();
    });
    const expandDesktopMenu = () => {
      desktopCollapsed = false;
      saveDesktopPreference();
      updateMenu();
      menuToggle.focus();
    };
    document.querySelector('[data-rail-menu]')?.addEventListener('click', expandDesktopMenu);
    document.querySelector('.nav-rail')?.addEventListener('click', event => {
      if (mobileMenu.matches || !desktopCollapsed || event.target.closest('a, button')) return;
      expandDesktopMenu();
    });
    document.querySelectorAll('[data-sidebar-close]').forEach(button => button.addEventListener('click', () => {
      closeMenu();
      menuToggle.focus();
    }));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && mobileMenu.matches && document.body.classList.contains('sidebar-open')) {
        closeMenu();
        menuToggle.focus();
      }
    });
    mobileMenu.addEventListener('change', closeMenu);
    const collapseMenu = () => {
      if (menuToggle.getAttribute('aria-expanded') !== 'true') return;
      if (!mobileMenu.matches) {
        desktopCollapsed = true;
        saveDesktopPreference();
      }
      if (sidebar.contains(document.activeElement)) menuToggle.focus();
      closeMenu();
    };
    document.addEventListener('click', event => {
      if (!sidebar.contains(event.target) && !menuToggle.contains(event.target) && !event.target.closest('.nav-rail')) collapseMenu();
    });
    window.addEventListener('blur', () => {
      window.setTimeout(() => {
        if (document.activeElement instanceof HTMLIFrameElement) collapseMenu();
      }, 0);
    });
    updateMenu();
    requestAnimationFrame(() => requestAnimationFrame(() => document.documentElement.classList.add('motion-ready')));
  }
  const themeToggle = document.querySelector('[data-theme-toggle]');
  if (themeToggle) {
    const updateThemeToggle = () => {
      const dark = document.documentElement.dataset.theme === 'dark';
      const label = dark ? 'Ativar tema claro' : 'Ativar tema escuro';
      themeToggle.setAttribute('aria-label', label);
      themeToggle.setAttribute('title', label);
      themeToggle.setAttribute('aria-pressed', String(dark));
    };
    themeToggle.addEventListener('click', () => {
      const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = theme;
      try { window.localStorage.setItem('humcode.theme.v2', theme); } catch (_) {}
      updateThemeToggle();
    });
    updateThemeToggle();
  }
  const userToggle = document.querySelector('[data-user-toggle]');
  const userMenu = document.querySelector('[data-user-menu]');
  if (userToggle && userMenu) {
    const closeUserMenu = () => {
      userMenu.hidden = true;
      userMenu.inert = true;
      userToggle.setAttribute('aria-expanded', 'false');
    };
    userToggle.addEventListener('click', () => {
      userMenu.hidden = !userMenu.hidden;
      userMenu.inert = userMenu.hidden;
      userToggle.setAttribute('aria-expanded', String(!userMenu.hidden));
    });
    document.addEventListener('click', event => {
      if (!userMenu.contains(event.target) && !userToggle.contains(event.target)) closeUserMenu();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !userMenu.hidden) {
        closeUserMenu();
        userToggle.focus();
      }
    });
    document.querySelector('.header-user').addEventListener('focusout', event => {
      if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) closeUserMenu();
    });
  }
  document.querySelectorAll('[data-toggle-password]').forEach(button => {
    button.addEventListener('click', () => {
      const input = button.closest('.password-field').querySelector('input');
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.setAttribute('aria-label', show ? 'Ocultar senha' : 'Mostrar senha');
      button.setAttribute('aria-pressed', String(show));
    });
  });
  document.addEventListener('change', event => {
    const input = event.target.closest?.('[data-auto-submit]');
    if (!input || !input.files.length || !input.form) return;
    const max = Number(input.dataset.maxFiles || 0), maxBytes = Number(input.dataset.maxBytes || 0);
    let problem = '';
    if (input.dataset.maxFiles !== undefined && input.files.length > max) problem = `Cada anotação aceita até ${input.dataset.totalFiles} arquivos. Escolha no máximo ${max} novo(s).`;
    if (!problem && maxBytes && [...input.files].some(file => file.size > maxBytes)) problem = `Cada arquivo deve ter no máximo ${Math.round(maxBytes / 1048576)} MB.`;
    if (problem) {
      input.value = '';
      if (window.Swal) window.Swal.fire({ icon: 'error', title: 'Não foi possível adicionar', text: problem, target: input.closest('dialog') || 'body', buttonsStyling: false, confirmButtonText: 'Ok', customClass: { confirmButton: 'button button-primary' } });
      else window.alert(problem);
      return;
    }
    input.form.submit();
  });
  document.addEventListener('click', event => {
    const button = event.target.closest?.('[data-swal-confirm]');
    if (!button) return;
    event.preventDefault();
    const form = button.form;
    const title = button.dataset.swalTitle || 'Deseja realmente remover?';
    if (!window.Swal) { if (window.confirm(title)) form.submit(); return; }
    window.Swal.fire({
      title, text: 'Essa ação não pode ser desfeita', icon: 'warning',
      target: button.closest('dialog') || 'body',
      showCancelButton: true, reverseButtons: true, focusCancel: true, buttonsStyling: false,
      confirmButtonText: 'Sim', cancelButtonText: 'Não',
      customClass: { confirmButton: 'button button-primary', cancelButton: 'button button-secondary' }
    }).then(result => {
      if (!result.isConfirmed) return;
      form.querySelectorAll('[data-swal-enable]').forEach(field => { field.disabled = false; });
      form.submit();
    });
  });
  document.querySelectorAll('[data-confirm]').forEach(button => {
    button.addEventListener('click', event => { if (!window.confirm(button.dataset.confirm)) event.preventDefault(); });
  });
  document.querySelectorAll('[data-upload-form]').forEach(form => {
    const input = form.querySelector('input[type="file"]');
    const zone = form.querySelector('[data-dropzone]');
    const list = form.querySelector('[data-selected-files]');
    const error = form.querySelector('[data-upload-error]');
    const maxSize = Number(form.dataset.maxBytes);
    const maxFiles = Number(form.dataset.maxFiles);
    const maxTotal = Number(form.dataset.maxTotalBytes);
    const expected = form.querySelector('[data-upload-count]');
    const update = () => {
      list.replaceChildren();
      error.textContent = '';
      input.setCustomValidity('');
      const files = Array.from(input.files);
      expected.value = String(files.length);
      if (files.length > maxFiles) error.textContent = `Selecione até ${maxFiles} arquivos por vez.`;
      if (files.reduce((total, file) => total + file.size, 0) > maxTotal) error.textContent = 'O lote excede o limite total. Envie menos arquivos por vez.';
      files.forEach(file => {
        const item = document.createElement('li');
        const name = document.createElement('span');
        name.textContent = file.name;
        const size = document.createElement('small');
        size.textContent = file.size < 1048576 ? `${Math.ceil(file.size / 1024)} KB` : `${(file.size / 1048576).toFixed(1)} MB`;
        item.append(name, size);
        list.append(item);
        if (file.size > maxSize) error.textContent = `“${file.name}” excede o limite por arquivo.`;
        if (!file.size) error.textContent = `“${file.name}” está vazio.`;
      });
      if (error.textContent) input.setCustomValidity(error.textContent);
    };
    input.addEventListener('change', update);
    ['dragenter', 'dragover'].forEach(type => zone.addEventListener(type, event => {
      event.preventDefault(); zone.classList.add('dragover');
    }));
    ['dragleave', 'drop'].forEach(type => zone.addEventListener(type, event => {
      event.preventDefault(); zone.classList.remove('dragover');
    }));
    zone.addEventListener('drop', event => {
      if (event.dataTransfer.files.length) {
        input.files = event.dataTransfer.files;
        update();
      }
    });
    form.addEventListener('submit', event => {
      update();
      if (!form.checkValidity()) { event.preventDefault(); form.reportValidity(); return; }
      if (!window.XMLHttpRequest) return;
      event.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      button.querySelector('span').textContent = 'Enviando…';
      form.setAttribute('aria-busy', 'true');
      const progress = form.querySelector('[data-upload-progress]');
      const bar = progress.querySelector('progress');
      const status = progress.querySelector('p');
      progress.hidden = false;
      bar.value = 0;
      const request = new XMLHttpRequest();
      request.open('POST', form.action);
      request.upload.addEventListener('progress', upload => {
        if (upload.lengthComputable) {
          bar.value = Math.round(upload.loaded / upload.total * 100);
          status.textContent = bar.value === 100 ? 'Envio concluído. Salvando os materiais…' : `Enviando arquivos: ${bar.value}%`;
        }
      });
      const recover = message => {
        button.disabled = false;
        button.querySelector('span').textContent = 'Enviar materiais';
        form.removeAttribute('aria-busy');
        progress.hidden = true;
        error.textContent = message;
      };
      request.addEventListener('load', () => {
        const responseURL = new URL(request.responseURL || form.action, location.href);
        if (request.status >= 200 && request.status < 300 && ['subject', 'folder', 'unassigned'].includes(portalRoute(responseURL))) {
          location.assign(responseURL.href);
          return;
        }
        if (portalRoute(responseURL) === 'login') { location.assign(responseURL.href); return; }
        const response = new DOMParser().parseFromString(request.responseText, 'text/html');
        recover(response.querySelector('.error-card p, .notice-error')?.textContent || 'Não foi possível concluir o envio. Confira os arquivos e tente novamente.');
      });
      request.addEventListener('error', () => recover('A conexão foi interrompida. Confira a biblioteca antes de enviar novamente.'));
      request.send(new FormData(form));
    });
  });
  document.querySelectorAll('input[data-new-password]').forEach(input => {
    const validate = () => {
      const bytes = new TextEncoder().encode(input.value).length;
      input.setCustomValidity(bytes > 72 ? 'A senha excede 72 bytes. Acentos e símbolos podem ocupar mais de um byte.' : '');
    };
    input.addEventListener('input', validate);
    input.addEventListener('change', validate);
  });

  // Library navigation keeps normal links and forms as a fallback.
  let navigationRequest;
  let previewRequest;
  let searchTimer;
  let activePreviewLink;
  let previewScroll = 0;
  const modifiedClick = event => event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
  const libraryURL = form => {
    const target = new URL(form.action, location.href);
    target.search = new URLSearchParams(new FormData(form)).toString();
    target.searchParams.delete('page');
    for (const [key, value] of [...target.searchParams]) {
      if (value === '' || (key === 'sort' && value === 'recent')) target.searchParams.delete(key);
    }
    return target;
  };
  const setLibraryStatus = (message, failed = false) => {
    const node = document.querySelector('[data-library-status]');
    if (node) {
      node.textContent = message;
      node.classList.toggle('sr-only', !failed);
    }
  };
  // keepSelector: elemento que fica na mesma posição da tela (e recebe o foco) após a troca, sem voltar ao topo.
  const navigateLibrary = async (target, historyMode = 'push', focusResults = false, keepSelector = '') => {
    if (!document.querySelector('[data-library-page]')) { location.assign(target.href); return; }
    navigationRequest?.abort();
    previewRequest?.abort();
    navigationRequest = new AbortController();
    const request = navigationRequest;
    const page = document.querySelector('[data-library-page]');
    page.setAttribute('aria-busy', 'true');
    setLibraryStatus('Buscando materiais…');
    try {
      const response = await fetch(target, {signal: request.signal});
      const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (request.signal.aborted) return;
      const nextPage = parsed.querySelector('[data-library-page]');
      if (!response.ok || !nextPage) { location.assign(response.url || target.href); return; }
      const currentInput = document.activeElement;
      const restoreSearch = currentInput?.matches('[data-library-filter] input[name="q"]');
      const selection = restoreSearch ? [currentInput.selectionStart, currentInput.selectionEnd] : null;
      const keptTop = keepSelector ? document.querySelector(keepSelector)?.getBoundingClientRect().top : undefined;
      destroySelects(page);
      page.replaceWith(document.importNode(nextPage, true));
      initSelects(document.querySelector('[data-library-page]'));
      for (const selector of ['.subject-nav', '.sidebar-heading', '[data-notification-menu]']) {
        const existing = document.querySelector(selector);
        const next = parsed.querySelector(selector);
        if (existing && next) existing.replaceWith(document.importNode(next, true));
      }
      const nextFilter = document.querySelector('[data-library-filter]');
      const uploadSubject = document.querySelector('#upload-dialog select[name="subject_id"]');
      if (uploadSubject) {
        uploadSubject.value = nextFilter?.dataset.subjectId ?? '';
        updateFolderChoices(uploadSubject.form, nextFilter?.dataset.folderId ?? '');
        const kind = uploadSubject.form.elements.kind;
        kind.value = nextFilter?.dataset.kind ?? 'material';
        if (jq?.fn.select2) jq(kind).trigger('change.select2');
      }
      if (uploadSubject && jq?.fn.select2) jq(uploadSubject).trigger('change.select2');
      document.title = parsed.title;
      const topHeading = document.querySelector('.topbar-heading > span:last-child');
      if (topHeading) topHeading.textContent = parsed.querySelector('.topbar-heading > span:last-child')?.textContent || 'Biblioteca';
      document.querySelector('.main-nav .nav-link')?.classList.toggle('active', portalRoute(target) === 'home');
      if (historyMode !== 'none') history[historyMode === 'replace' ? 'replaceState' : 'pushState']({}, '', target);
      setLibraryStatus(`${parsed.querySelector('.library-summary > span')?.textContent.trim() || 'Biblioteca atualizada'}.`);
      const kept = keepSelector ? document.querySelector(keepSelector) : null;
      if (kept && keptTop !== undefined) {
        window.scrollBy(0, kept.getBoundingClientRect().top - keptTop);
        (kept.querySelector('[aria-current="page"]') || kept).focus({preventScroll: true});
      } else if (restoreSearch && nextFilter) {
        nextFilter.elements.q.focus({preventScroll: true});
        nextFilter.elements.q.setSelectionRange(...selection);
      } else if (focusResults) {
        const heading = document.querySelector('.library-heading h1');
        heading.setAttribute('tabindex', '-1');
        heading.focus({preventScroll: true});
        window.scrollTo(0, 0);
      }
    } catch (error) {
      if (error.name !== 'AbortError') setLibraryStatus('Não foi possível atualizar a lista. Tente buscar novamente.', true);
    } finally {
      if (navigationRequest === request) document.querySelector('[data-library-page]')?.removeAttribute('aria-busy');
    }
  };
  document.addEventListener('submit', event => {
    const form = event.target;
    if (form.matches('[data-library-filter]') && document.querySelector('[data-library-page]')) {
      event.preventDefault();
      clearTimeout(searchTimer);
      navigateLibrary(libraryURL(form));
    }
  });
  document.addEventListener('input', event => {
    if (!event.target.matches('[data-library-filter] input[name="q"]')) return;
    clearTimeout(searchTimer);
    // A newer query must immediately invalidate any older response.
    navigationRequest?.abort();
    searchTimer = setTimeout(() => navigateLibrary(libraryURL(event.target.form), 'replace'), 300);
  });
  document.addEventListener('change', event => {
    const select = event.target;
    if (!select.matches('[data-library-filter] select')) return;
    clearTimeout(searchTimer);
    const target = libraryURL(select.form);
    if (select.matches('[data-subject-filter]')) {
      const subject = new URL(select.value, location.href);
      target.pathname = subject.pathname;
    }
    navigateLibrary(target);
  });
  const closePreview = (restoreFocus = true) => {
    previewRequest?.abort();
    const panel = document.querySelector('[data-library-preview]');
    if (!panel) return;
    panel.hidden = true;
    panel.querySelector('[data-preview-content]').replaceChildren();
    document.querySelector('.library-layout')?.classList.remove('has-preview');
    document.querySelectorAll('[data-material-row]').forEach(row => row.classList.remove('selected'));
    if (restoreFocus && activePreviewLink?.isConnected) {
      activePreviewLink.focus({preventScroll: true});
      window.scrollTo(0, previewScroll);
      activePreviewLink = null;
    }
  };
  document.addEventListener('click', async event => {
    if (event.target.closest('[data-preview-close]')) { closePreview(); return; }
    const link = event.target.closest('a');
    if (!link || modifiedClick(event)) return;
    if (link.matches('[data-library-link], .subject-nav a, .main-nav a') && document.querySelector('[data-library-page]') && ['home', 'subject', 'folder', 'unassigned'].includes(portalRoute(new URL(link.href)))) {
      event.preventDefault();
      clearTimeout(searchTimer);
      const inTabs = link.closest('.category-tabs');
      navigateLibrary(new URL(link.href), 'push', !inTabs, inTabs ? '.category-tabs' : '');
      return;
    }
    if (!link.matches('[data-preview]')) return;
    try { sessionStorage.setItem('humcode.library.return', JSON.stringify({url: location.href, scroll: window.scrollY})); } catch (_) {}
    if (window.matchMedia('(max-width: 1000px)').matches) return;
    event.preventDefault();
    previewRequest?.abort();
    previewRequest = new AbortController();
    const request = previewRequest;
    const panel = document.querySelector('[data-library-preview]');
    const content = panel.querySelector('[data-preview-content]');
    activePreviewLink = link;
    previewScroll = window.scrollY;
    panel.hidden = false;
    panel.setAttribute('aria-busy', 'true');
    document.querySelector('.library-layout').classList.add('has-preview');
    document.querySelectorAll('[data-material-row]').forEach(row => row.classList.toggle('selected', row === link.closest('tr')));
    const pending = document.createElement('p');
    pending.className = 'preview-loading';
    pending.textContent = 'Abrindo material…';
    content.replaceChildren(pending);
    try {
      const response = await fetch(link.href, {signal: request.signal});
      const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (request.signal.aborted) return;
      const reading = parsed.querySelector('[data-reading-content]');
      if (!response.ok || !reading) { location.assign(response.url || link.href); return; }
      reading.querySelector('.back-link')?.remove();
      reading.querySelector('.material-toolbar')?.remove();
      reading.querySelector('.viewer-heading p')?.remove();
      reading.querySelector('.heading-actions a[target="_blank"]')?.remove();
      const expand = reading.querySelector('[data-reading-expand]');
      const full = document.createElement('a');
      full.className = 'button button-secondary';
      full.href = link.href;
      full.textContent = 'Abrir leitura';
      expand?.replaceWith(full);
      const title = reading.querySelector('h1');
      const heading = document.createElement('h2');
      heading.textContent = title.textContent;
      title.replaceWith(heading);
      content.replaceChildren(document.importNode(reading, true));
      panel.scrollIntoView({block: 'start'});
      panel.querySelector('[data-preview-close]').focus({preventScroll: true});
    } catch (error) {
      if (error.name !== 'AbortError') {
        pending.textContent = 'Não foi possível abrir a prévia. ';
        const fallback = document.createElement('a');
        fallback.href = link.href;
        fallback.className = 'text-link';
        fallback.textContent = 'Abrir material';
        pending.append(fallback);
      }
    } finally { if (previewRequest === request) panel.removeAttribute('aria-busy'); }
  });
  window.addEventListener('popstate', () => {
    if (document.querySelector('[data-library-page]')) {
      clearTimeout(searchTimer);
      navigateLibrary(new URL(location.href), 'none');
    }
  });
  window.matchMedia('(max-width: 1000px)').addEventListener('change', event => { if (event.matches) closePreview(false); });
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-reading-expand]');
    if (button) {
      const expanded = document.body.classList.toggle('reading-expanded');
      button.setAttribute('aria-pressed', String(expanded));
      button.textContent = expanded ? 'Recolher leitura' : 'Expandir leitura';
    }
    document.querySelectorAll('.material-menu[open]').forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (document.querySelector('dialog[open]')) return;
    closePreview();
    if (document.body.classList.contains('reading-expanded')) document.querySelector('[data-reading-expand]')?.click();
    document.querySelectorAll('.material-menu[open]').forEach(menu => menu.open = false);
  });
  if (location.hash === '#delete-material-dialog') document.getElementById('delete-material-dialog')?.showModal();
  try {
    const saved = JSON.parse(sessionStorage.getItem('humcode.library.return') || 'null');
    const back = document.querySelector('[data-reading-back]');
    if (back && saved) {
      const target = new URL(saved.url, location.href);
      if (target.origin === location.origin && ['home', 'subject', 'folder', 'unassigned'].includes(portalRoute(target))) {
        back.href = target.href;
        back.textContent = 'Voltar à biblioteca';
      }
    }
    if (document.querySelector('[data-library-page]') && saved?.url === location.href) {
      requestAnimationFrame(() => window.scrollTo(0, Number(saved.scroll) || 0));
      sessionStorage.removeItem('humcode.library.return');
    }
  } catch (_) {}
  const initRecurrence = scope => scope.querySelectorAll('[data-recurrence-fields]').forEach(fields => {
    const select = fields.querySelector('[data-recurrence-select]');
    const options = fields.querySelector('[data-recurrence-options]');
    const weekdays = fields.querySelector('[data-recurrence-weekdays]');
    const eventSelect = fields.closest('form').querySelector('[name="event_id"]');
    const dateInput = fields.closest('form').querySelector('[name="event_date"]');
    let pickedDays = false;
    weekdays.addEventListener('change', () => { pickedDays = true; });
    dateInput?.addEventListener('change', () => {
      if (pickedDays || !/^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)) return;
      const day = new Date(dateInput.value + 'T12:00:00Z').getUTCDay();
      weekdays.querySelectorAll('input').forEach(input => { input.checked = Number(input.value) === day; });
    });
    const update = () => {
      const followsEvent = eventSelect?.selectedOptions[0]?.dataset.recurring === '1';
      fields.hidden = followsEvent;
      fields.querySelectorAll('input, select').forEach(input => { input.disabled = followsEvent; });
      options.hidden = select.value === 'none';
      weekdays.hidden = select.value !== 'weekly';
      fields.querySelector('[name="recurrence_interval"]').max = select.value === 'monthly' ? '12' : '52';
    };
    select.addEventListener('change', update);
    eventSelect?.addEventListener('change', update);
    update();
  });
  initRecurrence(document);
  window.humcodeInit = { selects: initSelects, destroySelects, eventForms: initEventForms, recurrence: initRecurrence };
})();

// Vídeo aulas: o player do YouTube só é criado ao abrir e é removido ao fechar, o que interrompe o vídeo.
(() => {
  document.addEventListener('click', event => {
    const link = event.target.closest('[data-video-open]');
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const dialog = document.getElementById('video-dialog');
    const frame = dialog?.querySelector('[data-video-frame]');
    if (!frame || !/^[A-Za-z0-9_-]{11}$/.test(link.dataset.videoId || '')) return;
    event.preventDefault();
    const player = document.createElement('iframe');
    player.src = `https://www.youtube-nocookie.com/embed/${link.dataset.videoId}?rel=0&autoplay=1`;
    player.title = link.dataset.videoTitle || 'Vídeo aula';
    player.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
    player.referrerPolicy = 'strict-origin-when-cross-origin';
    frame.replaceChildren(player);
    dialog.querySelector('[data-video-heading]').textContent = link.dataset.videoTitle || 'Vídeo aula';
    dialog.querySelector('[data-video-watch]').href = link.href;
    dialog.showModal();
  });
  document.addEventListener('close', event => {
    if (event.target.id === 'video-dialog') event.target.querySelector('[data-video-frame]')?.replaceChildren();
  }, true);
})();
(() => {
  // O navegador troca a seleção a cada clique no campo de arquivos; aqui os arquivos escolhidos se acumulam
  // numa lista, com o mesmo limite, formatos e tamanho do servidor, que repete a validação.
  const box = document.querySelector('[data-note-files]');
  if (!box) return;
  const input = box.querySelector('[data-note-attachments]');
  const message = box.querySelector('[data-note-files-error]');
  const list = box.querySelector('[data-note-selected]');
  const template = box.querySelector('[data-note-selected-item]');
  const max = Number(box.dataset.maxFiles);
  const maxBytes = Number(box.dataset.maxBytes);
  const allowed = ['pdf', 'png', 'jpg', 'jpeg', 'docx', 'html'];
  const existing = Number(input.dataset.existing || 0);
  let selected = [];
  const size = bytes => bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
  const show = text => { message.textContent = text; message.hidden = !text; };
  const sync = () => {
    const transfer = new DataTransfer();
    selected.forEach(file => transfer.items.add(file));
    input.files = transfer.files;
  };
  const render = () => {
    list.replaceChildren(...selected.map((file, index) => {
      const item = template.content.firstElementChild.cloneNode(true);
      const extension = file.name.split('.').pop().toLowerCase();
      item.querySelector('[data-selected-ext]').className = `file-badge ext-${extension}`;
      item.querySelector('[data-selected-ext]').textContent = extension.toUpperCase();
      item.querySelector('[data-selected-name]').textContent = file.name;
      item.querySelector('[data-selected-size]').textContent = size(file.size);
      item.querySelector('[data-selected-label]').textContent = `Remover arquivo ${file.name}`;
      item.querySelector('[data-selected-remove]').addEventListener('click', () => {
        selected = selected.filter((_, position) => position !== index);
        sync(); render(); show('');
      });
      return item;
    }));
    list.hidden = !selected.length;
  };
  input.addEventListener('change', () => {
    let text = '';
    for (const file of [...input.files]) {
      const extension = file.name.split('.').pop().toLowerCase();
      if (!allowed.includes(extension)) { text = 'Anexe apenas PDF, PNG, JPEG, JPG, DOCX ou HTML.'; continue; }
      if (file.size > maxBytes) { text = `Cada arquivo deve ter no máximo ${Math.round(maxBytes / 1048576)} MB.`; continue; }
      if (selected.some(item => item.name === file.name && item.size === file.size)) continue;
      if (existing + selected.length >= max) { text = `Cada anotação aceita até ${max} arquivos.`; continue; }
      selected.push(file);
    }
    sync(); render(); show(text);
  });
})();
(() => {
  // Anotações, convites, eventos e tarefas abrem num modal: o conteúdo vem da própria rota de detalhe, que
  // devolve só o fragmento quando pedida com ?modal=1 ou com o cabeçalho X-Detail-Modal. Sem JavaScript, ou se a
  // busca falhar, o link segue para a página normal.
  const dialog = document.getElementById('detail-dialog');
  if (!dialog) return;
  const content = dialog.querySelector('[data-detail-content]');
  const commitment = /(?:^|\/)agenda\/(?:novo|tarefas\/nova|(?:eventos|tarefas)\/\d+(?:\/editar)?)\/?$/;
  let changed = false;
  const show = html => {
    window.humcodeInit?.destroySelects(content);
    content.innerHTML = html;
    // O detalhe pode abrir sobre a página do mesmo item; o diálogo de exclusão ganha outro id para não colidir com o da página.
    content.querySelectorAll('dialog[id]').forEach(inner => {
      const id = inner.id;
      if (document.querySelectorAll(`[id="${id}"]`).length < 2) return;
      inner.id = `${id}-modal`;
      content.querySelectorAll(`[data-open="${id}"]`).forEach(trigger => { trigger.dataset.open = inner.id; });
    });
    content.querySelectorAll('input[data-return-path], input[name="return"][value="modal"]').forEach(field => { field.value = location.pathname + location.search; });
    if (!dialog.open) dialog.showModal();
    const init = window.humcodeInit;
    if (init) { init.selects(content); init.eventForms(content); init.recurrence(content); }
    // Ao trocar o conteúdo com o modal aberto o foco volta para o corpo da página; devolve-o ao modal.
    content.querySelector('button, a[href], input, select, textarea')?.focus({ preventScroll: true });
  };
  const fail = text => {
    if (window.Swal) window.Swal.fire({ icon: 'error', title: 'Não foi possível continuar', text, target: dialog, buttonsStyling: false, confirmButtonText: 'Ok', customClass: { confirmButton: 'button button-primary' } });
    else window.alert(text);
  };
  const open = async url => {
    const target = new URL(url, location.href);
    target.searchParams.set('modal', '1');
    let html = '';
    try {
      const response = await fetch(target, { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch', 'X-Detail-Modal': '1' } });
      html = response.ok ? await response.text() : '';
    } catch (error) { html = ''; }
    if (!html.includes('data-detail-fragment')) { location.href = url; return; }
    show(html);
  };
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target === '_blank' || link.hasAttribute('download')) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !(link.hasAttribute('data-detail-link') || commitment.test(url.pathname))) return;
    event.preventDefault();
    open(link.href);
  });
  // Formulários de evento e tarefa enviam por fetch: o resultado (detalhe, erro ou outra página) substitui o conteúdo do modal.
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !dialog.contains(form) || !form.closest('[data-detail-forms]')) return;
    if (form.method.toLowerCase() !== 'post') return;
    event.preventDefault();
    const buttons = [...form.querySelectorAll('button[type=submit], button:not([type])')];
    buttons.forEach(button => { button.disabled = true; });
    try {
      const response = await fetch(form.action, { method: 'POST', body: new FormData(form, event.submitter), credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch', 'X-Detail-Modal': '1' }, redirect: 'follow' });
      const html = await response.text();
      if (html.includes('data-detail-fragment')) { changed = true; show(html); return; }
      if (response.ok) { changed = false; dialog.close(); location.href = response.url; return; }
      const message = new DOMParser().parseFromString(html, 'text/html').querySelector('.error-card p')?.textContent?.trim();
      fail(message || 'Confira os dados e tente novamente.');
    } catch (error) {
      fail('Não foi possível enviar. Verifique a conexão e tente novamente.');
    } finally {
      buttons.forEach(button => { button.disabled = false; });
    }
  });
  dialog.addEventListener('close', () => {
    content.replaceChildren();
    if (changed) { changed = false; location.reload(); }
  });
  const reopen = /^#abrir-(nota|convite)-(\d+)$/.exec(location.hash);
  if (reopen) {
    history.replaceState(null, '', location.pathname + location.search);
    open(`${document.documentElement.dataset.basePath || ''}/${reopen[1] === 'nota' ? 'anotacoes' : 'convites'}/${reopen[2]}`);
  }
})();
(() => {
  // Lista de anotações: dados remotos paginados (12 por página) e cada linha desenhada como card.
  const start = () => {
    const host = document.querySelector('[data-notes-table]');
    if (!host || !window.Tabulator) return;
    const star = '<svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/></svg>';
    const text = (tag, className, value) => {
      const node = document.createElement(tag);
      node.className = className;
      node.textContent = value;
      return node;
    };
    const card = cell => {
      const note = cell.getData();
      const root = document.createElement('article');
      root.className = 'note-card' + (note.important ? ' is-important' : '');
      root.dataset.noteRow = note.id;
      if (note.important) {
        const badge = text('span', 'note-important-badge', 'Importante');
        badge.dataset.noteImportant = '';
        badge.insertAdjacentHTML('afterbegin', star);
        root.append(badge);
      }
      const heading = text('h3', 'note-card-title', '');
      const link = text('a', '', note.title);
      link.href = note.url;
      link.dataset.detailLink = '';
      link.dataset.detailKey = `abrir-nota-${note.id}`;
      heading.append(link);
      root.append(heading, text('p', 'note-card-meta', `${note.subject} - ${note.date}`), text('p', 'note-card-excerpt', note.excerpt));
      return root;
    };
    const size = Number(host.dataset.size) || 12;
    // Troca de página sem salto: a lista esvazia por um instante e o navegador levaria a rolagem ao topo.
    let keptY = null;
    const hold = () => { keptY = window.scrollY; host.style.minHeight = host.offsetHeight + 'px'; };
    const release = () => {
      host.style.minHeight = '';
      if (keptY !== null) window.scrollTo(0, keptY);
      keptY = null;
    };
    host.addEventListener('click', event => { if (event.target.closest('.tabulator-page:not(:disabled)')) hold(); }, true);
    const table = new Tabulator(host, {
      ajaxURL: host.dataset.url,
      ajaxParams: { subject_id: host.dataset.subject || '' },
      ajaxConfig: { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } },
      pagination: true,
      paginationMode: 'remote',
      paginationSize: size,
      paginationButtonCount: 5,
      dataLoader: false,
      renderVertical: 'basic',
      layout: 'fitColumns',
      headerVisible: false,
      selectableRows: false,
      placeholder: 'Nenhuma anotação encontrada.',
      locale: 'pt-br',
      langs: { 'pt-br': { pagination: { first: '«', first_title: 'Primeira página', prev: '‹', prev_title: 'Página anterior', next: '›', next_title: 'Próxima página', last: '»', last_title: 'Última página', page_title: 'Mostrar a página' } } },
      columns: [{ title: 'Anotação', field: 'title', formatter: card, headerSort: false, resizable: false }]
    });
    table.on('dataProcessed', release);
    table.on('dataLoadError', release);
  };
  // Os scripts adiados (inclusive o Tabulator, no corpo da página) rodam antes de DOMContentLoaded.
  if (document.readyState === 'complete') start(); else document.addEventListener('DOMContentLoaded', start);
})();
