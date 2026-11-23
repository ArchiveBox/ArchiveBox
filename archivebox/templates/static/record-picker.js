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
    const wrapper = document.createElement("span");
    wrapper.className = "record-picker";
    const input = document.createElement("input");
    input.type = "search";
    input.autocomplete = "off";
    input.placeholder = label + "…";
    input.setAttribute("aria-label", label);
    const status = document.createElement("span");
    status.className = "record-picker-status";
    status.setAttribute("role", "status");
    const more = document.createElement("button");
    more.type = "button";
    more.textContent = "More results";
    more.hidden = true;
    select.before(wrapper);
    wrapper.append(input, select, more, status);
    let next = "";
    const search = connect(input, lookup(type, () => ({
      destination: select.dataset.pickerDestination,
      exclude: select.dataset.pickerExclude,
    })), (result) => {
      const value = select.value;
      const retained = optionsFrom(select).filter((option) => option.fixed || (option.id && option.id === value));
      const results = result.choices || [];
      const byId = new Map(retained.map((item) => [item.id, item]));
      for (const item of results) byId.set(String(item.id), item);
      select.replaceChildren();
      for (const [id, item] of byId) {
        const option = new Option(item.name, id, false, id === value);
        if (item.fixed) option.dataset.pickerFixed = "";
        option.disabled = Boolean(item.disabled);
        select.add(option);
      }
      select.value = value;
      next = result.next || "";
      more.hidden = !next;
      status.textContent = result.error ? "Could not load choices." : results.length ? "" : "No matches.";
    });
    input.addEventListener("focus", () => search());
    input.addEventListener("input", () => { more.hidden = true; });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "Enter") {
        event.preventDefault();
        select.focus();
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
      input.value = "";
      status.textContent = "";
      more.hidden = true;
      next = "";
    };
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
      input.list.replaceChildren(...choices.map((item) => new Option(item.name)));
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
