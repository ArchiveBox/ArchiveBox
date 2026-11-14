document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.querySelector('.folder-sidebar');
  const dialog = document.querySelector('#folder-dialog');
  const folderForm = dialog?.querySelector('form');
  if (dialog) {
    const picker = sidebar ? null : document.querySelector('#id_folder');
    async function openFolder(button) {
      button.closest('.folder-menu:popover-open')?.hidePopover();
      folderForm.reset();
      dialog.dataset.mode=button.dataset.mode || 'edit';
      const moving=dialog.dataset.mode==='move';
      dialog.querySelector('.folder-name-field').hidden=moving;
      dialog.querySelector('.folder-move-field').hidden=!moving;
      dialog.querySelector('.folder-save').textContent=moving ? 'Move folder' : 'Save folder';
      folderForm.elements.folder_id.value = button.dataset.id || '';
      folderForm.elements.name.value = button.dataset.name || '';
      folderForm.elements.parent.value = button.dataset.parent || picker?.value || '';
      document.querySelector('#folder-dialog-title').textContent = moving ? 'Move folder' : button.dataset.id ? (button.dataset.smart === 'true' ? 'Edit smart folder rules' : 'Edit folder') : button.dataset.smart === 'true' ? 'New smart folder' : 'New folder';
      dialog.querySelector('.folder-form-error').textContent = '';
      dialog.querySelector('.folder-delete').hidden=true;
      dialog.showModal();
      (moving ? folderForm.elements.parent : folderForm.elements.name).focus();
      const kind = dialog.querySelector('#folder-kind');
      kind.disabled = true;
      folderForm.querySelector('[type=submit]').disabled = true;
      try {
        const url = new URL(folderForm.dataset.rulesUrl, location.href);
        if (button.dataset.id) url.searchParams.set('folder_id', button.dataset.id);
        const response = await fetch(url, {credentials:'same-origin'});
        if (!response.ok) throw new Error('Could not load folder rules.');
        const schema = await response.json();
        setupRules(schema, button.dataset.smart === 'true');
        folderForm.querySelector('[type=submit]').disabled = false;
      } catch (error) {dialog.querySelector('.folder-form-error').textContent = error.message;}

    }
    function setupRules(schema, smart) {
      const kind = dialog.querySelector('#folder-kind');
      const root = dialog.querySelector('.folder-rules');
      dialog.querySelector('.folder-delete').hidden=!schema.can_delete || dialog.dataset.mode==='move';
      const defaultRule = () => ({field:'url', lookup:'icontains', value:''});
      const negatives={not_exact:'exact',not_contains:'icontains',not_in:'in',not_in_folder:'in_folder'};
      function normalize(node) {
        if (!node.op) {
          if (negatives[node.lookup]) return {op:'NOT',rules:[{...node,lookup:negatives[node.lookup]}]};
          return node;
        }
        const members=node.rules.map(normalize);
        if (node.op==='NOT') return members[0].op==='NOT' ? members[0].rules[0] : {op:'NOT',rules:members};
        while (members.length>2) members.splice(0,2,{op:node.op,rules:members.slice(0,2)});
        return {...node,rules:members};
      }
      let rules = normalize(schema.rules || {op:'AND', rules:[defaultRule()]});
      const specs = new Map(schema.fields.map(field => [field.name, field]));
      const unavailable = new Set(schema.unavailable_parents);
      [...folderForm.elements.parent.options].forEach(option => option.disabled=unavailable.has(option.value));
      smart ||= schema.rules !== null;
      kind.value = smart ? 'smart' : 'normal';
      kind.disabled = schema.container || Boolean(picker);
      if (smart && folderForm.elements.folder_id.value && dialog.dataset.mode!=='move') document.querySelector('#folder-dialog-title').textContent='Edit smart folder rules';
      function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
      }
      function select(options, value, label, change) {
        const control = element('select');
        control.setAttribute('aria-label', label);
        options.forEach(([key, text]) => control.add(new Option(text, key)));
        control.value = String(value ?? '');
        control.addEventListener('change', () => {change(control.value); serialize();});
        return control;
      }
      function button(label, action, className='') {
        const control = element('button', className, label);
        control.type = 'button';
        control.addEventListener('click', action);
        return control;
      }
      function serialize() {
        function compact(node) {
          if (!node.op) return node;
          const children=node.rules.map(compact);
          return node.op!=='NOT' && children.length===1 ? children[0] : {...node,rules:children};
        }
        folderForm.elements.rules.value = kind.value === 'smart' ? JSON.stringify(compact(rules)) : '';
      }
      function input(type, value, label, change) {
        const control = element('input'); control.type = type; control.value = value ?? '';
        control.setAttribute('aria-label', label); control.required = true;
        if (type === 'number') {control.step='any';control.inputMode='decimal';}
        control.addEventListener('input', () => {change(control.value); serialize();});
        return control;
      }
      function renderValue(row, node, spec) {
        if (['isnull','present'].includes(node.lookup)) return;
        if (spec.type === 'folder') {
          const options = node.lookup === 'in_children' ? [['self','This folder']] : [['*','ANY']];
          options.push(...schema.folders.map(folder => [folder.id, folder.name]));
          node.value ??= options[0][0];
          row.append(select(options, node.value, 'Folder', value => node.value=value));
        } else if (['in','not_in'].includes(node.lookup)) {
          row.append(input('text', Array.isArray(node.value) ? node.value.join(', ') : node.value, 'Values, separated by commas', value => node.value=value.split(',').map(part => part.trim())));
        } else if (node.lookup === 'past_days') {
          row.append(input('number', node.value, 'Days', value => node.value=value));
        } else if (spec.type === 'boolean' || (spec.choices.length && node.lookup==='exact')) {
          const options = spec.type === 'boolean' ? [['true','Yes'],['false','No']] : spec.choices;
          node.value ??= spec.type === 'boolean' ? true : options[0][0];
          row.append(select(options, node.value, 'Value', value => node.value=spec.type === 'boolean' ? value==='true' : value));
        } else if (spec.units.length) {
          if (typeof node.value !== 'object' || node.value === null) node.value={amount:node.value || '', unit:'B'};
          const quantity = element('div','rule-quantity');
          quantity.append(input('number', node.value.amount, 'Amount', value => node.value.amount=value),
            select(spec.units.map(unit => [unit,unit]), node.value.unit, 'Unit', value => node.value.unit=value));
          row.append(quantity);
        } else {
          const type = spec.type === 'number' ? 'number' : spec.type === 'date' ? 'date' : 'text';
          const value = spec.type === 'json' && typeof node.value === 'object' ? JSON.stringify(node.value) : node.value;
          row.append(input(type, value, 'Value', value => {
            if (spec.type === 'json' && node.lookup !== 'has_key') {
              try {node.value=JSON.parse(value);} catch (_) {node.value=value;}
            } else node.value=value;
          }));
        }
      }
      function renderNode(node, replace, remove) {
        const negated=node.op==='NOT';
        const item=negated ? node.rules[0] : node;
        const row=element('div',item.op ? 'rule-group' : 'rule-condition');
        function changePolarity(value) {replace(value==='not' ? {op:'NOT',rules:[item]} : item);render();}
        function nest() {replace({op:'AND',rules:[node,defaultRule()]});render();}
        function action(label,title,callback) {
          const control=button(label,callback,'rule-remove');
          control.title=title;control.setAttribute('aria-label',title);return control;
        }
        if (item.op) {
          const heading=element('div','rule-group-heading');
          heading.append(select([['is','Group'],['not','NOT group']],negated ? 'not' : 'is','Group polarity',changePolarity));
          const actions=element('div','rule-actions');
          actions.append(action('⊞','Nest group',nest));
          if (remove) actions.append(action('×','Remove group',remove));
          heading.append(actions);row.append(heading);
          item.rules.forEach((child,index) => {
            if (index) {
              const join=element('div','rule-join');
              join.append(select([['AND','AND'],['OR','OR']],item.op,'Join rules',value => {item.op=value;render();}));
              row.append(join);
            }
            row.append(renderNode(child,value => {item.rules[index]=value;},item.rules.length>1 ? () => {item.rules.splice(index,1);render();} : null));
          });
          if (item.rules.length<2) {
            const toolbar=element('div','rule-group-toolbar');
            toolbar.append(button('+ Rule',() => {item.rules.push(defaultRule());render();}),
              button('+ Group',() => {item.rules.push({op:'AND',rules:[defaultRule()]});render();}));
            row.append(toolbar);
          }
        } else {
          const spec=specs.get(item.field) || specs.get('url');
          row.append(select(schema.fields.map(field => [field.name,field.label]),item.field,'Field',value => {
            item.field=value;item.lookup=specs.get(value).operators[0];item.value=null;render();
          }));
          const polarity=select([['is','IS'],['not','IS NOT']],negated ? 'not' : 'is','Condition polarity',changePolarity);
          polarity.className='rule-polarity';row.append(polarity);
          row.append(select(spec.operators.filter(op => !negatives[op]).map(op => [op,({exact:'equal to',icontains:'containing',istartswith:'starting with',iendswith:'ending with',in:'one of',isnull:'empty',present:'present',in_folder:'in folder',in_children:'in children of'})[op] || schema.operators[op].replace(/^is /,'')]),item.lookup,'Comparison',value => {
            item.lookup=value;item.value=null;render();
          }));
          const value=element('div','rule-value');renderValue(value,item,spec);row.append(value);
          const actions=element('div','rule-actions');actions.append(action('⊞','Nest condition in group',nest));
          if (remove) actions.append(action('×','Remove condition',remove));
          row.append(actions);
        }
        row.classList.toggle('is-negated',negated);
        return row;
      }
      function render() {
        root.replaceChildren(); root.hidden=kind.value !== 'smart' || dialog.dataset.mode==='move';
        dialog.classList.toggle('has-rules', !root.hidden);
        if (!root.hidden) {
          const group=rules.op==='NOT' ? rules.rules[0] : rules;
          if (!group.op && !schema.container) rules={op:'AND',rules:[rules]};
          root.append(renderNode(rules,value => {rules=value;}));
          if (schema.container) root.querySelectorAll('input,select,button').forEach(control => control.disabled=true);
        }
        serialize();
      }
      kind.onchange = render;
      render();
    }
    document.querySelectorAll('.folder-new,.folder-edit').forEach(button => button.addEventListener('click', () => openFolder(button)));
    dialog.querySelectorAll('.folder-dialog-close').forEach(button => button.addEventListener('click', () => dialog.close()));
    dialog.querySelector('.folder-delete').addEventListener('click', async event => {
      if (!window.confirm(`Delete “${folderForm.elements.name.value}”?`)) return;
      event.currentTarget.disabled=true;
      try {
        const response=await fetch(folderForm.dataset.deleteUrl,{method:'POST',body:new FormData(folderForm),credentials:'same-origin'});
        const result=await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not delete folder.');
        const url=new URL(location.href);
        if (url.searchParams.get('folder')===folderForm.elements.folder_id.value) url.searchParams.delete('folder');
        location.assign(url.href);
      } catch (error) {dialog.querySelector('.folder-form-error').textContent=error.message;event.currentTarget.disabled=false;}
    });
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
  document.querySelectorAll('.folder-menu-toggle,.library-import-toggle,.library-export-toggle,.library-create-toggle').forEach(button => {
    const menu = document.getElementById(button.getAttribute('popovertarget'));
    const items = [...menu.querySelectorAll('[role=menuitem]')];
    function positionMenu() {
      const rect = button.getBoundingClientRect();
      const box = menu.getBoundingClientRect();
      menu.style.left = `${Math.max(8, Math.min(innerWidth - box.width - 8, rect.right - box.width))}px`;
      const top = rect.bottom + box.height + 12 <= innerHeight ? rect.bottom + 4 : rect.top - box.height - 4;
      menu.style.top = `${Math.max(8, Math.min(innerHeight - box.height - 8, top))}px`;
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
  if (!sidebar) return;
  const form = document.querySelector('#changelist-form');
  if (location.hash === '#delete-snapshots' && form && new URLSearchParams(location.search).has('folder')) {
    history.replaceState(null, '', location.pathname + location.search);
    const action = form.querySelector('select[name=action]');
    const selection = form.querySelector('input.action-select');
    const across = form.querySelector('input[name=select_across]');
    const submit = form.querySelector('button[name=index]');
    if (selection && across && submit && action?.querySelector('option[value=delete_selected]')) {
      selection.checked = true;
      across.value = '1';
      action.value = 'delete_selected';
      // Django's existing action displays confirmation before requesting deletion.
      form.requestSubmit(submit);
      return;
    }
  }
  const status = sidebar.querySelector('.folder-drop-status');
  const rows = [...sidebar.querySelectorAll('.folder-row')];
  const segments = new Intl.Segmenter(undefined, {granularity:'grapheme'});
  function leadingEmoji(name) {
    const first = segments.segment(name).containing(0)?.segment;
    return first && /\p{Extended_Pictographic}|\p{Regional_Indicator}|[0-9#*]\uFE0F?\u20E3/u.test(first) ? first : '';
  }
  rows.forEach(row => {
    const first = leadingEmoji(row.dataset.folderName);
    if (!first) return;
    const label = row.querySelector('.folder-link>span');
    const emoji = document.createElement('span');
    emoji.className='folder-title-emoji'; emoji.textContent=first; emoji.setAttribute('aria-hidden','true');
    const icon=row.querySelector('.folder-link>svg');
    if (icon) icon.replaceWith(emoji);
    else {
      const toggle=row.querySelector('.folder-toggle');
      toggle.classList.add('has-title-emoji'); toggle.append(emoji);
    }
    label.textContent=row.dataset.folderName.slice(first.length).trimStart();
    row.querySelector('.folder-link').setAttribute('aria-label', row.dataset.folderName);
  });
  const current = sidebar.querySelector('.folder-row:has([aria-current="page"])');
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
      if (toggle) {
        const expanded = term ? rows.some(child => child.dataset.parentId === row.dataset.folderId && matching.has(child.dataset.folderId)) : !collapsed.has(row.dataset.folderId);
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.setAttribute('aria-label', `${expanded ? 'Collapse' : 'Expand'} ${row.dataset.folderName}`);
      }
    });
    sidebar.querySelector('.folder-search-empty').hidden = !term || matching.size > 0;
  }
  search.addEventListener('input', renderTree);
  const searchToggle = sidebar.querySelector('.folder-search-toggle');
  const sectionLabel = sidebar.querySelector('.folder-section-label');
  function toggleFolderSearch(open) {
    search.hidden = !open;
    sectionLabel.hidden = open;
    searchToggle.setAttribute('aria-expanded', String(open));
    searchToggle.setAttribute('aria-label', open ? 'Close folder search' : 'Find a folder');
    searchToggle.title = open ? 'Close folder search' : 'Find a folder';
    if (open) search.focus();
    else {
      search.value = '';
      renderTree();
      searchToggle.focus();
    }
  }
  searchToggle.addEventListener('click', () => toggleFolderSearch(search.hidden));
  search.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      toggleFolderSearch(false);
    }
  });
  const mobileToggle = sidebar.querySelector('.folder-mobile-toggle');
  const reopenToggle = document.querySelector('.folder-sidebar-reopen');
  const currentFolder = current?.dataset.folderName || 'All snapshots';
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
    if (mobileViewport.matches) {
      mobileCollapsed = !mobileCollapsed;
      if (mobileCollapsed && !search.hidden) toggleFolderSearch(false);
    }
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
    clearDropTarget();
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
      const across = form.querySelector('input.select-across')?.value === '1';
      if (!checkbox.checked && !across) {
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
    row.addEventListener('dragend', () => {
      const cancelled = movingFolder;
      clearDrag();
      if (cancelled) status.textContent = '';
    });
  });
  const rootTarget = sidebar.querySelector('.library-root-link');
  rootTarget.dataset.folderId = '';
  rootTarget.classList.add('folder-drop-target');
  function placement(target, event) {
    if (!movingFolder || !target.dataset.folderId) return 'inside';
    const rect = target.getBoundingClientRect();
    const fraction = (event.clientY - rect.top) / rect.height;
    return fraction < .25 ? 'before' : fraction > .75 ? 'after' : 'inside';
  }
  function canDrop(target) {
    if (dragging) return target !== rootTarget;
    if (!movingFolder) return false;
    let ancestor = target;
    while (ancestor) {
      if (ancestor.dataset.folderId === movingFolder) return false;
      ancestor = rows.find(row => row.dataset.folderId === ancestor.dataset.parentId);
    }
    return true;
  }
  let hoverTarget = null;
  let hoverPlacement = null;
  function clearDropTarget() {
    hoverTarget?.classList.remove('drop-active','drop-before','drop-after');
    hoverTarget = null;
    hoverPlacement = null;
    clearTimeout(expandTimer);
    expandTimer = null;
  }
  sidebar.querySelectorAll('.folder-drop-target').forEach(target => {
    target.addEventListener('dragover', event => {
      if (!dragging && !movingFolder) return;
      event.preventDefault();
      if (!canDrop(target)) {
        event.dataTransfer.dropEffect = 'none';
        clearDropTarget();
        return;
      }
      event.dataTransfer.dropEffect = 'move';
      const position = placement(target, event);
      if (hoverTarget !== target || hoverPlacement !== position) clearDropTarget();
      hoverTarget = target;
      hoverPlacement = position;
      target.classList.toggle('drop-before', position === 'before');
      target.classList.toggle('drop-after', position === 'after');
      target.classList.toggle('drop-active', position === 'inside');
      if (position === 'inside' && collapsed.has(target.dataset.folderId) && !expandTimer) {
        expandTimer = setTimeout(() => {collapsed.delete(target.dataset.folderId); renderTree(); expandTimer = null;}, 600);
      }
    });
    target.addEventListener('dragleave', event => {if (!target.contains(event.relatedTarget) && hoverTarget === target) clearDropTarget();});
    target.addEventListener('drop', async event => {
      if (!dragging && !movingFolder) return;
      event.preventDefault();
      if (!canDrop(target)) {clearDrag(); status.textContent = ''; return;}
      if (movingFolder) {
        const data = new FormData();
        data.set('folder_id', movingFolder); data.set('target_id', target.dataset.folderId); data.set('placement', placement(target,event));
        data.set('csrfmiddlewaretoken', folderForm.elements.csrfmiddlewaretoken.value);
        clearDrag(); status.textContent = 'Moving folder…';
        try {
          const response = await fetch(sidebar.dataset.moveUrl, {method:'POST',body:data,credentials:'same-origin'});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Could not move folder.');
          let ancestor = data.get('placement') === 'inside' ? target : rows.find(row => row.dataset.folderId === target.dataset.parentId);
          while (ancestor) {
            collapsed.delete(ancestor.dataset.folderId);
            ancestor = rows.find(row => row.dataset.folderId === ancestor.dataset.parentId);
          }
          try {localStorage.setItem('archivebox.folder-collapsed', JSON.stringify([...collapsed]));} catch (_) {}
          location.reload();
        } catch (error) {status.textContent = error.message;}
        return;
      }
      const destination = form.querySelector('[name=folder_destination]');
      const action = form.querySelector('select[name=action]');
      if (!destination || !action) {clearDrag(); status.textContent = 'Folder moves are unavailable for this account.'; return;}
      destination.value = target.dataset.smart === 'true' && target.dataset.container !== 'true' ? '' : target.dataset.folderId;
      action.value = 'move_to_folder';
      clearDrag(); status.textContent = 'Moving snapshots…';
      form.requestSubmit(form.querySelector('button[name=index]'));
    });
  });
});
