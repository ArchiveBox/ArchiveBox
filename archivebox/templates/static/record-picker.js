(() => {
  const urls = {
    folder: "/api/v1/core/folders/autocomplete/",
    tag: "/api/v1/core/tags/autocomplete/",
  };
  const mounted = new WeakMap();

  function optionsFrom(select) {
    return Array.from(select.options, (option) => ({
      id: option.value,
      name: option.text,
      fixed: option.hasAttribute("data-picker-fixed") || !option.value,
      disabled: option.disabled,
    }));
  }

  function connect(input, lookup, update) {
    let timer, controller;
    function search(after = "") {
      clearTimeout(timer);
      controller?.abort();
      timer = setTimeout(async () => {
        if (!input.isConnected) return;
        controller = new AbortController();
        const { signal } = controller;
        const query = input.value.trim();
        try {
          const result = await lookup(query, signal, after);
          if (!signal.aborted && input.isConnected && query === input.value.trim()) update(result);
        } catch {
          if (!signal.aborted && input.isConnected) update({ error: true });
        }
      }, 140);
    }
    input.addEventListener("input", () => search());
    search.cancel = () => {
      clearTimeout(timer);
      controller?.abort();
    };
    return search;
  }

  function lookup(type, parameters = () => ({}), endpoint) {
    return async (q, signal, after) => {
      const url = new URL(endpoint || urls[type], location.origin);
      url.searchParams.set("q", q);
      if (after) url.searchParams.set("after", after);
      for (const [key, value] of Object.entries(parameters())) {
        if (value) url.searchParams.set(key, value);
      }
      const apiKey = window.ARCHIVEBOX_API_KEY;
      const response = await fetch(url, {
        signal,
        headers: apiKey && !endpoint ? { "X-ArchiveBox-API-Key": apiKey } : {},
      });
      if (!response.ok) throw new Error("Could not load choices");
      const data = await response.json();
      return { choices: data.choices || data.tags || [], next: data.next };
    };
  }

  function mount(select) {
    if (mounted.has(select)) return mounted.get(select);
    const type = select.dataset.picker;
    const label = type === "folder" ? "Find a folder" : "Find a tag";
    const renderedWrapper = select.parentElement.matches(".record-picker") ? select.parentElement : null;
    const wrapper = renderedWrapper || document.createElement("span");
    wrapper.className = "record-picker";
    const renderedInput = renderedWrapper?.querySelector(":scope > input");
    const input = renderedInput || document.createElement("input");
    if (!renderedInput) {
      input.type = "search";
      input.autocomplete = "off";
      input.placeholder = label + "…";
      input.setAttribute("aria-label", label);
    }
    const status = document.createElement("span");
    status.className = "record-picker-status";
    status.setAttribute("role", "status");
    const more = document.createElement("button");
    more.type = "button";
    more.textContent = "More results";
    more.hidden = true;
    const nativeFolder = type === "folder";
    input.hidden = nativeFolder;
    if (!renderedWrapper) select.before(wrapper);
    wrapper.append(input, select, more, status);
    let next = "";
    const panel = document.createElement("div");
    const choices = document.createElement("div");
    if (nativeFolder) {
      panel.className = "record-picker-menu";
      panel.popover = "auto";
      choices.className = "record-picker-choices";
      wrapper.append(panel);
      panel.append(input, choices, more, status);
    }
    // Keep the native chooser as the single closed control. Search is a menu
    // command, so touch devices still get their normal OS picker on first tap.
    const findValue = "__find_folder__";
    const findOption = () => {
      const option = new Option(label + "…", findValue);
      option.dataset.pickerCommand = "find";
      return option;
    };
    function insertFind() {
      // Place search above the destinations, even when the page is full.
      const value = select.value;
      select.add(findOption(), Array.from(select.options).find(option => !option.disabled) || null);
      select.value = value;
    }
    // After form.reset() the browser normally falls back to the first option.
    // Preserve the real default before inserting the Find command above it.
    const defaultOption = select.selectedOptions[0];
    if (nativeFolder && defaultOption) defaultOption.defaultSelected = true;
    if (nativeFolder) insertFind();
    let previous = select.value;
    const search = connect(input, lookup(type, () => ({
      destination: select.dataset.pickerDestination,
      exclude: select.dataset.pickerExclude,
    })), (result) => {
      const value = select.value;
      const defaultValue = nativeFolder ? Array.from(select.options).find(option => option.defaultSelected)?.value : undefined;
      const retained = optionsFrom(select).filter(option => option.fixed || option.id === value || option.id === defaultValue);
      const results = result.choices || [];
      const byId = new Map(retained.filter(item => item.fixed).map(item => [item.id, item]));
      for (const item of results) byId.set(String(item.id), item);
      // Keep off-page form values available for submission and reset. Pinned
      // values must not jump ahead of ancestors in the server's ordered page.
      for (const item of retained) {
        if (!byId.has(item.id)) byId.set(item.id, {...item, hidden: nativeFolder});
      }
      select.replaceChildren();
      for (const [id, item] of byId) {
        const option = new Option(item.name, id, id === defaultValue, id === value);
        if (item.fixed) option.dataset.pickerFixed = "";
        option.disabled = Boolean(item.disabled);
        option.hidden = Boolean(item.hidden);
        select.add(option);
      }
      if (nativeFolder) {
        insertFind();
        if (panel.matches(":popover-open")) {
          // Use the same choices as the native picker. Users typing a filter
          // can choose a visible match without reopening the OS select.
          const term = input.value.trim().toLowerCase();
          const fixed = retained.filter(item => item.fixed && !item.disabled && item.name && item.name.toLowerCase().includes(term));
          const buttons = [...fixed, ...results].map(item => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = item.name;
            button.addEventListener("click", () => {
              select.value = String(item.id);
              select.dispatchEvent(new Event("change", {bubbles: true}));
            });
            return button;
          });
          choices.replaceChildren(...buttons);
        }
      }
      select.value = value;
      next = result.next || "";
      more.hidden = !next || input.hidden;
      status.hidden = nativeFolder && input.hidden;
      status.textContent = result.error ? "Could not load choices." : results.length || choices.childElementCount ? "" : "No matches.";
    });
    if (nativeFolder) {
      const remember = () => { if (select.value !== findValue) previous = select.value; };
      select.addEventListener("focus", remember);
      select.addEventListener("pointerdown", remember);
      select.addEventListener("keydown", remember);
      function openSearch(term = "") {
        input.hidden = false;
        choices.replaceChildren();
        panel.showPopover();
        // Anchor to the visible select (also the hit target over the Move
        // button). The top layer escapes the scrolling changelist and dialogs.
        const rect = select.getBoundingClientRect();
        const height = window.visualViewport?.height || innerHeight;
        panel.style.left = Math.max(4, Math.min(rect.left, innerWidth - panel.offsetWidth - 4)) + "px";
        if (height - rect.bottom >= Math.min(220, rect.top)) {
          panel.style.top = rect.bottom + 2 + "px";
          panel.style.bottom = "auto";
        } else {
          panel.style.top = "auto";
          panel.style.bottom = Math.max(0, innerHeight - rect.top + 2) + "px";
        }
        input.value = term;
        input.focus();
      }
      // A mouse or keyboard can filter on first interaction, like the tag
      // field. Let touch open the platform chooser and its Find command.
      let mousePress = false;
      select.addEventListener("pointerdown", event => {
        mousePress = event.pointerType === "mouse" && event.button === 0;
        if (mousePress) event.preventDefault();
      });
      select.addEventListener("click", () => {
        // Opening on pointerdown lets the subsequent outside pointerup
        // immediately light-dismiss the popover. Older click events also
        // lack pointerType, so use the device from the original press.
        if (mousePress) openSearch();
        mousePress = false;
      });
      select.addEventListener("keydown", event => {
        if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
        const printable = event.key.length === 1;
        if (!printable && !["Enter", "ArrowDown"].includes(event.key)) return;
        event.preventDefault();
        openSearch(printable ? event.key.trimStart() : "");
      });
      select.addEventListener("change", event => {
        if (select.value === findValue) {
          // A search command must never submit the Move action or a list filter.
          event.stopImmediatePropagation();
          select.value = previous;
          openSearch();
        } else {
          remember();
          panel.hidePopover();
          input.hidden = true;
          more.hidden = true;
          status.hidden = true;
        }
      }, true);
      input.addEventListener("keydown", event => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          panel.hidePopover();
          input.hidden = true;
          more.hidden = true;
          status.hidden = true;
          select.focus();
        }
      });
      panel.addEventListener("toggle", () => {
        if (!panel.matches(":popover-open")) {
          input.hidden = true;
          if (input.value) {
            input.value = "";
            search();
          }
        }
      });
      choices.addEventListener("keydown", event => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        event.preventDefault();
        const next = event.key === "ArrowDown" ? event.target.nextElementSibling : event.target.previousElementSibling;
        (next || input).focus();
      });
      // Load just the first page when the control becomes visible. A selected
      // row, opening an editor, or exposing filters can reveal it after mount.
      const visible = new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting)) {
          visible.disconnect();
          if (!input.value) search();
        }
      });
      visible.observe(select);
    }
    input.addEventListener("focus", () => search());
    input.addEventListener("input", () => { more.hidden = true; choices.replaceChildren(); });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "Enter") {
        event.preventDefault();
        if (nativeFolder && !input.hidden) {
          const first = choices.firstElementChild;
          if (event.key === "Enter") first?.click();
          else first?.focus();
        } else select.focus();
      }
    });
    more.onclick = () => search(next);
    if (select.dataset.pickerFilter) {
      select.addEventListener("change", () => {
        const url = new URL(select.dataset.pickerFilterUrl, location.href);
        if (select.value) url.searchParams.set(select.dataset.pickerFilter, select.value);
        location.assign(url.href);
      });
    }
    const reset = () => {
      search.cancel();
      if (nativeFolder) panel.hidePopover();
      input.value = "";
      input.hidden = nativeFolder;
      status.hidden = nativeFolder;
      status.textContent = "";
      more.hidden = true;
      next = "";
      if (nativeFolder) search();
    };
    if (renderedInput) input.disabled = false;
    mounted.set(select, { input, reset });
    return mounted.get(select);
  }

  function initialize(root = document) {
    for (const select of root.querySelectorAll("select[data-picker]")) mount(select);
    for (const input of root.querySelectorAll("input[data-tag-suggestions]")) initializeTagInput(input);
  }

  function initializeTagInput(input) {
    if (mounted.has(input) || !input.list) return;
    const searchTags = lookup("tag");
    const search = connect(input, (q, signal) => q ? searchTags(q, signal) : { choices: [] }, ({ choices = [] }) => {
      input.list.replaceChildren(...choices.map((item) => new Option(item.name, item.name)));
    });
    mounted.set(input, search);
  }

  function selectChoice(select, id, label) {
    id = String(id);
    if (!Array.from(select.options).some((option) => option.value === id)) {
      select.add(new Option(label, id));
    }
    select.value = id;
  }

  document.addEventListener("focusin", (event) => {
    if (event.target.matches("input[data-tag-suggestions]")) initializeTagInput(event.target);
  });
  window.ArchiveBoxPicker = { connect, initialize, lookup, mount, selectChoice };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => initialize(), { once: true });
  } else {
    initialize();
  }
})();
