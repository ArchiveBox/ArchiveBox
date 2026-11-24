(() => {
  function setBadgeCounter(row, total, visible) {
    const expanded = row.pills.classList.contains('library-tags-expanded');
    const label = row.pills.dataset.badgeLabel || 'tags';
    row.toggle.hidden = expanded ? total === 0 : total <= visible;
    const text = expanded ? `Show fewer ${label}` : `+${total - visible}`;
    if (row.toggle.textContent !== text) row.toggle.textContent = text;
    row.toggle.setAttribute('aria-label', expanded ? `Show fewer ${label}` : `Show all ${total} ${label}`);
    row.toggle.setAttribute('aria-expanded', String(expanded));
  }
  function updateCompactBadges(row) {
    const pills = row.pills.querySelectorAll('.tag-pill');
    if (pills.length <= 2) row.pills.classList.remove('library-tags-expanded');
    pills.forEach(pill => {if (pill.hidden) pill.hidden = false;});
    setBadgeCounter(row, pills.length, 2);
  }
  function bindBadgeToggle(row, update) {
    const toggle = document.createElement('button');
    toggle.type = 'button'; toggle.className = 'library-tags-toggle';
    row.pills.after(toggle);
    row.toggle = toggle;
    toggle.addEventListener('pointerdown', event => event.preventDefault());
    toggle.addEventListener('click', event => {
      event.stopPropagation();
      if (row.editor.contains(document.activeElement) && document.activeElement !== toggle) document.activeElement.blur();
      row.pills.classList.toggle('library-tags-expanded');
      update();
    });
  }

  // Compact cards retain their two-pill cap. The native table fits actual
  // one-line pill widths to the shared Title + Tags space.
  const cleanupTagRows = [];
  let refreshSearchTags;
  let initializedForm;
  function initializeTags(form, added) {
    if (form === initializedForm) {
      if (added) refreshSearchTags?.(added);
      return;
    }
    initializedForm = form;
    cleanupTagRows.splice(0).forEach(cleanup => cleanup());
    const table = form?.querySelector('#result_list');
    const header = table?.tHead;
    const title = header?.querySelector('.column-title_str');
    const tags = header?.querySelector('.column-tags_inline');
    const label = tags?.querySelector('.text span, .text a');
    const labelRange = document.createRange();
    if (label) labelRange.selectNodeContents(label);
    const rows = [];
    let counterWidths = [];
    let frame = 0;

    function spacing(element, properties) {
      const css = getComputedStyle(element);
      return properties.reduce((sum, name) => sum + (parseFloat(css[name]) || 0), 0);
    }
    function fitTableTags() {
      frame = 0;
      const dirty = rows.filter(row => !row.measure);
      // Install all temporary measurement styles and probes before the first
      // geometry read, so the header and natural pills share one layout.
      const probes = dirty.length && title && tags ? prepareTagMeasurement(dirty) : [];
      if (!header?.getBoundingClientRect().height || !title || !tags) {
        clearTagMeasurement(probes);
        table?.classList.remove('library-tag-fit');
        table?.style.removeProperty('--library-tags-width');
        rows.forEach(updateCompactBadges);
        return;
      }
      const cap = Math.floor((title.getBoundingClientRect().width + tags.getBoundingClientRect().width) * 0.4);
      const headerDemand = label ? labelRange.getBoundingClientRect().width +
        spacing(label, ['paddingLeft', 'paddingRight']) + spacing(tags, ['paddingLeft', 'paddingRight']) : 0;
      if (dirty.length) {
        measureTags(dirty, probes);
        clearTagMeasurement(probes);
      }
      table.classList.add('library-tag-fit');
      const demand = Math.max(headerDemand, ...rows.map(row => row.measure.full));
      const width = Math.min(Math.ceil(demand), cap);
      const columnWidth = `${width}px`;
      if (table.style.getPropertyValue('--library-tags-width') !== columnWidth) {
        table.style.setProperty('--library-tags-width', columnWidth);
      }
      for (const row of rows) {
        const {widths, pillGap, editorGap, fixed, full} = row.measure;
        let visible = widths.length;
        if (full > width) {
          let used = fixed;
          // Keep a readable first label, even when its full text alone is wider
          // than the column. The flex item ellipsizes and +N counts only siblings.
          visible = Math.min(widths.length, 1);
          for (let i = 0; i < widths.length - 1; i++) {
            used += widths[i] + (i ? pillGap : 0);
            const hidden = widths.length - i - 1;
            const counter = counterWidths[String(hidden).length - 1] + editorGap;
            if (used + counter <= width) visible = i + 1;
          }
        }
        const showAll = row.pills.classList.contains('library-tags-expanded') ||
          row.editor.contains(document.activeElement) &&
          document.activeElement.matches('input, .tag-remove-btn');
        row.tags.forEach((pill, i) => {
          const hidden = !showAll && i >= visible;
          if (pill.hidden !== hidden) pill.hidden = hidden;
        });
        setBadgeCounter(row, widths.length, showAll ? widths.length : visible);
      }
    }
    function prepareTagMeasurement(dirty) {
      table.classList.add('library-tag-fit', 'library-tag-measuring');
      for (const row of dirty) row.tags = Array.from(row.pills.querySelectorAll('.tag-pill'));
      // A shared probe per digit count measures the exact +N width. Reserving
      // +10 can hide a chip that fits beside +9.
      const maxDigits = Math.max(...dirty.map(row => String(row.tags.length).length));
      const probes = [];
      for (let digits = counterWidths.length + 1; digits <= maxDigits; digits++) {
        const probe = dirty[0].toggle.cloneNode(false);
        probe.hidden = false;
        probe.textContent = `+${'1'.repeat(digits)}`;
        probes.push(probe);
      }
      if (probes.length) dirty[0].toggle.after(...probes);
      return probes;
    }
    function measureTags(dirty, probes) {
      for (const probe of probes) counterWidths.push(probe.getBoundingClientRect().width);
      for (const row of dirty) {
        const widths = row.tags.map(pill => pill.getBoundingClientRect().width);
        const pillGap = spacing(row.pills, ['columnGap']);
        const editorGap = spacing(row.editor, ['columnGap']);
        const fixed = spacing(row.cell, ['paddingLeft', 'paddingRight']) +
          spacing(row.editor, ['paddingLeft', 'paddingRight']) +
          (row.input ? spacing(row.input, ['minWidth']) + editorGap : 0);
        const full = widths.reduce((total, width, i) => total + width + (i ? pillGap : 0), fixed);
        row.measure = {widths, pillGap, editorGap, fixed, full};
      }
    }
    function clearTagMeasurement(probes) {
      probes.forEach(probe => probe.remove());
      table?.classList.remove('library-tag-measuring');
    }
    function scheduleFit() {
      if (!frame) frame = requestAnimationFrame(fitTableTags);
    }
    const bindings = new Map();
    function bindPills(pills) {
      const editor = pills.closest('.tag-editor-inline');
      const cell = pills.closest('td.field-tags_inline');
      const inTable = cell && cell.closest('table') === table;
      const row = {pills, editor, cell, input: editor.querySelector('.tag-inline-input-sm')};
      if (inTable) rows.push(row);
      const update = () => inTable ? scheduleFit() : updateCompactBadges(row);
      bindBadgeToggle(row, update);
      const observer = new MutationObserver(() => {
        row.measure = null;
        update();
      });
      observer.observe(pills, {childList: true});
      if (inTable) {
        editor.addEventListener('focusin', update);
        editor.addEventListener('focusout', update);
      }
      bindings.set(pills, () => observer.disconnect());
      updateCompactBadges(row);
    }
    form?.querySelectorAll('.tag-pills-inline').forEach(bindPills);
    cleanupTagRows.push(() => bindings.forEach(disconnect => disconnect()));
    refreshSearchTags = added => {
      for (const [pills, disconnect] of bindings) {
        if (!pills.isConnected) {
          disconnect();
          bindings.delete(pills);
        }
      }
      for (let i = rows.length - 1; i >= 0; i--) {
        if (!rows[i].pills.isConnected) rows.splice(i, 1);
      }
      for (const row of added) row.querySelectorAll('.tag-pills-inline').forEach(bindPills);
      if (table && rows.length) scheduleFit();
    };
    if (table) {
      let lastWidth;
      const observer = new ResizeObserver(([entry]) => {
        const width = entry.contentRect.width;
        if (width !== lastWidth) {
          lastWidth = width;
          scheduleFit();
        }
      });
      observer.observe(table.parentElement);
      window.addEventListener('resize', scheduleFit);
      cleanupTagRows.push(() => {
        observer.disconnect();
        window.removeEventListener('resize', scheduleFit);
        cancelAnimationFrame(frame);
      });
      fitTableTags();
    }
  }

  const sidebars = new WeakMap();
  function initializeSidebar(sidebar) {
    if (!sidebar) return;
    const existing = sidebars.get(sidebar);
    if (existing) return existing;

    const library = sidebar.closest('.snapshot-library');
    const toggle = sidebar.querySelector('.folder-mobile-toggle');
    const viewport = matchMedia('(max-width: 767px)');
    const mode = sidebar.dataset.mode || 'folders';
    const folderName = sidebar.querySelector('.folder-row:has([aria-current="page"])')?.dataset.folderName ||
      sidebar.querySelector('.library-entry [aria-current=page]')?.textContent.trim() ||
      sidebar.querySelector('.library-root-link').textContent;
    const modeDestinationKey = 'archivebox.sidebar-mode-destination';
    const state = {viewport, desktopHidden: false, mobileCollapsed: true, apply};
    try {state.desktopHidden = localStorage.getItem('archivebox.sidebar-hidden') === 'true';} catch (_) {}
    try {
      const destination = sessionStorage.getItem(modeDestinationKey);
      sessionStorage.removeItem(modeDestinationKey);
      if (viewport.matches && destination === location.pathname + location.search) state.mobileCollapsed = false;
    } catch (_) {}
    sidebar.querySelector('#library-mode-menu')?.addEventListener('click', event => {
      const link = event.target.closest('a[href]');
      if (!link || !viewport.matches || event.defaultPrevented || event.button !== 0 ||
          event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      try {sessionStorage.setItem(modeDestinationKey, link.pathname + link.search);} catch (_) {}
    });
    function apply() {
      const narrow = viewport.matches;
      const hidden = narrow ? state.mobileCollapsed : state.desktopHidden;
      sidebar.classList.toggle('is-collapsed', state.mobileCollapsed);
      library.classList.toggle('sidebar-hidden', !narrow && state.desktopHidden);
      toggle.setAttribute('aria-expanded', String(!hidden));
      toggle.setAttribute('aria-label', `${hidden ? 'Show' : 'Hide'} ${mode}`);
      toggle.title = toggle.getAttribute('aria-label');

      const reopen = library.querySelector('.folder-sidebar-reopen');
      if (!reopen) return;
      const caption = reopen.querySelector('span');
      if (caption.textContent !== folderName) caption.textContent = folderName;
      reopen.title = `Show ${mode} · ${folderName}`;
      reopen.setAttribute('aria-label', `Show ${mode}`);
      reopen.hidden = narrow || !state.desktopHidden;
    }
    sidebars.set(sidebar, state);
    apply();
    return state;
  }

  window.archiveboxLibraryLayout = {
    initializeTags,
    initializeSidebar,
    bindCompactTags(pills) {
      const row = {pills, editor: pills.parentElement};
      bindBadgeToggle(row, () => updateCompactBadges(row));
      updateCompactBadges(row);
    },
  };
})();
