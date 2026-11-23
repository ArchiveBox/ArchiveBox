(() => {
  if (window.archiveboxSearchField) return;
  // Streamed results replace the admin toolbar. Global listeners must never
  // close over its old DOM; only the currently focused editor needs these events.
  const activeEditors = new WeakMap();
  const fitActiveMenu = () => activeEditors.get(document.activeElement)?.fitMenu();
  document.addEventListener('selectionchange', () => activeEditors.get(document.activeElement)?.selectionChanged());
  window.visualViewport?.addEventListener('resize', fitActiveMenu);
  window.visualViewport?.addEventListener('scroll', fitActiveMenu);
  window.addEventListener('resize', fitActiveMenu);
  // The sidebar and the results table live in separate scroll panes. They share
  // a base toolbar height, but a wrapped query (or its help) adds real rows.
  // Observe only the current results toolbar; streaming can replace it.
  const toolbarSize = new ResizeObserver(entries => {
    for (const {target, borderBoxSize} of entries) {
      target.closest('.snapshot-library')?.style.setProperty('--search-toolbar-height', borderBoxSize[0].blockSize + 'px');
    }
  });
  function init(root) {
    if (root.dataset.ready) return;
    root.dataset.ready = '1';
    const toolbar = root.closest('#changelist-search')?.closest('.public-snapshot-toolbar, #toolbar');
    if (toolbar) {
      toolbarSize.disconnect();
      toolbarSize.observe(toolbar, {box: 'border-box'});
    }
    const editor = root.querySelector('.query'), menu = root.querySelector('.suggestions');
    const options = root.querySelector('[role="listbox"]'), feedback = root.querySelector('.feedback');
    const hidden = root.querySelector('input[name]'), clear = root.querySelector('.abx-query-clear');
    const precedenceHint = root.querySelector('.precedence-hint');

    const operators = JSON.parse(root.dataset.operators);
    for (const op of operators) op.values = op.choices || [];
    const lookup = {__proto__: null, ...Object.fromEntries(operators.flatMap(op => [op.key,...(op.aliases || [])].map(key => [key,op])))};
    const listFields = new Set(['tags','plugins','filetype']);
    const literalFields = new Set(['meta','deep']);
    const freeSuggestions = new Set(['title','linksto','linkedfrom','after','before','bookmarked', ...literalFields]);
    const freeFields = new Set(['tags','plugins','folder','owner','status','permissions','title','linksto','linkedfrom','domain','site','after','before','bookmarked', ...literalFields]);
    const quotedText = /^"(?:\\.|[^"\\])+"$/;
    const tagList = /^(?:"(?:\\.|[^"\\])+"|[^",\s]+)(?:,(?:"(?:\\.|[^"\\])+"|[^",\s]+))*$/;
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const icon = name => `<svg aria-hidden="true"><use href="${esc(root.dataset.icons)}#${esc(name)}"></use></svg>`;
    let query = hidden.value, focused = false, composing = false, menuOpen = false, selected = -1, suggestions = [];
    let rendering = false, lastPaint = '', history = [{text:query,anchor:0,focus:0}], historyIndex = 0;

    // Keep plain query text as the source of truth. Badges are decorations, not
    // atomic editor objects. Entering one with the caret reveals editable text.
    // Copy/cut/paste and selections therefore operate on the original query.
    function selection() {
      const sel = window.getSelection();
      if (!sel || !editor.contains(sel.anchorNode) || !editor.contains(sel.focusNode)) return {anchor:query.length,focus:query.length};
      const offset = (node,n) => { const r = document.createRange(); r.selectNodeContents(editor); r.setEnd(node,n); return r.toString().length; };
      const anchor = offset(sel.anchorNode,sel.anchorOffset);
      return {anchor,focus:sel.isCollapsed ? anchor : offset(sel.focusNode,sel.focusOffset)};
    }
    function restore(pos) {
      const point = offset => {
        const walker = document.createTreeWalker(editor,NodeFilter.SHOW_TEXT);
        let node, last;
        while ((node = walker.nextNode())) { last = node; if (offset <= node.length) return [node,offset]; offset -= node.length; }
        if (!last) { last = document.createTextNode(''); editor.append(last); }
        return [last,last.length];
      };
      const [anchor, anchorOffset] = point(pos.anchor), [focus, focusOffset] = point(pos.focus);
      window.getSelection().setBaseAndExtent(anchor, anchorOffset, focus, focusOffset);
    }
    // UI lexer only: preserve quoted strings, negation, commas, and parentheses.
    // The server validates the full expression. This lexer also accepts partial
    // input so normal editing can continue between balanced quotes and groups.
    function tokens(text) {
      const result = [];
      // A trailing quote or backslash is normal while typing. Advance once
      // through it; never retry alternative ways to divide the same operand.
      let end = 0;
      while (end < text.length) {
        if (/\s/.test(text[end])) { end++; continue; }
        const start = end;
        if (text[end] === '(' || text[end] === ')') {
          end++;
        } else {
          let quoted = false;
          while (end < text.length) {
            const char = text[end];
            if (!quoted && /[\s()]/.test(char)) break;
            if (char === '"') quoted = !quoted;
            end += char === '\\' && end + 1 < text.length ? 2 : 1;
          }
        }
        const raw = text.slice(start, end);
        const neg = /^~+/.exec(raw)?.[0] || '';
        const operand = raw.slice(neg.length);
        // Only an unquoted field name at the beginning can introduce an operator.
        const parts = operand.startsWith('"') ? null : /^([a-z][a-z0-9_]*):(.*)$/i.exec(operand);
        result.push({
          start, end, raw, neg,
          key: parts?.[1].toLowerCase() === 'tag' ? 'tags' : parts?.[1].toLowerCase(), value: parts?.[2],
          exact: quotedText.test(operand)
        });
      }
      return result;
    }
    // Annotate what each operator applies to. Juxtaposed terms bind like AND.
    // Leave unfinished syntax in the field so it remains editable as typed.
    function annotateScopes(terms) {
      let index = 0;
      let hasMixedPrecedence = false;
      const precedence = {AND: 2, OR: 1};
      const mark = (token, first, last) => {
        token.scope = [first.start, last.end];
      };
      // Draw the boundary only where an OR competes with an AND branch. Group
      // decoration is separate from query text so copying never inserts parentheses.
      function markAndGroup(branch) {
        if (!branch.conjunction) return;
        branch.first.andGroupStarts = (branch.first.andGroupStarts || 0) + 1;
        branch.last.andGroupEnds = (branch.last.andGroupEnds || 0) + 1;
        hasMixedPrecedence = true;
      }
      function operand(depth) {
        const token = terms[index];
        if (!token || depth > 64 || token.raw === ')' || Object.hasOwn(precedence, token.raw)) return null;
        index++;
        if (token.raw === '(') {
          const inner = expression(1, depth + 1);
          if (terms[index]?.raw !== ')') return {first: token, last: inner?.last || token};
          const close = terms[index++];
          mark(token, token, close);
          close.scope = token.scope;
          return {first: token, last: close};
        }
        if (token.neg === token.raw) {
          const inner = operand(depth + 1);
          if (inner) {
            mark(token, inner.first, inner.last);
            inner.first.excluded = inner.last.excluded = true;
          }
          return {first: token, last: inner?.last || token};
        }
        if (token.neg) mark(token, token, token);
        return {first: token, last: token};
      }
      function expression(minimum, depth) {
        const left = operand(depth);
        if (!left) return null;
        while (index < terms.length && terms[index].raw !== ')') {
          const next = terms[index];
          const explicit = Object.hasOwn(precedence, next.raw);
          const strength = explicit ? precedence[next.raw] : precedence.AND;
          if (strength < minimum) break;
          if (explicit) index++;
          const right = expression(strength + 1, depth);
          if (!right) break;
          if (explicit) mark(next, left.first, right.last);
          if (next.raw === 'OR') {
            markAndGroup(left);
            markAndGroup(right);
          }
          left.last = right.last;
          left.conjunction = strength === precedence.AND;
        }
        return left;
      }
      while (index < terms.length) {
        if (!expression(1, 0)) index++;
      }
      return hasMixedPrecedence;
    }
    function valid(token) {
      if (!lookup[token.key] || !token.value || token.value.endsWith(',')) return false;
      // Suggestions are examples. A partial plugin or tag name is itself a valid
      // filter; waiting for an exact suggestion would hide its badge while editing.
      if (token.key === 'tags' || token.key === 'plugins') return tagList.test(token.value);
      if ((token.value.match(/(?<!\\)"/g) || []).length % 2) return false;
      const value = token.value.replace(/^"|"$/g,'');
      if (['after','before','bookmarked'].includes(token.key)) return /^\d{4}(-\d{2}){0,2}$/.test(value);
      if (freeFields.has(token.key)) return true;
      return token.key === 'filetype' && /^(?:"[a-z0-9]+"|[a-z0-9]+)(?:,(?:"[a-z0-9]+"|[a-z0-9]+))*$/i.test(token.value);
    }
    function activeToken(pos = selection()) {
      const at = pos.focus;
      return tokens(query).find(t => at >= t.start && at <= t.end) || {start:at,end:at,raw:'',value:'',neg:''};
    }
    let paintedTerms = [];
    let paintedSelection;
    let hoveredStart = null;
    function showScope(pos = selection()) {
      const source = paintedTerms.find(token => token.start === hoveredStart && token.scope)
        || (focused && pos.anchor === pos.focus
          ? paintedTerms.find(token => token.scope && pos.focus > token.start && pos.focus <= token.end)
          : null);
      for (const element of editor.querySelectorAll('[data-start]')) {
        const start = Number(element.dataset.start);
        const inScope = !!source && start !== source.start && start >= source.scope[0] && start < source.scope[1];
        element.classList.toggle('in-scope', inScope);
        element.classList.toggle('in-exclusion-scope', inScope && !!source.neg);
        const boundary = source && (source.raw === '(' || source.raw === ')')
          && element.classList.contains('group-mark')
          && (start === source.scope[0] || start + 1 === source.scope[1]);
        element.classList.toggle('scope-boundary', !!boundary);
      }
    }
    let paintTimer;
    function paint(pos = selection()) {
      clearTimeout(paintTimer);
      paintTimer = null;
      paintedSelection = pos;
      const pieces = [];
      let offset = 0;
      const low = Math.min(pos.anchor, pos.focus);
      const high = Math.max(pos.anchor, pos.focus);
      paintedTerms = tokens(query);
      const showPrecedence = annotateScopes(paintedTerms);
      precedenceHint.hidden = !showPrecedence;
      if (showPrecedence) editor.setAttribute('aria-describedby', precedenceHint.id);
      else editor.removeAttribute('aria-describedby');
      for (const token of paintedTerms) {
        pieces.push(esc(query.slice(offset, token.start)));
        pieces.push('<span class="and-group">'.repeat(token.andGroupStarts || 0));
        const editing = focused && (low === high ? low >= token.start && low <= token.end : low < token.end && high > token.start);
        const field = valid(token);
        const classes = [];
        if ((field || token.exact) && !editing) classes.push('filter-badge');
        if (field && !editing && ['domain','site','linksto','linkedfrom'].includes(token.key)) classes.push('host-filter');
        if (!editing && (token.exact || (field && literalFields.has(token.key) && quotedText.test(token.value)))) {
          classes.push('exact');
        }
        if (token.neg || token.excluded) classes.push('excluded');
        if (token.raw === 'AND' || token.raw === 'OR') classes.push('boolean');
        if (token.raw === 'OR') classes.push('alternative-separator');
        if (token.raw === '(' || token.raw === ')') classes.push('group-mark');
        const decoration = field && !editing
          ? `<span class="badge-icon" contenteditable="false" aria-hidden="true">${icon(lookup[token.key].icon)}</span>`
          : '';
        pieces.push(`<span class="${classes.join(' ')}" data-start="${token.start}">${decoration}${esc(token.raw)}</span>`);
        pieces.push('</span>'.repeat(token.andGroupEnds || 0));
        offset = token.end;
      }
      pieces.push(esc(query.slice(offset)));
      const html = pieces.join('');
      if (html !== lastPaint || editor.textContent !== query) {
        rendering = true; editor.innerHTML = html; lastPaint = html;
        if (focused) restore(pos);
        rendering = false;
      }
      hidden.value = query; clear.hidden = !query;
      showScope(pos);
    }
    const quote = (value, force = false) => force || /[\s":()~\\]/.test(value) ? '"' + value.replace(/\\/g,'\\\\').replace(/"/g,'\\"') + '"' : value;

    // The server supplies permission-scoped values. Replacing only the active
    // operand preserves adjacent terms and any preceding comma-separated values.
    function completionParts(token) {
      if (!lookup[token.key]) return null;
      // Split on separators outside quotes so choosing a suggestion cannot
      // rewrite an earlier tag containing a comma (including an unfinished edit).
      const values = [''];
      let quoted = false, escaped = false;
      for (const char of token.value) {
        if (char === ',' && !quoted) { values.push(''); continue; }
        values[values.length - 1] += char;
        if (escaped) escaped = false;
        else if (quoted && char === '\\') escaped = true;
        else if (char === '"') quoted = !quoted;
      }
      const prior = listFields.has(token.key) ? values.slice(0,-1) : [];
      const operand = listFields.has(token.key) ? values.at(-1) : token.value;
      const typed = operand.replace(/^"|"$/g,'').replace(/\\(["\\])/g,'$1');
      return {prior, operand, typed};
    }
    function completions(token, wholeToken, parts) {
      if (!token.key || !lookup[token.key]) {
        const prefix = token.raw.replace(/^~/,'').toLowerCase();
        return operators.filter(op => [op.key,...(op.aliases || [])].some(k => k.startsWith(prefix))).map(op => {
          const key = op.aliases?.find(a => prefix && a.startsWith(prefix)) || op.key;
          return {label:key+':',detail:op.description,icon:op.icon,replacement:(token.raw.startsWith('~')?'~':'')+key+':',operator:true};
        });
      }
      const op = lookup[token.key];
      const {prior, operand, typed} = parts;
      // Smart case belongs to this operator's value. An uppercase neighbor or
      // AND must not narrow its suggestions. Hostnames always follow DNS casing.
      const matchCase = op.key !== 'domain' && /\p{Uppercase}/u.test(wholeToken.value);
      const normalize = value => matchCase ? value : value.toLowerCase();
      const prefix = normalize(typed);
      const matches = op.values.filter(v => normalize(v).includes(prefix) && !prior.includes(v));
      // Keep the spelling the user typed available: choosing the canonical
      // mixed-case spelling can change which archived records match.
      // Inventory choices (plugins, folders, tags, etc.) must actually exist.
      if (prefix && freeSuggestions.has(token.key) && !matches.includes(typed)) matches.unshift(typed);
      const forceQuotes = literalFields.has(token.key) || operand.startsWith('"');
      return (op.key === 'plugins' ? matches : matches.slice(0,8)).map(value => ({label:value,detail:'',icon:op.icon,
        replacement:token.neg+token.key+':'+[...prior,quote(value, forceQuotes || (listFields.has(token.key) && value.includes(',')))].join(','),operator:false}));
    }
    let menuFrame;
    function fitMenu() {
      // An embedding host controls an iframe's height; only a top-level field
      // can size its menu from the visual viewport above the software keyboard.
      if (menuFrame || menu.hidden || window.self !== window.top) return;
      menuFrame = requestAnimationFrame(() => {
        menuFrame = null;
        if (menu.hidden || !root.isConnected) return;
        const viewport = window.visualViewport;
        const bottom = viewport ? viewport.offsetTop + viewport.height : window.innerHeight;
        const room = bottom - options.getBoundingClientRect().top - menu.querySelector('.menu-foot').offsetHeight - 10;
        options.style.setProperty('--menu-room', Math.max(60, Math.floor(room)) + 'px');
      });
    }
    let menuTimer;
    let requestKey = '', controller;
    function abortSuggestions() {
      if (!controller) return;
      controller.abort();
      controller = null;
      requestKey = '';
    }
    function hideMenu() {
      if (menu.hidden) return;
      menu.hidden = true;
      editor.setAttribute('aria-expanded','false');
      editor.removeAttribute('aria-activedescendant');
    }
    function scheduleMenu() {
      // Keep text, badges, and the caret responsive while typing. Rebuild
      // suggestions only after a pause, and hide rows for the old operand.
      abortSuggestions();
      hideMenu();
      selected = -1;
      clearTimeout(menuTimer);
      menuTimer = setTimeout(() => showMenu(), 150);
    }
    function showMenu(reset = true) {
      clearTimeout(menuTimer);
      menuTimer = null;
      if (!focused || composing || !menuOpen || !root.isConnected) {
        abortSuggestions();
        hideMenu();
        return;
      }
      const pos = selection();
      const wholeToken = activeToken(pos);
      const prefix = query.slice(wholeToken.start,pos.focus);
      const token = tokens(prefix)[0] || {raw:'',value:'',neg:''};
      const parts = completionParts(token);
      suggestValues(token, parts);
      const previous = reset ? undefined : suggestions[selected]?.replacement;
      suggestions = completions(token, wholeToken, parts);
      selected = suggestions.findIndex(suggestion => suggestion.replacement === previous);
      menu.hidden = suggestions.length === 0;
      editor.setAttribute('aria-expanded',String(!menu.hidden));
      root.querySelector('.menu-label').textContent = lookup[token.key] ? lookup[token.key].description : 'Narrow your search';
      options.innerHTML = suggestions.map((s,i) => `<button type="button" class="suggestion cursor-interaction" role="option" id="${hidden.id}-option-${i}" data-index="${i}" aria-selected="${i===selected}">${icon(s.icon)}<span class="suggestion-name">${esc(s.label)}</span><span class="suggestion-detail">${esc(s.detail)}</span></button>`).join('');
      fitMenu();
      if (reset) options.scrollTop = 0;
      selectSuggestion(selected);
    }
    function selectSuggestion(index) {
      options.children[selected]?.setAttribute('aria-selected','false');
      selected = index;
      const active = options.children[selected];
      if (active) {
        active.setAttribute('aria-selected','true');
        editor.setAttribute('aria-activedescendant',active.id);
        const row = active.getBoundingClientRect(), box = options.getBoundingClientRect();
        if (row.top < box.top) options.scrollTop += row.top - box.top;
        else if (row.bottom > box.bottom) options.scrollTop += row.bottom - box.bottom;
      } else editor.removeAttribute('aria-activedescendant');
    }
    async function suggestValues(token, parts) {
      const op = lookup[token.key];
      if (!op || op.choices) { abortSuggestions(); return; }
      const needle = parts.typed;
      // The sidebar and Django filters already live in the list URL. Only
      // list editors inherit them; the separate Smart Folder builder has its own scope.
      const params = new URLSearchParams(location.search);
      for (const name of ['q','search_mode','p','page','o','sidebar']) params.delete(name);
      const view = root.closest('.snapshot-library #changelist-search') && params.size ? location.pathname + '?' + params : '';
      const key = JSON.stringify([op.key,needle,view]);
      if (key === requestKey) return;
      abortSuggestions();
      requestKey = key;
      op.values = [];
      const request = controller = new AbortController();
      try {
        const url=new URL(root.dataset.suggestions, location.href);
        if (view) url.searchParams.set('search_url',view);
        url.searchParams.set('operator',op.key); url.searchParams.set('prefix',needle);
        const response=await fetch(url,{signal:request.signal});
        if (!response.ok) return;
        const {values}=await response.json();
        if (controller === request && focused && menuOpen && root.isConnected) {
          op.values = values;
          showMenu(false);
        }
      } catch (error) {
        if (error.name !== 'AbortError') console.debug('Search suggestions unavailable');
      } finally {
        if (controller === request) controller = null;
      }
    }
    function record(pos) {
      // Visiting an old bookmarked mode URL still runs its original query.
      // Once edited, the operator field submits the new expression as typed.
      if (hidden.name === 'q' && hidden.form?.elements.search_mode) hidden.form.elements.search_mode.value = 'query';
      if (history[historyIndex].text === query) return;
      history.splice(historyIndex+1); history.push({text:query,...pos}); historyIndex = history.length-1;
      if (history.length > 150) { history.shift(); historyIndex--; }
      hidden.dispatchEvent(new Event("input",{bubbles:true}));
    }
    function change(text,pos) {
      history[historyIndex] = {text:query,...selection()};
      query = text; editor.focus(); focused = true; feedback.textContent = '';
      paint(pos); record(pos); menuOpen = true; scheduleMenu();
    }
    function choose(index) {
      const suggestion = suggestions[index]; if (!suggestion) return;
      const token = activeToken();
      const trailing = query.slice(token.end);
      const suffix = suggestion.operator || /^\s/.test(trailing) ? '' : ' ';
      const inserted = suggestion.replacement+suffix;
      const caret = token.start+inserted.length;
      change(query.slice(0,token.start)+inserted+trailing,{anchor:caret,focus:caret});
      if (!suggestion.operator) { menuOpen = false; showMenu(); }
    }
    function undo(direction) {
      history[historyIndex] = {text:query,...selection()};
      historyIndex = Math.max(0,Math.min(history.length-1,historyIndex+direction));
      const saved = history[historyIndex]; query = saved.text; paint(saved); menuOpen = false; showMenu(); hidden.dispatchEvent(new Event("input",{bubbles:true}));
    }
    function submit() {
      menuOpen=false; showMenu(); hidden.value=query;
      if (hidden.name === 'q') hidden.form?.requestSubmit();
      else hidden.dispatchEvent(new Event('change',{bubbles:true}));
    }
    root.addEventListener('archivebox:search-progress', ({detail}) => {
      if (!detail || detail.query !== query || !Number.isSafeInteger(detail.matches) || detail.matches < 0) return;
      const message = document.createElement('span'), count = document.createElement('span');
      message.textContent = detail.message;
      count.className = 'match-count';
      count.textContent = detail.matches.toLocaleString() + (detail.matches === 1 ? ' match' : ' matches');
      feedback.replaceChildren(message, count);
    });
    editor.addEventListener('focus',() => { focused = true; menuOpen = true; paint(); showMenu(); });
    editor.addEventListener('blur',() => { focused = false; menuOpen = false; paint(); showMenu(); });
    editor.addEventListener('beforeinput',e => {
      if (!composing && (e.inputType === 'insertParagraph' || e.inputType === 'insertLineBreak')) {
        e.preventDefault(); submit(); return;
      }
      if (e.inputType === 'historyUndo' || e.inputType === 'historyRedo') { e.preventDefault(); undo(e.inputType === 'historyUndo' ? -1 : 1); }
      else history[historyIndex] = {text:query,...selection()};
    });
    editor.addEventListener('input',() => {
      if (composing) return;
      // Let the browser paint its own edit first. Replacing badge nodes here
      // also rebuilds the selection and queues mutation observers before paint.
      query = editor.textContent.replace(/[\r\n]/g,' ');
      hidden.value = query;
      clear.hidden = !query;
      if (feedback.firstChild) feedback.replaceChildren();
      // beforeinput captures the real selection before the next edit or undo.
      record({anchor:query.length,focus:query.length});
      clearTimeout(paintTimer);
      paintTimer = setTimeout(() => {
        paintTimer = null;
        if (!composing && root.isConnected) paint();
      }, 120);
      menuOpen = true; scheduleMenu();
    });
    // Replacing text nodes mid-composition would drop the mobile keyboard's
    // provisional text. Repaint once the IME commits it and the caret is stable.
    editor.addEventListener('compositionstart',() => { composing = true; showMenu(); });
    editor.addEventListener('compositionend',() => { composing = false; editor.dispatchEvent(new Event('input')); });
    function selectionChanged() {
      if (!focused || rendering || composing || paintTimer) return;
      const sel = window.getSelection(); if (!editor.contains(sel?.anchorNode)) return;
      // Restoring the caret after a synchronous edit also fires selectionchange.
      // Its decorations are already up to date.
      const pos = selection();
      if (pos.anchor !== paintedSelection?.anchor || pos.focus !== paintedSelection?.focus) paint(pos);
    }
    activeEditors.set(editor, {selectionChanged, fitMenu});
    editor.addEventListener('click',e => {
      // A click in a decorated token resolves to its underlying character offset.
      // The token then opens as text; arrow keys use the browser's native caret.
      paint(); menuOpen = true; showMenu();
    });
    editor.addEventListener('pointermove', event => {
      const token = event.target.closest('[data-start]');
      const start = token ? Number(token.dataset.start) : null;
      if (hoveredStart === start) return;
      hoveredStart = start;
      showScope();
    });
    editor.addEventListener('pointerleave', () => {
      hoveredStart = null;
      showScope();
    });
    editor.addEventListener('keydown',e => {
      if (composing || e.isComposing) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(e.shiftKey?1:-1); return; }
      if (e.ctrlKey && e.key.toLowerCase() === 'y') { e.preventDefault(); undo(1); return; }
      if (e.key === 'Escape') { e.preventDefault(); menuOpen = false; showMenu(); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (menu.hidden) { menuOpen = true; showMenu(); }
        if (suggestions.length) {
          const current = selected < 0 && e.key === 'ArrowUp' ? 0 : selected;
          selectSuggestion((current + (e.key === 'ArrowDown' ? 1 : -1) + suggestions.length) % suggestions.length);
        }
        return;
      }
      if (e.key === 'Tab') {
        if (menuTimer) showMenu();
        if (!menu.hidden && suggestions.length) { e.preventDefault(); choose(selected < 0 ? 0 : selected); }
        return;
      }
      if (e.key === 'Enter') { e.preventDefault(); if (!menu.hidden && selected >= 0) choose(selected); else submit(); return; }
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'Home' || e.key === 'End') {
        // Leave caret movement, word movement, and Shift selection native.
        menuOpen = false; showMenu();
      }
    });
    options.addEventListener('mousedown',e => e.preventDefault());
    options.addEventListener('click',e => { const row = e.target.closest('[data-index]'); if (row) choose(Number(row.dataset.index)); });
    const selectedText = () => { const pos = selection(); return query.slice(Math.min(pos.anchor,pos.focus),Math.max(pos.anchor,pos.focus)); };
    editor.addEventListener('copy',e => { e.preventDefault(); e.clipboardData.setData('text/plain',selectedText()); });
    editor.addEventListener('cut',e => {
      e.preventDefault(); e.clipboardData.setData('text/plain',selectedText());
      const pos = selection(), a = Math.min(pos.anchor,pos.focus), b = Math.max(pos.anchor,pos.focus);
      change(query.slice(0,a)+query.slice(b),{anchor:a,focus:a});
    });
    editor.addEventListener('paste',e => {
      e.preventDefault(); const text = e.clipboardData.getData('text/plain').replace(/[\r\n]+/g,' ');
      const pos = selection(), a = Math.min(pos.anchor,pos.focus), b = Math.max(pos.anchor,pos.focus), end = a+text.length;
      change(query.slice(0,a)+text+query.slice(b),{anchor:end,focus:end});
    });
    // Keep editor focus until the action runs: a blur repaint must not replace
    // the icon underneath the pointer between mousedown and click.
    clear.addEventListener('mousedown',e => e.preventDefault());
    clear.addEventListener('click',() => change('',{anchor:0,focus:0}));
    hidden.type = 'hidden';
    hidden.addEventListener('archivebox:load', () => {
      query = hidden.value; history=[{text:query,anchor:0,focus:0}]; historyIndex=0; paint();
    });
    paint();
  }
  function mount(container) {
    container.querySelectorAll('.abx-search-field').forEach(init);
  }
  window.archiveboxSearchField = mount;
  mount(document);
  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) {
      if (node.nodeType === 1 && !node.closest('.abx-search-field[data-ready]')) {
        if (node.matches('.abx-search-field')) init(node); else mount(node);
      }
    }
  }).observe(document.body,{childList:true,subtree:true});
})();
