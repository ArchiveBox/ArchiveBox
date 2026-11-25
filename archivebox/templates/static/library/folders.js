window.archiveboxRefreshLibraryExportLinks = (doc, searchParams) => {
  // A search submission changes only q and search_mode. Preserve each live
  // sidebar link's own folder, sort, visibility and repeated filter values.
  function updateSearch(query, next) {
    for (const key of ['q', 'search_mode']) {
      if (next.has(key)) query.set(key, next.get(key));
      else query.delete(key);
    }
    return query;
  }
  document.querySelectorAll('a[data-export-format]').forEach(link => {
    const menu = link.closest('.folder-menu');
    const format = 'a[data-export-format="' + link.dataset.exportFormat + '"]';
    const nextLink = menu
      ? doc.getElementById(menu.id)?.querySelector(format)
      : doc.querySelector('.snapshot-export-links:not(.snapshot-export-menu) ' + format);
    if (nextLink) {
      link.dataset.exportRoute = nextLink.dataset.exportRoute;
      link.dataset.exportQuery = nextLink.dataset.exportQuery;
    } else if (searchParams || menu?.closest('.folder-row')) {
      // Independently paginated branches retain their scope during streamed search.
      const currentView = doc.getElementById('snapshot-export-menu-sidebar')?.querySelector(format);
      const next = searchParams || (currentView && new URLSearchParams(currentView.dataset.exportQuery));
      if (!next) return;
      link.dataset.exportQuery = updateSearch(new URLSearchParams(link.dataset.exportQuery), next).toString();
    }
    if (link.hasAttribute('href')) link.href = window.archiveboxExportURL(link);
  });
  document.querySelectorAll('[data-sidebar-mode-link]').forEach(link => {
    const next = doc.querySelector('[data-sidebar-mode-link="' + link.dataset.sidebarModeLink + '"]');
    if (next) link.setAttribute('href', next.getAttribute('href'));
    else if (searchParams) {
      const url = new URL(link.href);
      updateSearch(url.searchParams, searchParams);
      link.setAttribute('href', url.pathname + url.search);
    }
  });
};

document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.querySelector('.folder-sidebar');
  const dialog = document.querySelector('#folder-dialog');
  const folderForm = dialog?.querySelector('form');
  if (dialog) {
    const picker = sidebar ? null : document.querySelector('#id_folder');
    let editorVersion = 0;
    async function openFolder(button) {
      const version = ++editorVersion;
      dialog.querySelector('.folder-rule-layout').hidden = true;
      dialog.querySelector('.folder-options').hidden = true;
      dialog.classList.remove('has-rules');
      button.closest('.folder-menu:popover-open')?.hidePopover();
      folderForm.reset();
      dialog.dataset.mode=button.dataset.mode || 'edit';
      const moving=dialog.dataset.mode==='move';
      dialog.querySelector('.folder-name-field').hidden=moving;
      dialog.querySelector('.folder-move-field').hidden=!moving;
      dialog.querySelector('.folder-save').textContent=moving ? 'Move folder' : 'Save folder';
      folderForm.elements.folder_id.value = button.dataset.id || '';
      folderForm.elements.name.value = button.dataset.name || '';
      const parent = folderForm.elements.parent;
      const parentPicker = window.ArchiveBoxPicker.mount(parent);
      parentPicker.reset();
      const parentId = button.dataset.parent || picker?.value || '';
      const row = button.closest('.folder-row');
      const label = picker?.value === parentId ? picker.selectedOptions[0]?.text :
        row?.dataset.folderId === parentId ? row.querySelector('.folder-link')?.title : null;
      for (const option of Array.from(parent.options)) {
        if (option.value && !option.dataset.pickerCommand) option.remove();
      }
      if (parentId && label) window.ArchiveBoxPicker.selectChoice(parent, parentId, label);
      parent.dataset.pickerExclude = button.dataset.id || '';
      document.querySelector('#folder-dialog-title').textContent = moving ? 'Move folder' : button.dataset.id ? (button.dataset.smart === 'true' ? 'Edit smart folder rules' : 'Edit folder') : button.dataset.smart === 'true' ? 'New smart folder' : 'New folder';
      const subtitle = dialog.querySelector('#folder-dialog-subtitle');
      subtitle.hidden = moving || Boolean(button.dataset.id) || button.dataset.smart !== 'true';
      if (subtitle.hidden) dialog.removeAttribute('aria-describedby');
      else dialog.setAttribute('aria-describedby', subtitle.id);
      dialog.querySelector('.folder-form-error').textContent = '';
      dialog.showModal();
      (moving ? parent : folderForm.elements.name).focus();
      const kind = dialog.querySelector('#folder-kind');
      kind.disabled = true;
      folderForm.querySelector('[type=submit]').disabled = true;
      try {
        const url = new URL(folderForm.dataset.rulesUrl, location.href);
        if (button.dataset.id) url.searchParams.set('folder_id', button.dataset.id);
        const response = await fetch(url, {credentials:'same-origin'});
        if (!response.ok) throw new Error('Could not load folder rules.');
        const schema = await response.json();
        if (!dialog.open || version !== editorVersion) return;
        setupRules(schema, button.dataset.smart === 'true', version);
        folderForm.querySelector('[type=submit]').disabled = false;
      } catch (error) {
        if (dialog.open && version === editorVersion) dialog.querySelector('.folder-form-error').textContent = error.message;
      }

    }
    function setupRules(schema, smart, version) {
      const kind = dialog.querySelector('#folder-kind');
      const layout = dialog.querySelector('.folder-rule-layout');
      const root = layout.querySelector('.folder-rules');
      const matches = layout.querySelector('.folder-matches');
      let previewTimer, previewRequest, lastPreview;
      function cancelPreview() {
        clearTimeout(previewTimer);
        previewRequest?.abort();
      }
      dialog.addEventListener('close', cancelPreview, {once:true});
      function previewRow(snapshot) {
        const row = element('div', 'folder-match');
        const monogram = element('span', 'folder-match-icon', (snapshot.domain || '?').slice(0, 1).toUpperCase());
        monogram.setAttribute('aria-hidden', 'true');
        const text = element('div', 'folder-match-body');
        text.append(element('strong', '', snapshot.title || snapshot.domain),
          element('small', '', [snapshot.domain, snapshot.date].filter(Boolean).join(' · ')));
        row.append(monogram, text);
        return row;
      }
      function schedulePreview(delay) {
        const serialized = folderForm.elements.rules.value;
        if (serialized === lastPreview) return;
        lastPreview = serialized;
        cancelPreview();
        matches.replaceChildren();
        if (!serialized || layout.hidden || layout.querySelector(':invalid') || dialog.querySelector('.folder-options :invalid')) return;
        previewTimer = setTimeout(() => {
          if (!dialog.open || version !== editorVersion) return;
          const controller = new AbortController();
          previewRequest = controller;
          const body = new FormData();
          for (const name of ['csrfmiddlewaretoken', 'folder_id', 'parent']) body.set(name, folderForm.elements[name].value);
          body.set('rules', serialized);
          const status = element('p');
          matches.append(status);
          const current = () => !controller.signal.aborted && dialog.open && version === editorVersion;
          async function load() {
            status.textContent = 'Loading…';
            try {
              // Bound automatic requests for sparse rules. Keep the cursor so
              // continuing a long preview or retrying an outage preserves its rows.
              for (let page = 0; page < 4; page++) {
                const response = await fetch(folderForm.dataset.rulesUrl, {method:'POST', body, credentials:'same-origin', signal:controller.signal});
                if (!current()) return;
                if (!response.ok) {
                  const error = await response.json().catch(() => ({}));
                  if (!current()) return;
                  status.textContent = error.error || `Preview unavailable (HTTP ${response.status}).`;
                  if (response.status >= 500 || response.status === 429) status.append(' ', button('Retry', load));
                  return;
                }
                const result = await response.json();
                if (!current()) return;
                status.before(...result.snapshots.map(previewRow));
                if (!result.next) {
                  if (matches.querySelector('.folder-match')) status.remove();
                  else status.textContent = 'No matching snapshots.';
                  return;
                }
                body.set('after', result.next);
              }
              status.replaceChildren(button('Continue preview', load));
            } catch (_) {
              if (current()) status.replaceChildren('Preview unavailable. ', button('Retry', load));
            }
          }
          load();
        }, delay);
      }
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
      const {limit: savedLimit, sort: savedSort, query: savedQuery = '', ...predicate} = schema.rules || {};
      let limit = savedLimit ?? '', sort = savedSort || '-created_at';
      const queryInput = folderForm.elements.folder_query;
      const advanced = layout.querySelector('.folder-advanced');
      let rules = predicate.field || predicate.op ? normalize(predicate) : null;
      // Keep saved manual predicates intact. Opening or closing Advanced only
      // changes their presentation; it must never change folder membership.
      advanced.open = !!rules;
      layout.querySelector('.folder-query').hidden = schema.container;
      queryInput.value = savedQuery;
      queryInput.dispatchEvent(new Event('archivebox:load'));
      queryInput.oninput = () => serialize(300);
      queryInput.onchange = () => serialize();
      const specs = new Map(schema.fields.map(field => [field.name, field]));
      const relationLookups = new Set(['exact', 'in', 'isnull', 'present']);
      const labels = new Map(Object.entries(schema.related_selected || {}).map(([model, choices]) =>
        [model, new Map(choices.map(choice => [String(choice.id), choice.name]))]));
      if (schema.parent_choice) {
        const parent = folderForm.elements.parent;
        window.ArchiveBoxPicker.selectChoice(parent, schema.parent_choice.id, schema.parent_choice.name);
      }
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
      function serialize(delay = 0) {
        function compact(node) {
          if (!node.op) return node;
          const children=node.rules.map(compact);
          return node.op!=='NOT' && children.length===1 ? children[0] : {...node,rules:children};
        }
        const options = {...(limit !== '' ? {limit:Number(limit)} : {}), ...(sort !== '-created_at' ? {sort} : {})};
        const query = queryInput.value.trim();
        const predicate = {...(rules ? compact(rules) : {}), ...(query ? {query} : {})};
        folderForm.elements.rules.value = kind.value === 'smart' ? JSON.stringify({...predicate, ...options}) : '';
        schedulePreview(delay);
      }
      function input(type, value, label, change) {
        const control = element('input'); control.type = type; control.value = value ?? '';
        control.setAttribute('aria-label', label); control.required = true;
        if (type === 'number') {control.step='any';control.inputMode='decimal';}
        control.addEventListener('input', () => {change(control.value); serialize(300);});
        return control;
      }
      function renderRelatedValues(row, node, model) {
        const multiple = node.lookup === 'in';
        const selected = multiple ? (Array.isArray(node.value) ? node.value.slice() : []) : (node.value == null ? [] : [node.value]);
        if (!labels.has(model)) labels.set(model, new Map());
        const known = labels.get(model);
        const chips = element('div', 'tag-pills');
        const search = element('input');
        search.type = 'search';
        search.placeholder = 'Find an existing value…';
        search.setAttribute('aria-label', 'Find an existing value');
        search.autocomplete = 'off';
        const choices = element('select');
        choices.setAttribute('aria-label', 'Choose an existing value');
        choices.hidden = true;
        let available = new Map();
        function sync() {
          chips.replaceChildren();
          for (const id of selected) {
            const name = known.get(String(id)) || 'Unavailable selection';
            const chip = element('span', 'tag-pill', name);
            if (known.has(String(id)) && typeof window.applyArchiveBoxTagColor === 'function' && model === 'core.tag') {
              window.applyArchiveBoxTagColor(chip, name);
            }
            const remove = button('×', () => {
              selected.splice(selected.indexOf(id), 1);
              sync();
            }, 'tag-remove-btn');
            remove.setAttribute('aria-label', 'Remove ' + name);
            chip.append(remove);
            chips.append(chip);
          }
          (model === 'core.folder' ? choices : search).setCustomValidity(selected.length ? '' : 'Choose an existing value.');
          node.value = multiple ? selected.slice() : (selected[0] ?? null);
          serialize();
        }
        row.classList.add('rule-relation-value');
        if (model === 'core.folder') {
          // Folder relationships use the same paged path lookup as direct
          // folder rules. The chips keep the existing exact/in rule format.
          choices.hidden = false;
          choices.dataset.picker = 'folder';
          const placeholder = new Option('Choose a folder', '', true, true);
          placeholder.disabled = true;
          choices.add(placeholder);
          choices.addEventListener('change', () => {
            const id = choices.value;
            if (!id) return;
            known.set(id, choices.selectedOptions[0].text);
            if (!multiple) selected.length = 0;
            if (!selected.includes(id)) selected.push(id);
            choices.value = '';
            sync();
          });
          row.append(chips, choices);
          window.ArchiveBoxPicker.mount(choices);
          sync();
          return;
        }
        function show(results, emptyLabel = 'No matches') {
          available = new Map(results.filter(item => !selected.some(id => String(id) === String(item.id)))
            .map(item => [String(item.id), item]));
          choices.replaceChildren(new Option(available.size ? 'Select a result…' : emptyLabel, ''));
          for (const [key, item] of available) choices.add(new Option(item.name, key));
          choices.hidden = false;
        }
        const find = window.ArchiveBoxPicker.connect(
          search,
          window.ArchiveBoxPicker.lookup(null, () => ({ related_field: node.field }), folderForm.dataset.rulesUrl),
          ({choices: results = [], error}) => show(results, error ? 'Could not load choices' : 'No matches'),
        );
        search.addEventListener('focus', () => find());
        search.addEventListener('keydown', event => {
          if (event.key === 'ArrowDown' && !choices.hidden) {
            event.preventDefault();
            choices.focus();
          } else if (event.key === 'Enter') {
            event.preventDefault();
            if (!choices.hidden) choices.focus();
          }
        });
        choices.addEventListener('change', () => {
          const item = available.get(choices.value);
          if (!item) return;
          known.set(String(item.id), item.name);
          if (multiple) selected.push(item.id);
          else selected.splice(0, selected.length, item.id);
          search.value = '';
          choices.hidden = true;
          sync();
          search.focus();
        });
        row.append(chips, search, choices);
        sync();
      }

      function renderValue(row, node, spec) {
        if (['isnull','present'].includes(node.lookup)) return;
        if (spec.type === 'folder') {
          const options = node.lookup === 'in_children' ? [['self','This folder']] : [['*','ANY']];
          node.value ??= options[0][0];
          if (node.value !== options[0][0]) {
            options.push([node.value, labels.get('core.folder')?.get(String(node.value)) || 'Unavailable folder']);
          }
          const control = select(options, node.value, 'Folder', value => node.value=value);
          control.options[0].dataset.pickerFixed = '';
          control.dataset.picker = 'folder';
          row.append(control);
          window.ArchiveBoxPicker.mount(control);
        } else if (spec.related_model) {
          const model = schema.related_fields?.[spec.name];
          if (model && ['exact', 'in'].includes(node.lookup)) renderRelatedValues(row, node, model);
          else row.append(element('span', 'rule-legacy-value', 'Existing selection is not editable here.'));
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
          if (item.rules.length<2 || node === rules) {
            const toolbar=element('div','rule-group-toolbar');
            function append(child) {
              if (item.rules.length < 2) item.rules.push(child);
              else rules = {op:'AND', rules:[node, child]};
              render();
            }
            toolbar.append(button('+ Rule',() => append(defaultRule())),
              button('+ Group',() => append({op:'AND',rules:[defaultRule()]})));
            row.append(toolbar);
          }
        } else {
          const spec=specs.get(item.field) || specs.get('url');
          row.append(select(schema.fields.map(field => [field.name,field.label]),item.field,'Field',value => {
            const next = specs.get(value);
            item.field=value;
            item.lookup=next.related_model && !schema.related_fields?.[value] ? 'present' : next.operators[0];
            item.value=null;render();
          }));
          const polarity=select([['is','IS'],['not','IS NOT']],negated ? 'not' : 'is','Condition polarity',changePolarity);
          polarity.className='rule-polarity';row.append(polarity);
          const operators = spec.operators.filter(op => !negatives[op] && (
            !spec.related_model || op === item.lookup || (relationLookups.has(op) && (schema.related_fields?.[spec.name] || ['isnull', 'present'].includes(op)))
          ));
          row.append(select(operators.map(op => [op,({exact:'equal to',icontains:'containing',istartswith:'starting with',iendswith:'ending with',in:'one of',isnull:'empty',present:'present',in_folder:'in folder',in_children:'in children of'})[op] || schema.operators[op].replace(/^is /,'')]),item.lookup,'Comparison',value => {
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
        root.replaceChildren(); layout.hidden=kind.value !== 'smart' || dialog.dataset.mode==='move';
        const options = dialog.querySelector('.folder-options');
        options.replaceChildren(); options.hidden=layout.hidden;
        dialog.classList.toggle('has-rules', !layout.hidden);
        if (!layout.hidden) {
          if (rules) {
            const group=rules.op==='NOT' ? rules.rules[0] : rules;
            if (!group.op && !schema.container) rules={op:'AND',rules:[rules]};
            root.append(renderNode(rules,value => {rules=value;}));
            if (!schema.container) root.append(button('Remove advanced rules', () => {rules=null;render();}));
          } else {
            root.append(button('+ Rule', () => {rules={op:'AND',rules:[defaultRule()]};render();}));
          }
          if (schema.container) root.querySelectorAll('input,select,button').forEach(control => control.disabled=true);
          function option(label, control) {
            const wrapper=element('label','folder-option',label); wrapper.append(control); options.append(wrapper);
          }
          option('Sort by', select([...Object.entries(schema.sort_fields), ['?','Random']], sort.replace(/^-/, ''), 'Sort by', value => {
            sort=value==='?' ? '?' : (sort.startsWith('-') ? '-' : '')+value; render();
          }));
          if (sort!=='?') option('Direction', select([['desc','Descending'],['asc','Ascending']],sort.startsWith('-') ? 'desc' : 'asc','Sort direction', value => {
            sort=(value==='desc' ? '-' : '')+sort.replace(/^-/, '');
          }));
          const maximum=input('number',limit,'Limit',value => limit=value);
          maximum.required=false;maximum.min='1';maximum.step='1';maximum.inputMode='numeric';maximum.placeholder='No limit';
          option('Limit',maximum);
        }
        serialize();
      }
      kind.onchange = render;
      render();
    }
    let activeRename;
    function renameFolder(button) {
      if (activeRename?.busy) return;
      activeRename?.finish(false);
      const row = button.closest('.folder-row');
      const link = row.querySelector('a.folder-link');
      const label = link.querySelector('[data-folder-label]');
      const action = row.querySelector('.folder-menu-toggle');
      const status = sidebar.querySelector('.folder-drop-status');
      const originalName = row.dataset.folderName;
      const originalPath = link.title;
      const wasDraggable = row.draggable;
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'folder-inline-name';
      input.setAttribute('aria-label', 'Folder name');
      input.maxLength = 100;
      input.value = originalName;
      const editor = document.createElement('span');
      editor.className = 'library-link folder-link folder-inline-editor';
      if (!link.firstElementChild.matches('.folder-title-emoji')) editor.append(link.firstElementChild.cloneNode(true));
      editor.append(input);
      const state = activeRename = {
        busy: false,
        finish(focus = true) {
          link.hidden = false;
          editor.remove();
          row.draggable = wasDraggable;
          status.textContent = '';
          activeRename = null;
          if (focus) action.focus();
        },
      };

      button.closest('.folder-menu:popover-open')?.hidePopover();
      row.draggable = false;
      link.hidden = true;
      link.after(editor);
      input.focus();
      input.select();
      input.addEventListener('keydown', async event => {
        if (event.isComposing || !['Enter', 'Escape'].includes(event.key)) return;
        event.preventDefault();
        event.stopPropagation();
        if (state.busy) return;
        if (event.key === 'Escape' || input.value.trim() === originalName) return state.finish();
        if (!input.value.trim()) return;
        state.busy = input.readOnly = true;
        const body = new FormData();
        body.set('csrfmiddlewaretoken', folderForm.elements.csrfmiddlewaretoken.value);
        body.set('folder_id', row.dataset.folderId);
        body.set('name', input.value.trim());
        body.set('rename', '1');
        try {
          const response = await fetch(folderForm.action, {method:'POST', body, credentials:'same-origin'});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Could not rename folder.');
          const [emoji, name] = result.display;
          const icon = link.firstElementChild;
          if (emoji) {
            const lead = document.createElement('span');
            lead.className = 'folder-title-emoji';
            lead.setAttribute('aria-hidden', 'true');
            lead.textContent = emoji;
            icon.replaceWith(lead);
            link.setAttribute('aria-label', result.name);
          } else {
            if (icon.matches('.folder-title-emoji')) {
              const ns = 'http://www.w3.org/2000/svg';
              const svg = document.createElementNS(ns, 'svg');
              const use = document.createElementNS(ns, 'use');
              svg.setAttribute('aria-hidden', 'true');
              use.setAttribute('href', row.dataset.smart === 'true' ? '#library-smart' : '#library-folder');
              svg.append(use);
              icon.replaceWith(svg);
            }
            link.removeAttribute('aria-label');
          }
          label.textContent = name;
          link.title = result.path_label;
          row.dataset.folderName = result.name;
          for (const command of row.querySelectorAll('.folder-edit')) command.dataset.name = result.name;
          const menu = button.closest('.folder-menu');
          menu.setAttribute('aria-label', result.name);
          for (const control of row.querySelectorAll(':scope > .folder-toggle, :scope > .folder-row-actions [aria-label]')) {
            const aria = control.getAttribute('aria-label');
            if (!aria.endsWith(originalName)) continue;
            const next = aria.slice(0, -originalName.length) + result.name;
            control.setAttribute('aria-label', next);
            control.title = next;
          }
          // Keep loaded descendant paths correct without replacing lazy or expanded rows.
          for (const child of rows) {
            let ancestor = child.dataset.parentId;
            while (ancestor && ancestor !== row.dataset.folderId) ancestor = rowsById.get(ancestor)?.dataset.parentId;
            if (ancestor !== row.dataset.folderId) continue;
            const childLink = child.querySelector('a.folder-link');
            if (childLink?.title.startsWith(originalPath + ' / ')) {
              childLink.title = result.path_label + childLink.title.slice(originalPath.length);
            }
          }
          if (link.getAttribute('aria-current') === 'page') sidebar.querySelector('.folder-current').textContent = result.name;
          state.finish();
        } catch (error) {
          status.textContent = error.message;
          input.focus();
        } finally {
          state.busy = input.readOnly = false;
        }
      });
    }
    document.addEventListener('click', event => {
      const rename = event.target.closest('.folder-rename');
      if (rename) return renameFolder(rename);
      const button = event.target.closest('.folder-new,.folder-edit');
      if (button) openFolder(button);
    });
    dialog.querySelectorAll('.folder-dialog-close').forEach(button => button.addEventListener('click', () => dialog.close()));
    folderForm.addEventListener('submit', async event => {
      event.preventDefault();
      const save = folderForm.querySelector('[type=submit]');
      save.disabled = true;
      dialog.querySelector('.folder-form-error').textContent = '';
      try {
        const data = new FormData(folderForm);
        const refreshTree = sidebar && !data.get('folder_id');
        const url = new URL(folderForm.action);
        if (refreshTree) {
          data.set('refresh_tree', '1');
          url.search = location.search;
        }
        const response = await fetch(url, {method:'POST', body:data, credentials:'same-origin'});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not save folder.');
        if (picker) {
          const label = result.path_label;
          window.ArchiveBoxPicker.selectChoice(picker, result.id, label);
          picker.dispatchEvent(new Event('change', {bubbles:true}));
          dialog.close();
          picker.focus();
        } else if (refreshTree) {
          refreshFolderTree(result.folder_html, result.id, result.folder_next);
          dialog.close();
        } else {
          dialog.close();
          location.reload();
        }
      } catch (error) {dialog.querySelector('.folder-form-error').textContent = error.message;}
      finally {save.disabled = false;}
    });
  }
  function initializeMenus(root) {
    const groups = new Map();
    root.querySelectorAll('.folder-menu-toggle,.library-import-toggle,.library-export-toggle,.library-create-toggle,.library-mode-toggle,.library-sort-toggle').forEach(button => {
      const id = button.getAttribute('popovertarget');
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(button);
    });
    groups.forEach((buttons, id) => {
      let button = buttons[0];
      const menu = document.getElementById(id);
      if (menu.dataset.initialized) return;
      menu.dataset.initialized = 'true';
      const exports = menu.querySelectorAll('[data-export-format]');
      const deleteActions = [
        [menu.querySelector('[data-entry-delete-tag]'), 'deleteTagUrl'],
        [menu.querySelector('[data-entry-delete-snapshots]'), 'deleteSnapshotsUrl'],
      ];
      const deleteSeparator = menu.querySelector('[data-entry-delete-separator]');
      function activate(trigger) {
        button.setAttribute('aria-expanded', 'false');
        button = trigger;
        const entry = trigger.closest('.library-entry');
        if (!entry) return;
        menu.setAttribute('aria-label', entry.dataset.name);
        menu.dataset.entryValue = entry.dataset.filterValue;
        exports.forEach(link => {if (link.hasAttribute('href')) link.href = window.archiveboxExportURL(link);});
        const rename = menu.querySelector('[data-entry-rename]');
        if (rename) rename.hidden = !entry.dataset.tagRenameUrl;
        for (const [action, key] of deleteActions) {
          if (!action) continue;
          const url = entry.dataset[key];
          action.hidden = !url;
          if (action.form) action.form.action = url || '';
          else if (url) action.href = url;
          else action.removeAttribute('href');
        }
        if (deleteSeparator) deleteSeparator.hidden = !deleteActions.some(([action]) => action && !action.hidden);
      }
      if (id === 'library-entry-menu') {
        menu.querySelector('[data-entry-rename]')?.addEventListener('click', () => {
          const entry = button.closest('[data-tag-rename-url]');
          if (!entry) return;
          menu.hidePopover();
          entry.dispatchEvent(new CustomEvent('archivebox:tag-rename', {bubbles:true}));
        });
        document.addEventListener('click', event => {
          const trigger = event.target.closest('[popovertarget="library-entry-menu"]');
          if (trigger) activate(trigger);
        });
        document.addEventListener('keydown', event => {
          const trigger = event.target.closest('[popovertarget="library-entry-menu"]');
          if (trigger && ['ArrowDown','ArrowUp'].includes(event.key)) {
            event.preventDefault(); activate(trigger); menu.showPopover();
          }
        });
      } else buttons.forEach(trigger => trigger.addEventListener('click', () => activate(trigger)));
      const items = [...menu.querySelectorAll('[role=menuitem], [role=menuitemradio]')];
      const removal = menu.querySelector('.folder-delete-snapshots');
      let removalGeneration = 0;
      async function refreshRemoval() {
        if (!removal || !folderForm) return;
        const generation = ++removalGeneration;
        removal.removeAttribute('href');
        removal.dataset.action = '';
        removal.setAttribute('aria-disabled', 'true');
        removal.querySelector('.folder-menu-label').textContent = 'Checking folder…';
        try {
          const url = new URL(folderForm.dataset.deleteUrl, location.href);
          url.searchParams.set('intent', 'empty_only');
          url.searchParams.set('folder_id', removal.dataset.folderId);
          const response = await fetch(url, {credentials:'same-origin'});
          if (!response.ok) throw new Error('Could not check folder.');
          const state = await response.json();
          if (['has_snapshots','has_children','can_delete'].some(key => typeof state[key] !== 'boolean')) throw new Error('Invalid folder state.');
          if (generation !== removalGeneration || !menu.matches(':popover-open')) return;
          removal.querySelector('.folder-menu-label').textContent = state.has_snapshots ? 'Delete snapshots' : 'Delete folder';
          if (state.has_snapshots && removal.dataset.canDeleteSnapshots === 'true') {
            removal.href = removal.dataset.deleteSnapshotsUrl;
            removal.dataset.action = 'snapshots';
          } else if (!state.has_snapshots && state.can_delete && !state.has_children) {
            removal.dataset.action = 'folder';
          }
          removal.title = state.has_children && !state.has_snapshots ? 'Move or delete child folders first.' : '';
          removal.setAttribute('aria-disabled', String(!removal.dataset.action));
        } catch (_error) {
          if (generation === removalGeneration) removal.querySelector('.folder-menu-label').textContent = 'Could not check folder';
        }
      }
      removal?.addEventListener('click', async event => {
        if (removal.dataset.action === 'snapshots') return;
        event.preventDefault();
        if (removal.dataset.action !== 'folder') return;
        if (!window.confirm(`Delete empty folder “${menu.getAttribute('aria-label')}”?`)) return;
        removal.dataset.action = '';
        removal.setAttribute('aria-disabled', 'true');
        const data = new FormData(folderForm);
        data.set('folder_id', removal.dataset.folderId);
        data.set('intent', 'empty_only');
        try {
          const response = await fetch(folderForm.dataset.deleteUrl, {method:'POST',body:data,credentials:'same-origin'});
          const result = await response.json();
          if (!response.ok || !result.deleted) throw new Error(result.error || 'Could not delete folder.');
          const url = new URL(location.href);
          if (url.searchParams.get('folder') === removal.dataset.folderId) url.searchParams.delete('folder');
          location.assign(url.href);
        } catch (error) { window.alert(error.message); await refreshRemoval(); }
      });
      removal?.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); removal.click();}
      });
      function positionMenu() {
        const rect = button.getBoundingClientRect();
        const box = menu.getBoundingClientRect();
        menu.style.left = `${Math.max(8, Math.min(innerWidth - box.width - 8, rect.right - box.width))}px`;
        const top = rect.bottom + box.height + 12 <= innerHeight ? rect.bottom + 4 : rect.top - box.height - 4;
        menu.style.top = `${Math.max(8, Math.min(innerHeight - box.height - 8, top))}px`;
      }
      // The browser opens the popover before it delivers toggle. Measure it
      // while invisible so even a reused menu first appears at its new trigger.
      menu.addEventListener('beforetoggle', event => {
        if (event.newState === 'open') menu.removeAttribute('data-positioned');
      });
      function syncMenu(open) {
        if (open && menu.hasAttribute('data-positioned')) return;
        button.setAttribute('aria-expanded', String(open));
        button.closest('.library-entry')?.classList.toggle('has-open-menu', open);
        if (open) {
          refreshRemoval();
          positionMenu();
          menu.setAttribute('data-positioned', '');
          // Keep the first focused item visible when a tall menu is reopened.
          menu.scrollTop = 0;
          items.find(item => !item.hidden)?.focus({preventScroll:true});
          window.addEventListener('resize', positionMenu);
          window.addEventListener('scroll', positionMenu, true);
        } else {
          removalGeneration++;
          window.removeEventListener('resize', positionMenu);
          window.removeEventListener('scroll', positionMenu, true);
        }
      }
      menu.addEventListener('toggle', event => syncMenu(event.newState === 'open'));
      // Native triggers can open a menu before this deferred script has run.
      if (menu.matches(':popover-open')) syncMenu(true);
      if (id !== 'library-entry-menu') buttons.forEach(trigger => trigger.addEventListener('keydown', event => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          activate(trigger);
          if (!menu.matches(':popover-open')) menu.showPopover();
        }
      }));
      menu.addEventListener('keydown', event => {
        if (event.target.matches("[data-tag-merge-input]")) return;
        if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
          event.preventDefault();
          const visibleItems = items.filter(item => !item.hidden);
          const index = visibleItems.indexOf(document.activeElement);
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? visibleItems.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + visibleItems.length) % visibleItems.length;
          visibleItems[next]?.focus();
        } else if (event.key === 'Tab') menu.hidePopover();
      });
    });
  }
  window.archiveboxInitDomainRows = root => {
    initializeMenus(root);
    if (window.archiveboxLibraryLayout) {
      root.querySelectorAll('.domain-personas .tag-pills-inline').forEach(window.archiveboxLibraryLayout.bindCompactTags);
    }
  };
  window.archiveboxInitDomainRows(document);
  if (!sidebar) return;
  let form = document.querySelector('#changelist-form');
  function confirmScopedSnapshotDeletion() {
    if (location.hash !== '#delete-snapshots' || !['folder','tag','domain','persona','importer','crawl_schedule','crawl'].some(key => new URLSearchParams(location.search).has(key))) return false;
    const currentForm = document.querySelector('#changelist-form');
    const action = currentForm?.querySelector('select[name=action]');
    const selection = currentForm?.querySelector('input.action-select');
    const across = currentForm?.querySelector('input[name=select_across]');
    const submit = currentForm?.querySelector('button[name=index]');
    if (!selection || !across || !submit || !action?.querySelector('option[value=delete_selected]')) return false;
    history.replaceState(null, '', location.pathname + location.search);
    selection.checked = true;
    across.value = '1';
    action.value = 'delete_selected';
    // Django's existing action displays confirmation before requesting deletion.
    currentForm.requestSubmit(submit);
    return true;
  }
  window.addEventListener('hashchange', confirmScopedSnapshotDeletion);
  if (confirmScopedSnapshotDeletion()) return;
  const status = sidebar.querySelector('.folder-drop-status');
  const tree = sidebar.querySelector('.folder-tree');
  const folderMode = sidebar.dataset.mode === 'folders';
  const treeNavigation = sidebar.hasAttribute('data-tree-navigation');
  const objectMode = treeNavigation && !folderMode;
  const search = sidebar.querySelector('.folder-search');
  const empty = sidebar.querySelector('.folder-search-empty');
  const more = sidebar.querySelector('.library-load-more');
  const loading = sidebar.querySelector('.library-load-status');
  const folderPath = (sidebar.dataset.folderPath || '').split(',').filter(Boolean);
  more.dataset.cursor = sidebar.dataset.next || '';
  let sidebarQuery = search.value;
  let pageRequests = new AbortController();
  let searchTimer;
  const pendingPages = new Set();
  let loadError = '';
  let rows = [...sidebar.querySelectorAll('.folder-row')];
  let rowsById = new Map(rows.map(row => [row.dataset.folderId, row]));
  const folderExpansionKey = folderMode ? 'archivebox.folder-expansion' : `archivebox.library-expansion.${sidebar.dataset.mode}`;
  const folderExpansion = new Map();
  const searchCollapsed = new Set();
  try {
    const saved = JSON.parse(localStorage.getItem(folderExpansionKey) || '{}');
    (saved.expanded || []).forEach(id => folderExpansion.set(id, true));
    (saved.collapsed || []).forEach(id => folderExpansion.set(id, false));
  } catch (_) {}
  const revealedFolders = new Set(folderPath.filter(id => folderExpansion.get(id) !== false));

  function saveFolderExpansion() {
    const expanded = [], collapsed = [];
    for (const [id, open] of folderExpansion) (open ? expanded : collapsed).push(id);
    try {localStorage.setItem(folderExpansionKey, JSON.stringify({expanded, collapsed}));} catch (_) {}
  }
  function isFolderExpanded(id) {
    return sidebarQuery && folderMode ? !searchCollapsed.has(id) : revealedFolders.has(id) || folderExpansion.get(id) === true;
  }

  function initializeTreeRows() {
    rows.forEach(row => {
      if (row.dataset.treeInitialized) return;
      row.dataset.treeInitialized = 'true';
      if (row.hasAttribute('data-expanded')) revealedFolders.add(row.dataset.folderId);
      const toggle = row.querySelector('.folder-toggle');
      if (!toggle) return;
      row.querySelector('.library-branch-label')?.addEventListener('click', () => toggle.click());
      toggle.addEventListener('click', () => {
        const id = row.dataset.folderId;
        const open = !isFolderExpanded(id);
        if (sidebarQuery && folderMode) {
          if (open) searchCollapsed.delete(id);
          else searchCollapsed.add(id);
        } else {
          revealedFolders.delete(id);
          folderExpansion.set(id, open);
          saveFolderExpansion();
          if (open && !row.dataset.childrenLoaded) loadChildren(row);
        }
        renderTree();
      });
    });
  }
  initializeTreeRows();
  function renderTree() {
    if (!treeNavigation) return;
    const loadedParents = sidebarQuery && folderMode ? new Set(rows.map(row => row.dataset.parentId)) : null;
    rows.forEach(row => {
      let parent = row.dataset.parentId;
      let hidden = false;
      while (parent) {
        if (!isFolderExpanded(parent)) hidden = true;
        parent = rowsById.get(parent)?.dataset.parentId;
      }
      row.hidden = hidden;
      const toggle = row.querySelector('.folder-toggle');
      if (toggle) {
        const expanded = isFolderExpanded(row.dataset.folderId) && (!loadedParents || loadedParents.has(row.dataset.folderId));
        const label = `${expanded ? 'Collapse' : 'Expand'} ${row.dataset.folderName}`;
        toggle.setAttribute('aria-expanded', String(expanded));
        row.querySelector('.library-branch-label')?.setAttribute('aria-expanded', String(expanded));
        toggle.setAttribute('aria-label', label);
        toggle.title = label;
        if (expanded && !hidden && (!sidebarQuery || !folderMode) && !row.dataset.childrenRequested) loadChildren(row);
      }
    });
    sidebar.querySelectorAll('.library-child-more').forEach(button => {
      let parent = button.dataset.parent;
      let hidden = false;
      while (parent) {if (!isFolderExpanded(parent)) hidden = true; parent = rowsById.get(parent)?.dataset.parentId;}
      button.hidden = hidden || !button.dataset.cursor;
    });
  }
  function refreshFolderTree(html, createdId, next) {
    if (sidebarQuery || searchTimer !== undefined) {
      searchSidebar();
    } else {
      const fragment = document.createElement('template');
      fragment.innerHTML = html;
      resetPageRequests();
      replaceTree(fragment.content, next);
      refreshRows();
      let parent = rowsById.get(createdId)?.dataset.parentId;
      while (parent) {
        revealedFolders.add(parent);
        parent = rowsById.get(parent)?.dataset.parentId;
      }
      loading.hidden = true;
      renderTree();
    }

  }
  function refreshRows() {
    rows = [...tree.querySelectorAll('.folder-row')];
    rowsById = new Map(rows.map(row => [row.dataset.folderId, row]));
    initializeTreeRows();
    initializeMenus(sidebar);
    if (sidebar.dataset.moveUrl && folderMode) {
      const fresh = rows.filter(row => !row.dataset.dragInitialized);
      initializeFolderDragging(fresh); initializeDropTargets(fresh);
      fresh.forEach(row => row.dataset.dragInitialized = 'true');
    }
  }
  function resetPageRequests() {
    pageRequests.abort();
    pageRequests = new AbortController();
    pendingPages.clear();
    more.disabled = false;
    loadError = '';
  }
  function replaceTree(fragment, next = '') {
    tree.querySelectorAll('.library-child-more').forEach(button => observer.unobserve(button));
    tree.replaceChildren(fragment, more);
    more.dataset.cursor = next;
    more.hidden = !next;
  }
  function appendSearchFolders(fragment) {
    // A later page can have more children of a folder from an earlier page.
    const branchEnds = new Map();
    function recordBranchEnd(row) {
      for (let ancestor = row; ancestor; ancestor = rowsById.get(ancestor.dataset.parentId)) {
        const id = ancestor.dataset.folderId;
        const end = branchEnds.get(id);
        if (end && (row.compareDocumentPosition(end) & Node.DOCUMENT_POSITION_FOLLOWING)) break;
        branchEnds.set(id, row);
      }
    }
    rows.forEach(recordBranchEnd);
    for (const row of fragment.querySelectorAll('.folder-row')) {
      const id = row.dataset.folderId;
      if (rowsById.has(id)) continue;
      const parentEnd = branchEnds.get(row.dataset.parentId);
      if (parentEnd) parentEnd.after(row);
      else more.before(row);
      rowsById.set(id, row);
      recordBranchEnd(row);
    }
  }
  async function loadPage(button, replace=false) {
    if (button.disabled || (!replace && button.hidden) || !tree.contains(button)) return;
    const signal = pageRequests.signal;
    button.disabled = true;
    if (!pendingPages.size) loadError = '';
    pendingPages.add(button);
    loading.hidden = false; loading.textContent = 'Loading…';
    try {
      const url = new URL(sidebar.dataset.sidebarUrl, location.href);
      url.search = location.search;
      url.searchParams.set('sidebar', sidebar.dataset.mode);
      url.searchParams.set('sidebar_q', sidebarQuery);
      url.searchParams.delete('cursor');
      url.searchParams.delete('parent');
      if (!replace && button.dataset.cursor) url.searchParams.set('cursor', button.dataset.cursor);
      if (button.dataset.parent) url.searchParams.set('parent', button.dataset.parent);
      const response = await fetch(url, {credentials:'same-origin', signal});
      if (!response.ok) throw new Error('Could not load sidebar.');
      const result = await response.json();
      if (signal.aborted) return;
      const fragment = document.createElement('template');
      fragment.innerHTML = result.html;
      if (replace) {
        replaceTree(fragment.content, result.next);
      } else {
        if (sidebarQuery && treeNavigation && !button.dataset.parent) {
          appendSearchFolders(fragment.content);
        } else {
          fragment.content.querySelectorAll('.folder-row').forEach(row => {
            if (rowsById.has(row.dataset.folderId)) row.remove();
          });
          button.before(fragment.content);
        }
        button.dataset.cursor = result.next;
        button.hidden = !result.next;
        if (button.dataset.parent) rowsById.get(button.dataset.parent).dataset.childrenLoaded = 'true';
      }
      refreshRows();
      renderTree();
      empty.hidden = !sidebarQuery || Boolean(result.next || tree.querySelector('.folder-row, .library-entry'));
      observer.unobserve(button);
      if (!button.hidden) observer.observe(button);
    } catch (error) {
      if (!signal.aborted) loadError = error.message;
    } finally {
      if (!signal.aborted) {
        button.disabled = false;
        pendingPages.delete(button);
        if (!pendingPages.size) {
          loading.hidden = !loadError;
          if (loadError) loading.textContent = loadError;
        }
      }
    }
  }
  function loadChildren(row) {
    if ((sidebarQuery && folderMode) || !tree.contains(row)) return;
    row.dataset.childrenRequested = 'true';
    let button = [...tree.querySelectorAll('.library-child-more')].find(item => item.dataset.parent === row.dataset.folderId);
    if (!button) {
      button = document.createElement('button'); button.type = 'button';
      button.className = 'library-child-more'; button.textContent = 'Load more';
      button.dataset.parent = row.dataset.folderId;
      button.dataset.cursor = row.dataset.childrenNext || '';
      let branchEnd = row;
      for (let next = row.nextElementSibling; next?.classList.contains('folder-row'); next = next.nextElementSibling) {
        let parent = next.dataset.parentId;
        while (parent && parent !== row.dataset.folderId) parent = rowsById.get(parent)?.dataset.parentId;
        if (!parent) break;
        branchEnd = next;
      }
      branchEnd.after(button);
      button.addEventListener('click', () => loadPage(button));
      observer.observe(button);
    }
    button.hidden = false;
    return loadPage(button);
  }
  const observer = new IntersectionObserver(items => {
    for (const item of items) if (item.isIntersecting && item.target.dataset.cursor) loadPage(item.target);
  }, {root:tree, rootMargin:'100px'});
  observer.observe(more);
  more.addEventListener('click', () => loadPage(more));
  function searchSidebar() {
    clearTimeout(searchTimer);
    resetPageRequests();
    sidebarQuery = search.value.trim();
    searchCollapsed.clear();
    replaceTree(document.createDocumentFragment());
    rows = [];
    rowsById.clear();
    empty.hidden = true;
    loading.hidden = false;
    loading.textContent = 'Loading…';
    searchTimer = setTimeout(() => {
      searchTimer = undefined;
      loadPage(more, true);
    }, 25);
  }
  const sortMenu = sidebar.querySelector('#library-sort-menu');
  sortMenu?.addEventListener('click', event => {
    const choice = event.target.closest('[data-sidebar-sort]');
    if (!choice) return;
    sortMenu.hidePopover();
    sidebar.querySelector('.library-sort-toggle').focus({preventScroll: true});
    if (choice.getAttribute('aria-checked') === 'true') return;
    const sort = choice.dataset.sidebarSort;
    const setSort = url => {
      if (sort === 'count') url.searchParams.delete('sidebar_sort');
      else url.searchParams.set('sidebar_sort', sort);
      return url;
    };
    history.replaceState(history.state, '', setSort(new URL(location.href)));
    sidebar.querySelectorAll('.library-root-link, [data-sidebar-mode-link="tags"], [data-sidebar-mode-link="domains"]').forEach(link => {
      link.href = setSort(new URL(link.href));
    });
    sortMenu.querySelectorAll('[data-sidebar-sort]').forEach(item => {
      item.setAttribute('aria-checked', String(item === choice));
    });
    searchSidebar();
  });
  const deleteTagForm = sidebar.querySelector('#library-tag-delete-form');
  deleteTagForm?.addEventListener('submit', async event => {
    const menu = deleteTagForm.closest('.folder-menu');
    const tagId = menu.dataset.entryValue;
    deleteTagForm.elements.return_to.value = location.pathname + location.search;
    const filters = new URLSearchParams(location.search);
    if (['tag', 'tags__id__exact'].some(key => filters.get(key) === tagId)) return;
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const response = await fetch(deleteTagForm.action, {
        method: 'POST',
        body: new FormData(deleteTagForm),
        headers: {Accept: 'application/json'},
        credentials: 'same-origin',
      });
      if (!response.ok || !(await response.json()).deleted) throw new Error('Could not delete tag.');
      menu.hidePopover();
      document.dispatchEvent(new CustomEvent('archivebox:tag-deleted', {detail: tagId}));
      status.textContent = 'Tag deleted.';
      searchSidebar();
    } catch {
      status.textContent = 'Could not delete tag.';
    } finally {
      button.disabled = false;
    }
  });
  search.addEventListener('input', () => {
    if (sidebarQuery || search.value.trim()) searchSidebar();
  });
  const searchToggle = sidebar.querySelector('.folder-search-toggle');
  const sectionLabel = sidebar.querySelector('.folder-section-label');
  function toggleFolderSearch(open) {
    search.hidden = !open;
    sectionLabel.hidden = open;
    searchToggle.setAttribute('aria-expanded', String(open));
    searchToggle.setAttribute('aria-label', open ? 'Close sidebar search' : search.getAttribute('aria-label'));
    searchToggle.title = open ? 'Close sidebar search' : search.getAttribute('aria-label');
    if (open) search.focus();
    else {
      search.value = '';
      if (sidebarQuery) searchSidebar();
      searchToggle.focus();
    }
  }
  if (sidebarQuery) toggleFolderSearch(true);
  searchToggle.addEventListener('click', () => toggleFolderSearch(search.hidden));
  const tagName = sidebar.querySelector('.library-tag-name');
  const addTag = tagName ? sidebar.querySelector('.library-add') : null;
  if (addTag) {
    let previousSearchOpen = false;
    function toggleTagInput(open) {
      if (tagName.disabled) return;
      if (open) previousSearchOpen = !search.hidden;
      tagName.hidden = !open;
      search.hidden = open || !previousSearchOpen;
      sectionLabel.hidden = open || previousSearchOpen;
      searchToggle.hidden = open;
      addTag.setAttribute('aria-expanded', String(open));
      addTag.setAttribute('aria-label', open ? 'Cancel new tag' : 'Add tag');
      addTag.title = open ? 'Cancel new tag' : 'Add tag';
      if (open) {tagName.value = ''; tagName.focus();}
      else {
        if (searchTimer === undefined && !pendingPages.size) loading.hidden = true;
        addTag.focus();
      }
    }
    addTag.addEventListener('click', () => toggleTagInput(tagName.hidden));
    tagName.addEventListener('keydown', async event => {
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation(); toggleTagInput(false); return;
      }
      if (event.key !== 'Enter' || event.isComposing || tagName.disabled) return;
      event.preventDefault();
      if (!tagName.value.trim() || !tagName.reportValidity()) return;
      tagName.disabled = true; addTag.disabled = true;
      loading.hidden = false; loading.textContent = 'Creating tag…';
      try {
        const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
        const response = await fetch(tagName.dataset.createUrl, {
          method:'POST', credentials:'same-origin',
          headers:{'Content-Type':'application/json', 'X-CSRFToken':csrf},
          body:JSON.stringify({name:tagName.value.trim()}),
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.detail || 'Could not create tag.');
        tagName.disabled = false;
        toggleTagInput(false);
        search.value = result.tag_name;
        toggleFolderSearch(true);
        searchSidebar();
      } catch (error) {
        loading.textContent = error.message; loading.hidden = false;
      } finally {tagName.disabled = false; addTag.disabled = false;}
    });
  }
  search.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      toggleFolderSearch(false);
    }
  });
  const mobileToggle = sidebar.querySelector('.folder-mobile-toggle');
  const sidebarLayout = window.archiveboxLibraryLayout.initializeSidebar(sidebar);
  const mobileViewport = sidebarLayout.viewport;
  let sidebarDwellTimer = null;
  function clearSidebarDwell() {
    clearTimeout(sidebarDwellTimer);
    sidebarDwellTimer = null;
  }
  function viewportChanged() {
    if (mobileViewport.matches) clearSidebarDwell();
    sidebarLayout.apply();
  }
  mobileViewport.addEventListener('change', viewportChanged);
  viewportChanged();
  mobileToggle.addEventListener('click', () => {
    if (mobileViewport.matches) {
      sidebarLayout.mobileCollapsed = !sidebarLayout.mobileCollapsed;
      if (sidebarLayout.mobileCollapsed && !search.hidden) toggleFolderSearch(false);
    }
    else {
      sidebarLayout.desktopHidden = true;
      try {localStorage.setItem('archivebox.sidebar-hidden', 'true');} catch (_) {}
    }
    viewportChanged();
    if (!mobileViewport.matches) document.querySelector('.folder-sidebar-reopen').focus();
  });
  function showDesktopSidebar() {
    sidebarLayout.desktopHidden = false;
    try {localStorage.setItem('archivebox.sidebar-hidden', 'false');} catch (_) {}
    viewportChanged();
  }
  document.addEventListener('click', event => {
    if (!event.target.closest('.folder-sidebar-reopen')) return;
    showDesktopSidebar();
    mobileToggle.focus();
  });
  renderTree();
  // Public folders share navigation and exports, but have no move endpoint.
  if (!sidebar.dataset.moveUrl) return;

  function selectionChanged() {
    const checked = form?.querySelector('input.action-select:checked');
    document.querySelectorAll('.actions-folder').forEach(field => {field.hidden = !checked;});
  }
  document.addEventListener('change', selectionChanged);
  let dragging = false;
  let movingFolder = null;
  let expandTimer;
  let badge;
  function clearDrag() {
    dragging = false;
    movingFolder = null;
    clearSidebarDwell();
    clearDropTarget();
    document.body.classList.remove('dragging-snapshots');
    document.querySelectorAll('.snapshot-dragging,.drop-active,.drop-before,.drop-after').forEach(node => node.classList.remove('snapshot-dragging','drop-active','drop-before','drop-after'));
    badge?.remove();
  }
  // Reveal the desktop sidebar without focusing a control or changing the drop.
  function updateSidebarDwell(event) {
    if (!dragging || !event.dataTransfer?.types.includes('application/x-archivebox-snapshots') ||
        !sidebarLayout.desktopHidden || mobileViewport.matches || event.clientX < 0 || event.clientX > 18) {
      clearSidebarDwell();
      return;
    }
    if (sidebarDwellTimer !== null) return;
    sidebarDwellTimer = setTimeout(() => {
      sidebarDwellTimer = null;
      if (!dragging || !sidebarLayout.desktopHidden || mobileViewport.matches) return;
      showDesktopSidebar();
    }, 1000);
  }
  document.addEventListener('dragenter', updateSidebarDwell);
  document.addEventListener('dragover', updateSidebarDwell);
  document.addEventListener('dragleave', event => {
    if (!event.relatedTarget) clearSidebarDwell();
  });
  document.addEventListener('drop', clearSidebarDwell, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') clearSidebarDwell();
  });
  function initializeSnapshotDragging(root = form) {
    root?.querySelectorAll('input.action-select').forEach(checkbox => {
      const row = checkbox.closest('tr,.card');
      if (!row) return;
      row.draggable = true;
      // Images and links otherwise start their own native drag instead of moving
      // the selected snapshots. Clicking those links still works normally.
      row.querySelectorAll('a,img').forEach(element => {element.draggable = false;});
      row.addEventListener('dragstart', event => {
        const target = event.target instanceof Element ? event.target : event.target.parentElement;
        if (target?.closest('button,input,select,.tag-editor-container,.tag-editor-inline')) {event.preventDefault(); return;}
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
  }
  function initializeFolderDragging(folderRows) {
    folderRows.forEach(row => {
      row.draggable = true;
      row.addEventListener('dragstart', event => {
        const target = event.target instanceof Element ? event.target : event.target.parentElement;
        if (target?.closest('button,input')) {event.preventDefault(); return;}
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
  }
  if (folderMode) {
    initializeFolderDragging(rows);
    rows.forEach(row => row.dataset.dragInitialized = 'true');
  }
  const rootTarget = sidebar.querySelector('.library-root-link');
  rootTarget.dataset.folderId = '';
  if (!objectMode) rootTarget.classList.add('folder-drop-target');
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
  function initializeDropTargets(targets) {
    targets.forEach(target => {
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
        if (position === 'inside' && !sidebarQuery && !isFolderExpanded(target.dataset.folderId) && target.querySelector('.folder-toggle') && !expandTimer) {
          expandTimer = setTimeout(() => {
            revealedFolders.add(target.dataset.folderId);
            if (!target.dataset.childrenLoaded) loadChildren(target);
            renderTree();
            expandTimer = null;
          }, 600);
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
              if (ancestor.dataset.folderId) folderExpansion.set(ancestor.dataset.folderId, true);
              ancestor = rows.find(row => row.dataset.folderId === ancestor.dataset.parentId);
            }
            saveFolderExpansion();
            location.reload();
          } catch (error) {status.textContent = error.message;}
          return;
        }
        const destination = form.querySelector('[name=folder_destination]');
        const action = form.querySelector('select[name=action]');
        if (!destination || !action) {clearDrag(); status.textContent = 'Folder moves are unavailable for this account.'; return;}
        const id = target.dataset.smart === 'true' && target.dataset.container !== 'true' ? '' : target.dataset.folderId;
        window.ArchiveBoxPicker.selectChoice(destination, id, target.querySelector('.folder-link')?.title || target.dataset.folderName);
        action.value = 'move_to_folder';
        clearDrag(); status.textContent = 'Moving snapshots…';
        form.requestSubmit(form.querySelector('button[name=index]'));
      });
    });
  }
  initializeDropTargets(sidebar.querySelectorAll('.folder-drop-target'));
  let initializedForm;
  window.archiveboxInitLibraryRows = added => {
    if (added && form === initializedForm) {
      window.archiveboxLibraryLayout?.initializeTags(form, added);
      for (const row of added) {
        if (!objectMode) initializeSnapshotDragging(row);
        window.ArchiveBoxPicker.initialize(row);
      }
      return;
    }
    viewportChanged();
    form = document.querySelector('#changelist-form');
    if (form !== initializedForm) {
      initializedForm = form;
      if (dragging) {
        clearDrag();
        status.textContent = '';
      }
      window.archiveboxLibraryLayout?.initializeTags(form);
      if (form) window.ArchiveBoxPicker.initialize(form);
      if (!objectMode) initializeSnapshotDragging();
    }
    selectionChanged();
  };
  window.archiveboxInitLibraryRows();
});
