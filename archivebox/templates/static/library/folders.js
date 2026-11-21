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
      folderForm.elements.parent.value = button.dataset.parent || picker?.value || '';
      document.querySelector('#folder-dialog-title').textContent = moving ? 'Move folder' : button.dataset.id ? (button.dataset.smart === 'true' ? 'Edit smart folder rules' : 'Edit folder') : button.dataset.smart === 'true' ? 'New smart folder' : 'New folder';
      const subtitle = dialog.querySelector('#folder-dialog-subtitle');
      subtitle.hidden = moving || Boolean(button.dataset.id) || button.dataset.smart !== 'true';
      if (subtitle.hidden) dialog.removeAttribute('aria-describedby');
      else dialog.setAttribute('aria-describedby', subtitle.id);
      dialog.querySelector('.folder-form-error').textContent = '';
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
      function schedulePreview() {
        const serialized = folderForm.elements.rules.value;
        if (serialized === lastPreview) return;
        lastPreview = serialized;
        cancelPreview();
        matches.replaceChildren();
        if (!serialized || layout.hidden || layout.querySelector(':invalid') || dialog.querySelector('.folder-options :invalid')) return;
        previewTimer = setTimeout(async () => {
          if (!dialog.open || version !== editorVersion) return;
          const controller = new AbortController();
          previewRequest = controller;
          const body = new FormData();
          for (const name of ['csrfmiddlewaretoken', 'folder_id', 'parent']) body.set(name, folderForm.elements[name].value);
          body.set('rules', serialized);
          matches.replaceChildren(element('p', '', 'Loading…'));
          try {
            const response = await fetch(folderForm.dataset.rulesUrl, {method:'POST', body, credentials:'same-origin', signal:controller.signal});
            const result = await response.json();
            if (controller.signal.aborted || !dialog.open || version !== editorVersion) return;
            if (!response.ok) {
              matches.replaceChildren(element('p', '', result.error || 'Preview unavailable.'));
              return;
            }
            if (!result.snapshots.length) {
              matches.replaceChildren(element('p', '', 'No matching snapshots.'));
              return;
            }
            matches.replaceChildren(...result.snapshots.map(snapshot => {
              const row = element('div', 'folder-match');
              const monogram = element('span', 'folder-match-icon', (snapshot.domain || '?').slice(0, 1).toUpperCase());
              monogram.setAttribute('aria-hidden', 'true');
              const text = element('div', 'folder-match-body');
              text.append(element('strong', '', snapshot.title || snapshot.domain),
                element('small', '', [snapshot.domain, snapshot.date].filter(Boolean).join(' · ')));
              row.append(monogram, text);
              return row;
            }));
          } catch (_) {
            if (!controller.signal.aborted && dialog.open && version === editorVersion)
              matches.replaceChildren(element('p', '', 'Preview unavailable.'));
          }
        }, 300);
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
      const {limit: savedLimit, sort: savedSort, ...predicate} = schema.rules || {};
      let limit = savedLimit ?? '', sort = savedSort || '-created_at';
      let rules = normalize(schema.rules ? predicate : {op:'AND', rules:[defaultRule()]});
      const specs = new Map(schema.fields.map(field => [field.name, field]));
      const relationLookups = new Set(['exact', 'in', 'isnull', 'present']);
      const labels = new Map(Object.entries(schema.related_selected || {}).map(([model, choices]) =>
        [model, new Map(choices.map(choice => [String(choice.id), choice.name]))]));
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
        const options = {...(limit !== '' ? {limit:Number(limit)} : {}), ...(sort !== '-created_at' ? {sort} : {})};
        folderForm.elements.rules.value = kind.value === 'smart' ? JSON.stringify({...compact(rules), ...options}) : '';
        schedulePreview();
      }
      function input(type, value, label, change) {
        const control = element('input'); control.type = type; control.value = value ?? '';
        control.setAttribute('aria-label', label); control.required = true;
        if (type === 'number') {control.step='any';control.inputMode='decimal';}
        control.addEventListener('input', () => {change(control.value); serialize();});
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
        let timer, controller;
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
          search.setCustomValidity(selected.length ? '' : 'Choose an existing value.');
          node.value = multiple ? selected.slice() : (selected[0] ?? null);
          serialize();
        }
        function show(results, emptyLabel = 'No matches') {
          available = new Map(results.filter(item => !selected.some(id => String(id) === String(item.id)))
            .map(item => [String(item.id), item]));
          choices.replaceChildren(new Option(available.size ? 'Select a result…' : emptyLabel, ''));
          for (const [key, item] of available) choices.add(new Option(item.name, key));
          choices.hidden = false;
        }
        function find() {
          window.clearTimeout(timer);
          controller?.abort();
          const query = search.value.trim();
          show([], 'Searching…');
          timer = window.setTimeout(async () => {
            const request = new AbortController();
            controller = request;
            try {
              const url = new URL(folderForm.dataset.rulesUrl, location.href);
              url.searchParams.set('related_field', node.field);
              url.searchParams.set('q', query);
              const response = await fetch(url, {credentials:'same-origin', signal:request.signal});
              if (!response.ok) throw new Error('Lookup failed');
              const payload = await response.json();
              if (!request.signal.aborted && search.isConnected) show(payload.choices);
            } catch (error) {
              if (!request.signal.aborted && search.isConnected) show([], 'Could not load choices');
            }
          }, 140);
        }
        search.addEventListener('focus', find);
        search.addEventListener('input', find);
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
        row.classList.add('rule-relation-value');
        row.append(chips, search, choices);
        sync();
      }

      function renderValue(row, node, spec) {
        if (['isnull','present'].includes(node.lookup)) return;
        if (spec.type === 'folder') {
          const options = node.lookup === 'in_children' ? [['self','This folder']] : [['*','ANY']];
          options.push(...schema.folders.map(folder => [folder.id, folder.name]));
          node.value ??= options[0][0];
          row.append(select(options, node.value, 'Folder', value => node.value=value));
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
          const group=rules.op==='NOT' ? rules.rules[0] : rules;
          if (!group.op && !schema.container) rules={op:'AND',rules:[rules]};
          root.append(renderNode(rules,value => {rules=value;}));
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
    document.addEventListener('click', event => {
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
          picker.add(new Option(label, String(result.id), true, true));
          folderForm.elements.parent.add(new Option(label, String(result.id)));
          picker.dispatchEvent(new Event('change', {bubbles:true}));
          dialog.close();
          picker.focus();
        } else if (refreshTree) {
          refreshFolderTree(result.folder_html, result.id, result.folder_choices, result.move_folder_choices);
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
    root.querySelectorAll('.folder-menu-toggle,.library-import-toggle,.library-export-toggle,.library-create-toggle').forEach(button => {
      const menu = document.getElementById(button.getAttribute('popovertarget'));
      const items = [...menu.querySelectorAll('[role=menuitem]')];
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
      menu.addEventListener('toggle', event => {
        const open = event.newState === 'open';
        button.setAttribute('aria-expanded', String(open));
        if (open) {
          refreshRemoval();
          positionMenu();
          items[0]?.focus({preventScroll:true});
          window.addEventListener('resize', positionMenu);
          window.addEventListener('scroll', positionMenu, true);
        } else {
          removalGeneration++;
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
  }
  initializeMenus(document);
  if (!sidebar) return;
  let form = document.querySelector('#changelist-form');
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
  let rows = [...sidebar.querySelectorAll('.folder-row')];
  const segments = new Intl.Segmenter(undefined, {granularity:'grapheme'});
  function leadingEmoji(name) {
    const first = segments.segment(name).containing(0)?.segment;
    return first && /\p{Extended_Pictographic}|\p{Regional_Indicator}|[0-9#*]\uFE0F?\u20E3/u.test(first) ? first : '';
  }
  function initializeTreeRows() {
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
    rows.forEach(row => row.querySelector('.folder-toggle')?.addEventListener('click', () => {
      const id = row.dataset.folderId;
      if (collapsed.has(id)) collapsed.delete(id); else collapsed.add(id);
      try {localStorage.setItem('archivebox.folder-collapsed', JSON.stringify([...collapsed]));} catch (_) {}
      renderTree();
    }));
  }
  initializeTreeRows();
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
  function refreshFolderTree(html, createdId, parentChoices, moveChoices) {
    const tree = sidebar.querySelector('.folder-tree');
    tree.innerHTML = html;
    rows = [...tree.querySelectorAll('.folder-row')];
    initializeTreeRows();
    initializeMenus(tree);
    initializeFolderDragging(rows);
    initializeDropTargets(rows);
    let parent = rows.find(row => row.dataset.folderId === createdId)?.dataset.parentId;
    while (parent) {
      collapsed.delete(parent);
      parent = rows.find(row => row.dataset.folderId === parent)?.dataset.parentId;
    }
    renderTree();
    [folderForm.elements.parent, form?.querySelector('[name=folder_destination]')].filter(Boolean).forEach(select => {
      const selectedValue = select.value;
      const root = select.options[0].cloneNode(true);
      select.replaceChildren(root);
      const choices = select.name === 'folder_destination' ? moveChoices : parentChoices;
      choices.forEach(([id, label]) => select.add(new Option(label, id)));
      select.value = selectedValue;
    });
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
  let sidebarDwellTimer = null;
  function clearSidebarDwell() {
    clearTimeout(sidebarDwellTimer);
    sidebarDwellTimer = null;
  }
  try {desktopHidden = localStorage.getItem('archivebox.sidebar-hidden') === 'true';} catch (_) {}
  function viewportChanged() {
    if (mobileViewport.matches) clearSidebarDwell();
    const hidden = mobileViewport.matches ? mobileCollapsed : desktopHidden;
    // The mobile CSS owns the breakpoint. Preserve its state on desktop so a
    // resize cannot briefly expand the folder tree before matchMedia fires.
    sidebar.classList.toggle('is-collapsed', mobileCollapsed);
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
  function showDesktopSidebar() {
    desktopHidden = false;
    try {localStorage.setItem('archivebox.sidebar-hidden', 'false');} catch (_) {}
    viewportChanged();
  }
  reopenToggle.addEventListener('click', () => {
    showDesktopSidebar();
    mobileToggle.focus();
  });
  renderTree();
  // Public folders share navigation and exports, but have no move endpoint.
  if (!sidebar.dataset.moveUrl) return;

  // Compact cards retain their two-pill cap. The native table fits actual
  // one-line pill widths to the shared Title + Tags space.
  const cleanupTagRows = [];
  function initializeTagRows() {
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

    function setCounter(row, total, visible) {
      const expanded = row.pills.classList.contains('library-tags-expanded');
      row.toggle.hidden = expanded ? total === 0 : total <= visible;
      const text = expanded ? 'Show fewer tags' : `+${total - visible}`;
      if (row.toggle.textContent !== text) row.toggle.textContent = text;
      row.toggle.setAttribute('aria-label', expanded ? 'Show fewer tags' : `Show all ${total} tags`);
      row.toggle.setAttribute('aria-expanded', String(expanded));
    }
    function updateCompact(row) {
      const pills = row.pills.querySelectorAll('.tag-pill');
      if (pills.length <= 2) row.pills.classList.remove('library-tags-expanded');
      pills.forEach(pill => {if (pill.hidden) pill.hidden = false;});
      setCounter(row, pills.length, 2);
    }
    function spacing(element, properties) {
      const css = getComputedStyle(element);
      return properties.reduce((sum, name) => sum + (parseFloat(css[name]) || 0), 0);
    }
    function fitTableTags() {
      frame = 0;
      if (!header?.getBoundingClientRect().height || !title || !tags) {
        table?.classList.remove('library-tag-fit');
        table?.style.removeProperty('--library-tags-width');
        rows.forEach(updateCompact);
        return;
      }
      const cap = Math.floor((title.getBoundingClientRect().width + tags.getBoundingClientRect().width) * 0.4);
      table.classList.add('library-tag-fit');
      const dirty = rows.filter(row => !row.measure);
      if (dirty.length) measureTags(dirty);
      const demand = Math.max(label ? labelRange.getBoundingClientRect().width +
        spacing(label, ['paddingLeft', 'paddingRight']) + spacing(tags, ['paddingLeft', 'paddingRight']) : 0, ...rows.map(row => row.measure.full));
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
          visible = 0;
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
        setCounter(row, widths.length, showAll ? widths.length : visible);
      }
    }
    function measureTags(dirty) {
      table.classList.add('library-tag-measuring');
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
      dirty[0].toggle.after(...probes);
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
      probes.forEach(probe => probe.remove());
      table.classList.remove('library-tag-measuring');
    }
    function scheduleFit() {
      if (!frame) frame = requestAnimationFrame(fitTableTags);
    }
    form?.querySelectorAll('.tag-pills-inline').forEach(pills => {
      const editor = pills.closest('.tag-editor-inline');
      const toggle = document.createElement('button');
      toggle.type = 'button'; toggle.className = 'library-tags-toggle';
      pills.after(toggle);
      const cell = pills.closest('td.field-tags_inline');
      const inTable = cell && cell.closest('table') === table;
      const row = {pills, editor, toggle, cell, input: editor.querySelector('.tag-inline-input-sm')};
      if (inTable) rows.push(row);
      const update = () => inTable ? scheduleFit() : updateCompact(row);
      toggle.addEventListener('pointerdown', event => event.preventDefault());
      toggle.addEventListener('click', event => {
        event.stopPropagation();
        if (editor.contains(document.activeElement) && document.activeElement !== toggle) document.activeElement.blur();
        pills.classList.toggle('library-tags-expanded');
        update();
      });
      const observer = new MutationObserver(() => {
        row.measure = null;
        update();
      });
      observer.observe(pills, {childList: true});
      if (inTable) {
        editor.addEventListener('focusin', update);
        editor.addEventListener('focusout', update);
      }
      cleanupTagRows.push(() => observer.disconnect());
      updateCompact(row);
    });
    if (rows.length) {
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
      document.fonts.ready.then(() => {
        if (!table.isConnected) return;
        counterWidths = [];
        rows.forEach(row => {row.measure = null;});
        scheduleFit();
      });
      cleanupTagRows.push(() => {
        observer.disconnect();
        window.removeEventListener('resize', scheduleFit);
        cancelAnimationFrame(frame);
      });
      scheduleFit();
    }
  }
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
        !desktopHidden || mobileViewport.matches || event.clientX < 0 || event.clientX > 18) {
      clearSidebarDwell();
      return;
    }
    if (sidebarDwellTimer !== null) return;
    sidebarDwellTimer = setTimeout(() => {
      sidebarDwellTimer = null;
      if (!dragging || !desktopHidden || mobileViewport.matches) return;
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
  function initializeSnapshotDragging() {
    form?.querySelectorAll('input.action-select').forEach(checkbox => {
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
  initializeFolderDragging(rows);
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
  }
  initializeDropTargets(sidebar.querySelectorAll('.folder-drop-target'));
  let initializedForm;
  window.archiveboxInitLibraryRows = () => {
    form = document.querySelector('#changelist-form');
    if (form !== initializedForm) {
      initializedForm = form;
      if (dragging) {
        clearDrag();
        status.textContent = '';
      }
      initializeTagRows();
      initializeSnapshotDragging();
    }
    selectionChanged();
  };
  window.archiveboxInitLibraryRows();
});
