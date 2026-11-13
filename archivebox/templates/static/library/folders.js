document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.querySelector('.folder-sidebar');
  const dialog = document.querySelector('#folder-dialog');
  const folderForm = dialog?.querySelector('form');
  if (dialog) {
    const picker = sidebar ? null : document.querySelector('#id_folder');
    function openFolder(button) {
      button.closest('.folder-menu:popover-open')?.hidePopover();
      folderForm.reset();
      folderForm.elements.folder_id.value = button.dataset.id || '';
      folderForm.elements.name.value = button.dataset.name || '';
      folderForm.elements.parent.value = button.dataset.parent || picker?.value || '';
      document.querySelector('#folder-dialog-title').textContent = button.dataset.id ? 'Edit folder' : 'New folder';
      dialog.querySelector('.folder-form-error').textContent = '';
      dialog.showModal();
      folderForm.elements.name.focus();
    }
    document.querySelectorAll('.folder-new,.folder-edit').forEach(button => button.addEventListener('click', () => openFolder(button)));
    dialog.querySelectorAll('.folder-dialog-close').forEach(button => button.addEventListener('click', () => dialog.close()));
    folderForm.addEventListener('submit', async event => {
      event.preventDefault();
      const save = folderForm.querySelector('[type=submit]');
      save.disabled = true;
      try {
        const response = await fetch(folderForm.action, {method:'POST', body:new FormData(folderForm), credentials:'same-origin'});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not save folder.');
        if (picker) {
          const parent = folderForm.elements.parent.selectedOptions[0];
          const label = parent.value ? `${parent.textContent} / ${result.name}` : result.name;
          picker.add(new Option(label, String(result.id), true, true));
          folderForm.elements.parent.add(new Option(label, String(result.id)));
          picker.dispatchEvent(new Event('change', {bubbles:true}));
          dialog.close();
          picker.focus();
        } else location.reload();
      } catch (error) {dialog.querySelector('.folder-form-error').textContent = error.message;}
      finally {save.disabled = false;}
    });
  }
  if (!sidebar) return;
  const form = document.querySelector('#changelist-form');
  const status = sidebar.querySelector('.folder-drop-status');
  const rows = [...sidebar.querySelectorAll('.folder-row')];
  sidebar.querySelectorAll('.folder-menu-toggle,.library-import-toggle').forEach(button => {
    const menu = document.getElementById(button.getAttribute('popovertarget'));
    const items = [...menu.querySelectorAll('[role=menuitem]')];
    function positionMenu() {
      const rect = button.getBoundingClientRect();
      const box = menu.getBoundingClientRect();
      menu.style.left = `${Math.max(8, Math.min(innerWidth - box.width - 8, rect.right - box.width))}px`;
      menu.style.top = `${Math.max(8, Math.min(innerHeight - box.height - 8, rect.bottom + 4))}px`;
    }
    menu.addEventListener('toggle', event => {
      const open = event.newState === 'open';
      button.setAttribute('aria-expanded', String(open));
      if (open) {
        positionMenu();
        items[0]?.focus({preventScroll:true});
        window.addEventListener('resize', positionMenu);
        window.addEventListener('scroll', positionMenu, true);
      } else {
        window.removeEventListener('resize', positionMenu);
        window.removeEventListener('scroll', positionMenu, true);
      }
    });
    button.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!menu.matches(':popover-open')) menu.showPopover();
      }
    });
    menu.addEventListener('keydown', event => {
      const index = items.indexOf(document.activeElement);
      if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        items[next]?.focus();
      } else if (event.key === 'Tab') menu.hidePopover();
    });
  });
  const search = sidebar.querySelector('.folder-search');
  const collapsed = new Set();
  try {JSON.parse(localStorage.getItem('archivebox.folder-collapsed') || '[]').forEach(id => collapsed.add(String(id)));} catch (_) {}
  // Always reveal the selected folder's path when opening a saved list URL.
  let selected = sidebar.querySelector('[aria-current="page"]')?.closest('.folder-row');
  while (selected?.dataset.parentId) {
    collapsed.delete(selected.dataset.parentId);
    selected = rows.find(row => row.dataset.folderId === selected.dataset.parentId);
  }
  function renderTree() {
    const term = search.value.trim().toLocaleLowerCase();
    const matching = new Set(rows.filter(row => row.dataset.folderName.toLocaleLowerCase().includes(term)).map(row => row.dataset.folderId));
    if (term) rows.filter(row => matching.has(row.dataset.folderId)).forEach(row => {
      let parent = row.dataset.parentId;
      while (parent) {matching.add(parent); parent = rows.find(item => item.dataset.folderId === parent)?.dataset.parentId;}
    });
    rows.forEach(row => {
      let parent = row.dataset.parentId;
      let hidden = false;
      while (parent) {
        if (collapsed.has(parent)) hidden = true;
        parent = rows.find(candidate => candidate.dataset.folderId === parent)?.dataset.parentId;
      }
      row.hidden = term ? !matching.has(row.dataset.folderId) : hidden;
      const toggle = row.querySelector('.folder-toggle');
      if (toggle) toggle.setAttribute('aria-expanded', String(!collapsed.has(row.dataset.folderId)));
    });
    sidebar.querySelector('.folder-search-empty').hidden = !term || matching.size > 0;
  }
  search.addEventListener('input', renderTree);
  sidebar.querySelector('.folder-collapse-all').addEventListener('click', () => {
    rows.filter(row => row.querySelector('.folder-toggle')).forEach(row => collapsed.add(row.dataset.folderId));
    renderTree();
  });
  const mobileToggle = sidebar.querySelector('.folder-mobile-toggle');
  const reopenToggle = document.querySelector('.folder-sidebar-reopen');
  const currentFolder = sidebar.querySelector('[aria-current="page"] span')?.textContent.trim() || 'All snapshots';
  reopenToggle.querySelector('span').textContent = currentFolder;
  reopenToggle.title = `Show folders · ${currentFolder}`;
  const library = sidebar.closest('.snapshot-library');
  const mobileViewport = matchMedia('(max-width: 767px)');
  let desktopHidden = false;
  let mobileCollapsed = true;
  try {desktopHidden = localStorage.getItem('archivebox.sidebar-hidden') === 'true';} catch (_) {}
  function viewportChanged() {
    const hidden = mobileViewport.matches ? mobileCollapsed : desktopHidden;
    sidebar.classList.toggle('is-collapsed', mobileViewport.matches && mobileCollapsed);
    library.classList.toggle('sidebar-hidden', !mobileViewport.matches && desktopHidden);
    reopenToggle.hidden = mobileViewport.matches || !desktopHidden;
    mobileToggle.setAttribute('aria-expanded', String(!hidden));
    mobileToggle.setAttribute('aria-label', hidden ? 'Show folders' : 'Hide folders');
    mobileToggle.title = hidden ? 'Show folders' : 'Hide folders';
  }
  mobileViewport.addEventListener('change', viewportChanged);
  viewportChanged();
  mobileToggle.addEventListener('click', () => {
    if (mobileViewport.matches) mobileCollapsed = !mobileCollapsed;
    else {
      desktopHidden = true;
      try {localStorage.setItem('archivebox.sidebar-hidden', 'true');} catch (_) {}
    }
    viewportChanged();
    if (!mobileViewport.matches) reopenToggle.focus();
  });
  reopenToggle.addEventListener('click', () => {
    desktopHidden = false;
    try {localStorage.setItem('archivebox.sidebar-hidden', 'false');} catch (_) {}
    viewportChanged();
    mobileToggle.focus();
  });
  sidebar.querySelectorAll('.folder-toggle').forEach(toggle => toggle.addEventListener('click', () => {
    const id = toggle.closest('.folder-row').dataset.folderId;
    if (collapsed.has(id)) collapsed.delete(id); else collapsed.add(id);
    try {localStorage.setItem('archivebox.folder-collapsed', JSON.stringify([...collapsed]));} catch (_) {}
    renderTree();
  }));
  renderTree();

  if (!form) return;
  form.querySelectorAll('.tag-pills-inline').forEach(pills => {
    const toggle = document.createElement('button');
    toggle.type = 'button'; toggle.className = 'library-tags-toggle'; toggle.hidden = true;
    pills.after(toggle);
    function updateTags() {
      const count = pills.querySelectorAll('.tag-pill').length;
      const expanded = pills.classList.contains('library-tags-expanded');
      toggle.hidden = !expanded && pills.scrollHeight <= pills.clientHeight;
      toggle.textContent = expanded ? 'Show fewer tags' : `Show all ${count} tags`;
      toggle.setAttribute('aria-expanded', String(expanded));
    }
    toggle.addEventListener('click', () => {pills.classList.toggle('library-tags-expanded'); updateTags();});
    new MutationObserver(updateTags).observe(pills, {childList:true,subtree:true});
    window.addEventListener('resize', updateTags);
    updateTags();
  });
  function selectionChanged() {
    const checked = form.querySelector('input.action-select:checked');
    document.querySelectorAll('.actions-folder').forEach(field => {field.hidden = !checked;});
  }
  document.addEventListener('change', selectionChanged);
  selectionChanged();
  let dragging = false;
  let movingFolder = null;
  let expandTimer;
  let badge;
  function clearDrag() {
    dragging = false;
    movingFolder = null;
    clearTimeout(expandTimer);
    expandTimer = null;
    document.body.classList.remove('dragging-snapshots');
    document.querySelectorAll('.snapshot-dragging,.drop-active,.drop-before,.drop-after').forEach(node => node.classList.remove('snapshot-dragging','drop-active','drop-before','drop-after'));
    badge?.remove();
  }
  form.querySelectorAll('input.action-select').forEach(checkbox => {
    const row = checkbox.closest('tr,.card');
    if (!row) return;
    row.draggable = true;
    row.addEventListener('dragstart', event => {
      if (event.target.closest('button,input,select,.tag-editor-container,.tag-editor-inline')) {event.preventDefault(); return;}
      if (!checkbox.checked) {
        form.querySelectorAll('input.action-select').forEach(item => {item.checked = item === checkbox;});
        form.querySelectorAll('input.select-across').forEach(item => {item.value = '0';});
        checkbox.dispatchEvent(new Event('change', {bubbles:true}));
      }
      const checked = [...form.querySelectorAll('input.action-select:checked')];
      checked.forEach(item => item.closest('tr,.card')?.classList.add('snapshot-dragging'));
      dragging = true;
      document.body.classList.add('dragging-snapshots');
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('application/x-archivebox-snapshots', JSON.stringify(checked.map(item => item.value)));
      badge = document.createElement('div'); badge.className = 'snapshot-drag-badge';
      const across = form.querySelector('input.select-across')?.value === '1';
      badge.textContent = across ? 'Move all matching snapshots' : `Move ${checked.length} snapshot${checked.length === 1 ? '' : 's'}`;
      document.body.appendChild(badge); event.dataTransfer.setDragImage(badge, 16, 16);
      status.textContent = 'Drop on a folder to move.';
    });
    row.addEventListener('dragend', () => {clearDrag(); status.textContent = '';});
  });
  rows.forEach(row => {
    row.draggable = true;
    row.addEventListener('dragstart', event => {
      if (event.target.closest('button,input')) {event.preventDefault(); return;}
      movingFolder = row.dataset.folderId;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('application/x-archivebox-folder', movingFolder);
      row.classList.add('snapshot-dragging');
      status.textContent = 'Drop inside a folder to nest, or between folders to reorder.';
    });
    row.addEventListener('dragend', clearDrag);
  });
  const rootTarget = sidebar.querySelector('.library-primary a');
  rootTarget.dataset.folderId = '';
  rootTarget.classList.add('folder-drop-target');
  function placement(target, event) {
    if (!movingFolder || !target.dataset.folderId) return 'inside';
    const rect = target.getBoundingClientRect();
    const fraction = (event.clientY - rect.top) / rect.height;
    return fraction < .25 ? 'before' : fraction > .75 ? 'after' : 'inside';
  }
  sidebar.querySelectorAll('.folder-drop-target').forEach(target => {
    target.addEventListener('dragover', event => {
      if (!dragging && !movingFolder) return;
      if (dragging && target === rootTarget) return;
      if (movingFolder && (target.dataset.folderId === movingFolder || target.getAttribute('href') === '?folder=unfiled')) return;
      event.preventDefault(); event.dataTransfer.dropEffect = 'move';
      const position = placement(target, event);
      target.classList.toggle('drop-before', position === 'before');
      target.classList.toggle('drop-after', position === 'after');
      target.classList.toggle('drop-active', position === 'inside');
      if (position === 'inside' && collapsed.has(target.dataset.folderId) && !expandTimer) {
        expandTimer = setTimeout(() => {collapsed.delete(target.dataset.folderId); renderTree(); expandTimer = null;}, 600);
      }
    });
    target.addEventListener('dragleave', event => {if (!target.contains(event.relatedTarget)) {target.classList.remove('drop-active','drop-before','drop-after'); clearTimeout(expandTimer); expandTimer = null;}});
    target.addEventListener('drop', async event => {
      if (!dragging && !movingFolder) return;
      if (dragging && target === rootTarget) return;
      event.preventDefault();
      if (movingFolder) {
        const data = new FormData();
        data.set('folder_id', movingFolder); data.set('target_id', target.dataset.folderId); data.set('placement', placement(target,event));
        data.set('csrfmiddlewaretoken', folderForm.elements.csrfmiddlewaretoken.value);
        clearDrag(); status.textContent = 'Moving folder…';
        try {
          const response = await fetch(sidebar.dataset.moveUrl, {method:'POST',body:data,credentials:'same-origin'});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Could not move folder.');
          location.reload();
        } catch (error) {status.textContent = error.message;}
        return;
      }
      const destination = form.querySelector('[name=folder_destination]');
      const action = form.querySelector('select[name=action]');
      if (!destination || !action) {clearDrag(); status.textContent = 'Folder moves are unavailable for this account.'; return;}
      destination.value = target.dataset.folderId;
      action.value = 'move_to_folder';
      clearDrag(); status.textContent = 'Moving snapshots…';
      form.requestSubmit(form.querySelector('button[name=index]'));
    });
  });
});
