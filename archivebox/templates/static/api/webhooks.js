(() => {
  "use strict";
  const root = document.getElementById("webhooks");
  const initial = JSON.parse(
    document.getElementById("webhook-editor-data").textContent,
  );
  const baseURL = root.dataset.url;
  const models = initial.models.map((m) => [m.name, m.emoji, m.ref]);
  const eventsFor = (ref) => {
    const events = initial.models.find((m) => m.ref === ref)?.events || [];
    const selected = current?.ref === ref ? current.signal : null;
    return selected && !events.some((e) => e.key === selected)
      ? [
          ...events,
          {
            key: selected,
            label: initial.signal_labels[selected] || selected,
            icon: "bolt",
            color: "#597bab",
          },
        ]
      : events;
  };

  const folders = { Snapshot: initial.folders };
  const types = {
    disable_plugin: "Disable plugin",
    enable_plugin: "Enable plugin",
    set_config: "Set configuration",
    add_tags: "Add tags",
    remove_tags: "Remove tags",
    move_folder: "Move to folder",
    visibility: "Set visibility",
    set_depth: "Set crawl depth",
    http_request: "Send HTTP request",
    python: "Run a Python snippet",
    shell: "Run a shell command",
  };
  let hooks = initial.hooks.map(editorWebhook),
    current = null;
  async function post(path, data) {
    const response = await fetch(baseURL + path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": root.querySelector('[name="csrfmiddlewaretoken"]').value,
      },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw Error(error.error || "Could not save webhook");
    }
    return response.json();
  }
  // Only presentation fields differ from stored actions. This conversion is the
  // inverse of outboundWebhookData; no UI preset or extra delivery type is stored.
  function editorWebhook(hook) {
    return {
      ...hook,
      actions: hook.actions.flatMap((action) => {
        const { type } = action;
        if (type === "disable_plugins" || type === "enable_plugins")
          return action[type].map((value) => ({
            type: type.slice(0, -1),
            value,
          }));
        if (type === "config_overrides")
          return Object.entries(action.config_overrides).map(
            ([key, value]) => ({
              type: "set_config",
              key,
              value:
                typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value),
            }),
          );
        if (type === "max_depth")
          return [{ type: "set_depth", value: String(action.max_depth) }];
        if (type === "permissions")
          return [{ type: "visibility", value: action.permissions }];
        if (type === "folder")
          return [{ type: "move_folder", value: action.folder_id || "" }];
        if (type === "python") return [{ type, value: action.code }];
        if (type === "shell") return [{ type, value: action.command }];
        if (type === "http_request")
          return [
            {
              type,
              method: action.method || "POST",
              value: action.endpoint,
              headers: JSON.stringify(action.headers || {}),
              body: action.body,
            },
          ];
        return [{ type, value: action[type] }];
      }),
    };
  }
  const $ = (id) => document.getElementById(id);
  const icons = (name) =>
    '<svg class="icon" aria-hidden="true"><use href="#' + esc(name) + '"/></svg>';
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const eventOf = (h) =>
    eventsFor(h.ref).find((e) => e.key === h.signal) || {
      key: h.signal,
      label: initial.signal_labels[h.signal] || h.signal,
    };
  const folderOf = (h) =>
    eventOf(h).membership
      ? (folders[modelName(h.ref)] || []).find((f) => f.id === h.folder_id)
      : undefined;
  const modelName = (ref) => models.find((m) => m[2] === ref)?.[0] || ref;
  const modelIcon = (ref) => models.find((m) => m[2] === ref)?.[1] || "";

  function setDirty() {
    $("save-state").textContent = "Unsaved";
    $("preview").hidden = true;
  }
  function toast(text) {
    $("toast").textContent = text;
    $("toast").hidden = false;
    clearTimeout(window.toastTimer);
    window.toastTimer = setTimeout(() => ($("toast").hidden = true), 2400);
  }
  function renderList() {
    const term = $("search").value.toLowerCase();
    const visible = hooks.filter(
      (h) =>
        h.name.toLowerCase().includes(term) &&
        ($("filter").value === "all" ||
          h.actions.some((a) => a.type === "http_request")),
    );
    $("hook-rows").innerHTML = visible
      .map((h) => {
        const e = eventOf(h),
          f = folderOf(h);
        return `<tr data-id="${esc(h.id)}" class="${
          current?.id === h.id ? "selected" : ""
        }"><td><button class="switch row-switch" role="switch" aria-label="Enable ${esc(
          h.name,
        )}" aria-checked="${esc(h.enabled)}" data-id="${esc(
          h.id,
        )}"></button></td><td><button class="webhook-name" style="border:0;background:none;padding:0;text-align:left;font:inherit;font-weight:550">${esc(
          h.name,
        )}</button><span class="scope-label">${
          f
            ? icons("folder") + esc(f.name)
            : esc(modelIcon(h.ref)) + " " + esc(modelName(h.ref))
        }</span></td><td class="event-cell">${esc(e.label)}<span>${esc(
          modelName(h.ref),
        )}</span></td><td class="delivery-column delivery">${
          h.actions.length
        } action${h.actions.length === 1 ? "" : "s"}${
          h.actions.some((a) => a.type === "http_request") ? " · HTTP" : ""
        }</td><td><button class="icon-btn" aria-label="Edit ${esc(
          h.name,
        )}">${icons("external")}</button></td></tr>`;
      })
      .join("");
    $("total").textContent = hooks.length;
    $("row-count").textContent = visible.length + " webhooks";
    $("enabled-count").textContent =
      hooks.filter((h) => h.enabled).length + " enabled";
  }
  function renderTimeline() {
    $("event-timeline").innerHTML = eventsFor(current.ref)
      .map(
        (e) =>
          `<label class="event-option ${
            e.section ? "section-start" : ""
          }" style="--event-color:${
            esc(e.color)
          }"><input type="radio" name="event" value="${esc(e.key)}" ${
            current.signal === e.key ? "checked" : ""
          }><span class="event-icon">${icons(e.icon)}</span><span>${
            esc(e.label)
          }</span>${
            e.blocking ? '<span class="event-note">Blocking</span>' : ""
          }</label>`,
      )
      .join("");
  }
  function fillScope() {
    const e = eventOf(current),
      items = e.membership ? folders[modelName(current.ref)] || [] : [];
    $("scope-field").hidden = !e.membership;
    $("scope-label").textContent = "Folder";
    $("scope").innerHTML = items
      .map((f) => `<option value="${esc(f.id)}">${esc(f.name)}</option>`)
      .join("");
    if (!items.some((f) => f.id === current.folder_id))
      current.folder_id = items[0]?.id || "";
    $("scope").value = current.folder_id;
    $("open-scope").disabled = !current.folder_id;
  }
  function selectHTML(options, value, label, cls = "") {
    return (
      `<select class="${esc(cls)}" aria-label="${esc(label)}">` +
      options
        .map(
          ([v, l]) =>
            `<option value="${esc(v)}" ${
              String(v) === String(value) ? "selected" : ""
            }>${esc(l)}</option>`,
        )
        .join("") +
      "</select>"
    );
  }
  function authenticationFields() {
    return `<details class="http-auth"><summary>Authentication</summary><label>Authorization<input type="password" class="http-auth-token" autocomplete="new-password" aria-label="Authorization" placeholder="${current.has_auth_token ? "Saved token" : "Bearer …"}" value="${esc(current.auth_token || "")}"></label>${current.has_auth_token ? `<label><input type="checkbox" class="clear-auth-token" ${current.clear_auth_token ? "checked" : ""}>Clear saved token</label>` : ""}</details>`;
  }
  function actionFields(a) {
    if (a.type === "python" || a.type === "shell") return snippetFields(a);
    if (a.preset === "archivebox") return apiFields(a) + authenticationFields();
    if (a.type === "http_request")
      return (
        selectHTML(
          ["POST", "PUT", "PATCH", "DELETE", "GET"].map((x) => [x, x]),
          a.method || "POST",
          "HTTP method",
          "http-method",
        ) +
        `<input type="url" aria-label="Request URL" placeholder="https://…" value="${esc(
          a.value,
        )}"><details><summary>Headers</summary><textarea aria-label="Request headers" class="http-headers mono" rows="2">${esc(
          a.headers || "{}",
        )}</textarea></details><details><summary>Body</summary><textarea aria-label="Request body" class="http-body mono" rows="3">${esc(a.body === undefined || a.body === null ? "" : JSON.stringify(a.body, null, 2))}</textarea></details>` +
        authenticationFields()
      );
    if (a.type === "set_config")
      return (
        selectHTML(
          initial.config_fields.map((x) => [x, x]),
          a.key,
          "Configuration key",
          "config-key",
        ) + `<input aria-label="Configuration value" value="${esc(a.value)}">`
      );
    if (a.type.endsWith("_plugin"))
      return selectHTML(
        initial.plugins.map((x) => [x, x === "ytdlp" ? "yt-dlp" : x]),
        a.value,
        "Plugin",
      );
    if (a.type === "visibility")
      return selectHTML(
        ["private", "unlisted", "public"].map((x) => [x, x]),
        a.value,
        "Visibility",
      );
    if (a.type === "move_folder")
      return selectHTML(
        [["", "No folder"], ...folders.Snapshot.map((f) => [f.id, f.name])],
        a.value,
        "Destination folder",
      );
    if (a.type === "set_depth")
      return selectHTML(
        [0, 1, 2, 3, 4].map((x) => [x, x]),
        a.value,
        "Maximum crawl depth",
      );
    return `<input aria-label="Tags" value="${esc(
      a.value,
    )}" placeholder="Tags, comma separated">`;
  }
  // Universal actions remain available for every model; typed actions edit existing
  // Snapshot/Crawl config and fields through the same app functions as their APIs.
  function availableActions() {
    return Object.entries(types).filter(
      ([key]) =>
        ["http_request", "python", "shell"].includes(key) ||
        (current.signal !== "DELETE" &&
          ((modelName(current.ref) === "Snapshot" && key !== "set_depth") ||
            (modelName(current.ref) === "Crawl" &&
              [
                "set_config",
                "set_depth",
                "disable_plugin",
                "enable_plugin",
              ].includes(key)))),
    );
  }
  function keepAvailableActions() {
    const available = new Set(availableActions().map(([key]) => key));
    current.actions = current.actions.filter((action) =>
      available.has(action.type),
    );
  }
  function renderActions() {
    const available = availableActions();
    available.push(["archivebox_api", "Call another ArchiveBox API..."]);
    $("add-action").innerHTML =
      '<option value="">＋ Add action…</option>' +
      available.map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
    $("actions").innerHTML = current.actions
      .map(
        (a, i) =>
          `<div class="action-row" data-index="${i}"><div class="action-top"><span class="action-number">${
            i + 1
          }</span><span class="action-type">${
            a.preset === "archivebox"
              ? "Call another ArchiveBox API..."
              : types[a.type]
          }</span><button class="icon-btn" data-move="-1" aria-label="Move action ${
            i + 1
          } up" ${!i ? "disabled" : ""}>${icons(
            "up",
          )}</button><button class="icon-btn" data-move="1" aria-label="Move action ${
            i + 1
          } down" ${i === current.actions.length - 1 ? "disabled" : ""}>${icons(
            "down",
          )}</button><button class="icon-btn danger" data-remove aria-label="Remove action ${
            i + 1
          }">${icons("close")}</button></div><div class="action-inputs ${
            ["python", "shell"].includes(a.type)
              ? "snippet-action"
              : a.preset === "archivebox"
                ? "api-action"
                : a.type === "http_request"
                  ? "http-action"
                  : ""
          }">${actionFields(a)}</div></div>`,
      )
      .join("");
    $("action-count").textContent = current.actions.length;
  }
  async function openEditor(id) {
    current = structuredClone(
      hooks.find((h) => h.id === id) || {
        id: null,
        name: "",
        ref: "archivebox.core.models.Snapshot",
        signal: "CREATE",
        folder_id: "",
        enabled: true,
        actions: [],
      },
    );
    $("editor").hidden = false;
    $("delete-hook").hidden = !current.id;
    $("process-logs").hidden = !current.id;
    $("process-logs").href = processLogsURL(current.id);
    $("workspace").classList.remove("full");
    $("editor-title").textContent = hooks.some((h) => h.id === id)
      ? "Edit webhook"
      : "New webhook";
    $("name").value = current.name;
    $("object-type").value = current.ref;
    $("enabled").setAttribute("aria-checked", current.enabled);
    $("stop").checked = !!current.stop_processing;
    $("stop-on-failure").checked = current.stop_on_failure !== false;
    $("save-state").textContent = "";
    $("preview").hidden = true;
    renderTimeline();
    fillScope();
    renderActions();
    renderList();
    document.querySelector(".editor-body").scrollTop = 0;
  }
  function closeEditor() {
    $("editor").hidden = true;
    $("workspace").classList.add("full");
    current = null;
    renderList();
  }
  $("object-type").innerHTML = models
    .map(
      ([name, emoji, ref]) =>
        `<option value="${esc(ref)}">${esc(emoji)} ${esc(name)}</option>`,
    )
    .join("");
  $("event-rows").innerHTML = models
    .flatMap(([model, emoji, ref]) =>
      eventsFor(ref).map(
        (e) =>
          `<tr><td>${icons(e.icon)} ${
            esc(e.label)
          }</td><td>${esc(emoji)} ${esc(model)}</td><td>${
            e.blocking
              ? "Blocking"
              : e.membership
                ? "On membership change"
                : "After event"
          }</td></tr>`,
      ),
    )
    .join("");
  $("hook-rows").onclick = async (e) => {
    const toggle = e.target.closest(".row-switch");
    if (toggle) {
      const h = hooks.find((h) => h.id === toggle.dataset.id);
      h.enabled = !h.enabled;
      if (current?.id === h.id) {
        current.enabled = h.enabled;
        $("enabled").setAttribute("aria-checked", h.enabled);
      }
      try {
        await post("save/", outboundWebhookData(h));
      } catch (error) {
        h.enabled = !h.enabled;
        toast(error.message);
      }
      renderList();
      return;
    }
    const row = e.target.closest("tr[data-id]");
    if (row) openEditor(row.dataset.id);
  };
  $("search").oninput = renderList;
  $("filter").onchange = renderList;
  $("new-hook").onclick = () => openEditor(null);
  $("close-editor").onclick = closeEditor;
  $("name").oninput = () => {
    current.name = $("name").value;
    $("name").setCustomValidity("");
    setDirty();
  };
  $("enabled").onclick = () => {
    current.enabled = !current.enabled;
    $("enabled").setAttribute("aria-checked", current.enabled);
    setDirty();
  };
  $("object-type").onchange = () => {
    current.ref = $("object-type").value;
    current.signal = "CREATE";
    current.folder_id = "";
    keepAvailableActions();
    renderTimeline();
    fillScope();
    renderActions();
    setDirty();
  };
  $("event-timeline").onchange = (e) => {
    current.signal = e.target.value;
    keepAvailableActions();
    renderTimeline();
    fillScope();
    renderActions();
    setDirty();
  };
  $("scope").onchange = () => {
    current.folder_id = $("scope").value;
    $("open-scope").disabled = !current.folder_id;
    setDirty();
  };
  $("stop").onchange = () => {
    current.stop_processing = $("stop").checked;
    setDirty();
  };
  $("stop-on-failure").onchange = () => {
    current.stop_on_failure = $("stop-on-failure").checked;
    setDirty();
  };
  $("actions").oninput = (e) => {
    const row = e.target.closest(".action-row");
    if (!row) return;
    const a = current.actions[Number(row.dataset.index)];
    if (e.target.classList.contains("http-auth-token")) {
      current.auth_token = e.target.value;
      setDirty();
      return;
    }
    if (e.target.classList.contains("clear-auth-token")) {
      current.clear_auth_token = e.target.checked;
      setDirty();
      return;
    }
    if (e.target.classList.contains("snippet-source")) {
      a.value = e.target.value;
      e.target.previousElementSibling.querySelector("code").innerHTML =
        highlighted(a.value);
      syncCodeEditor(e.target);
      setDirty();
      return;
    }
    if (e.target.classList.contains("api-operation")) {
      configureOperation(a, e.target.value);
      renderActions();
      setDirty();
      return;
    }
    if (e.target.dataset.apiField) {
      a.args ??= {};
      a.args[e.target.dataset.apiField] = e.target.value;
      setDirty();
      return;
    }
    if (e.target.classList.contains("config-key")) a.key = e.target.value;
    else if (e.target.classList.contains("http-method"))
      a.method = e.target.value;
    else if (e.target.classList.contains("http-headers"))
      a.headers = e.target.value;
    else if (e.target.classList.contains("http-body"))
      a.bodyText = e.target.value;
    else a.value = e.target.value;
    setDirty();
  };
  $("actions").onclick = (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    const i = Number(button.closest(".action-row").dataset.index);
    if (button.hasAttribute("data-remove")) current.actions.splice(i, 1);
    else {
      const j = i + Number(button.dataset.move);
      [current.actions[i], current.actions[j]] = [
        current.actions[j],
        current.actions[i],
      ];
    }
    renderActions();
    setDirty();
  };
  $("add-action").onchange = () => {
    const type = $("add-action").value;
    if (!type) return;
    if (type === "python" || type === "shell") {
      current.actions.push({ type, value: snippetDefaults[type] });
      renderActions();
      setDirty();
      return;
    }
    if (type === "archivebox_api") {
      current.actions.push({
        type: "http_request",
        preset: "archivebox",
        operation: "",
        args: {},
        method: "POST",
        value: "",
      });
      renderActions();
      setDirty();
      return;
    }
    current.actions.push({
      type,
      key: type === "set_config" ? "YTDLP_MAX_SIZE" : undefined,
      method: "POST",
      headers: "{}",
      value: type.endsWith("_plugin")
        ? "ytdlp"
        : type === "set_depth"
          ? "1"
          : type === "visibility"
            ? "private"
            : "",
    });
    renderActions();
    setDirty();
  };
  $("save").onclick = async () => {
    try {
      const response = await post("save/", outboundWebhookData(current));
      const saved = editorWebhook(response.hook),
        i = hooks.findIndex((h) => h.id === saved.id);
      if (i < 0) hooks.push(saved);
      else hooks[i] = saved;
      current.id = saved.id;
      current.has_auth_token = saved.has_auth_token;
      current.auth_token = "";
      current.clear_auth_token = false;
      renderActions();
      $("delete-hook").hidden = false;
      $("process-logs").hidden = false;
      $("process-logs").href = processLogsURL(saved.id);
      $("editor-title").textContent = "Edit webhook";
      $("save-state").textContent = "Saved";
      renderList();
      renderActivity();
      toast("Webhook saved");
      history.replaceState(null, "", baseURL + "?webhook=" + current.id);
    } catch (error) {
      toast(error.message);
    }
  };
  $("delete-hook").onclick = async () => {
    if (!current?.id || !confirm("Delete this webhook?")) return;
    try {
      await post(current.id + "/delete/", {});
      hooks = hooks.filter((h) => h.id !== current.id);
      closeEditor();
      renderActivity();
      toast("Webhook deleted");
    } catch (error) {
      toast(error.message);
    }
  };
  $("open-scope").onclick = () => {
    if (current.folder_id)
      window.open(
        "/admin/core/snapshot/?folder=" + encodeURIComponent(current.folder_id),
        "_blank",
        "noopener",
      );
  };
  $("preview-button").onclick = async () => {
    try {
      const response = await post("preview/", outboundWebhookData(current));
      const output = current.actions.map(actionSummary).join("\n");
      $("preview-content").innerHTML = response.objects.length
        ? `<table><thead><tr><th>${esc(modelName(current.ref))}</th><th>Planned actions</th></tr></thead><tbody>` +
          response.objects
            .map(
              (obj) =>
                `<tr><td>${esc(obj.label)}<details><summary>Event input</summary><pre>${esc(JSON.stringify(obj.payload, null, 2))}</pre></details></td><td class="preview-output">${esc(output).replace(/\n/g, "<br>")}</td></tr>`,
            )
            .join("") +
          "</tbody></table>"
        : '<div class="empty">No saved objects</div>';
      $("preview").hidden = false;
      $("preview").scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (error) {
      toast(error.message);
    }
  };
  $("close-preview").onclick = () => ($("preview").hidden = true);
  function processLogsURL(id) {
    return (
      "/admin/machine/process/?worker_type=webhook&q=" + encodeURIComponent(id)
    );
  }
  function renderActivity() {
    // Last delivery uses existing webhook fields; complete per-action history
    // is available through Process logs, without a second audit model.
    const activity = hooks
      .map((hook) => {
        const success =
          hook.last_success &&
          (!hook.last_failure || hook.last_success >= hook.last_failure);
        return {
          hook,
          time: success ? hook.last_success : hook.last_failure,
          success,
        };
      })
      .filter((row) => row.time)
      .sort((a, b) => b.time.localeCompare(a.time));
    $("activity-empty").hidden = activity.length > 0;
    $("activity-rows").innerHTML = activity
      .map(
        ({ hook, time, success }) =>
          `<tr><td class="small muted nowrap">${esc(new Date(time).toLocaleString())}</td><td>${esc(hook.name)}</td><td class="small">${esc(eventOf(hook).label)}</td><td><span class="badge">${success ? "Succeeded" : "Failed"}</span> <a class="icon-btn" href="${processLogsURL(hook.id)}" aria-label="Process logs for ${esc(hook.name)}" title="Process logs">${icons("external")}</a>${hook.last_response ? `<details><summary>Response</summary><pre>${esc(hook.last_response)}</pre></details>` : ""}</td></tr>`,
      )
      .join("");
  }
  document.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = async () => {
        document
          .querySelectorAll("[data-tab]")
          .forEach((t) => t.setAttribute("aria-selected", t === b));
        ["subscriptions", "activity", "events"].forEach(
          (id) => ($(id).hidden = id !== b.dataset.tab),
        );
        closeEditor();
        if (b.dataset.tab === "activity") {
          try {
            const response = await fetch(baseURL + "data/");
            if (!response.ok) throw Error("Could not load activity");
            const data = await response.json();
            hooks = data.hooks.map(editorWebhook);
            renderActivity();
          } catch (error) {
            toast(error.message);
          }
        }
      }),
  );
  function outboundWebhookData(webhook) {
    return {
      id: webhook.id,
      auth_token: webhook.auth_token || "",
      clear_auth_token: !!webhook.clear_auth_token,
      name: webhook.name,
      ref: webhook.ref,
      signal: webhook.signal,
      enabled: webhook.enabled,
      folder_id: webhook.folder_id || null,
      stop_processing: !!webhook.stop_processing,
      stop_on_failure: webhook.stop_on_failure !== false,
      actions: webhook.actions.map((action) => {
        const { type, value } = action;
        if (type === "http_request") {
          const request = requestFor(action, true);
          return {
            type,
            method: request.method,
            endpoint: request.url,
            headers:
              typeof request.headers === "string"
                ? JSON.parse(request.headers)
                : request.headers,
            body: request.body ?? null,
          };
        }
        // Persist native configuration and model fields, not the editor's value/key.
        if (type === "disable_plugin")
          return { type: "disable_plugins", disable_plugins: [value] };
        if (type === "enable_plugin")
          return { type: "enable_plugins", enable_plugins: [value] };
        if (type === "set_config")
          return {
            type: "config_overrides",
            config_overrides: { [action.key]: value },
          };
        if (type === "set_depth")
          return { type: "max_depth", max_depth: Number(value) };
        if (type === "move_folder")
          return { type: "folder", folder_id: value || null };
        if (type === "visibility")
          return { type: "permissions", permissions: value };
        if (type === "python") return { type, code: value };
        if (type === "shell") return { type, command: value };
        return { type, [type]: value };
      }),
    };
  }

  let apiSchema = null,
    apiOperations = [],
    apiError = "";
  function deref(schema) {
    if (!schema) return {};
    if (schema.$ref) {
      const value = schema.$ref
        .split("/")
        .slice(1)
        .reduce((obj, key) => obj?.[key], apiSchema);
      return {
        ...value,
        ...Object.fromEntries(
          Object.entries(schema).filter(([key]) => key !== "$ref"),
        ),
      };
    }
    return schema;
  }
  function concreteSchema(schema) {
    schema = deref(schema);
    if (schema.anyOf || schema.oneOf) {
      const choices = schema.anyOf || schema.oneOf;
      return {
        ...schema,
        ...deref(choices.find((s) => s.type !== "null") || choices[0]),
      };
    }
    return schema;
  }
  // Reconstruct the generated API form from the HTTP request itself. There is no
  // persisted operation ID that could drift when Ninja routes change.
  function hydrateAPIPreset(action) {
    if (
      action.type !== "http_request" ||
      action.preset ||
      !action.value.startsWith("/api/")
    )
      return;
    const url = new URL(action.value, location.origin),
      path = decodeURIComponent(url.pathname);
    for (const op of apiOperations.filter(
      (op) => op.method === action.method,
    )) {
      const names = [];
      const pattern = op.path
        .split(/(\{[^}]+\})/)
        .map((part) => {
          if (part.startsWith("{")) {
            names.push(part.slice(1, -1));
            return "([^/]+)";
          }
          return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        })
        .join("");
      const match = path.match(new RegExp("^" + pattern + "$"));
      if (!match) continue;
      const args = {};
      for (const field of fieldsFor(op)) {
        let value;
        if (field.location === "path")
          value = match[names.indexOf(field.name) + 1];
        else if (field.location === "query")
          value = url.searchParams.get(field.name);
        else if (field.location === "header")
          value = JSON.parse(action.headers || "{}")[field.name];
        else if (field.location === "body_raw") value = action.body;
        else if (field.location === "body") value = action.body?.[field.name];
        if (value !== undefined && value !== null)
          args[fieldKey(field)] =
            typeof value === "object"
              ? JSON.stringify(value, null, 2)
              : String(value);
      }
      action.preset = "archivebox";
      action.operation = op.id;
      action.args = args;
      return;
    }
  }
  function operationOf(a) {
    return apiOperations.find((op) => op.id === a.operation);
  }
  function fieldsFor(op) {
    if (!op) return [];
    const fields = (op.parameters || [])
      .filter((p) => ["path", "query", "header"].includes(p.in))
      .map((p) => ({ ...p, location: p.in }));
    const schema = concreteSchema(
      op.requestBody?.content?.["application/json"]?.schema,
    );
    if (schema.properties) {
      for (const [name, property] of Object.entries(schema.properties))
        fields.push({
          name,
          location: "body",
          schema: property,
          required: (schema.required || []).includes(name),
        });
    } else if (op.requestBody)
      fields.push({
        name: "body",
        location: "body_raw",
        schema,
        required: op.requestBody.required,
      });
    return fields;
  }
  function fieldKey(field) {
    return field.location + ":" + field.name;
  }
  function fieldValue(a, field) {
    return a.args?.[fieldKey(field)] ?? "";
  }
  function inputField(a, field) {
    const schema = concreteSchema(field.schema),
      key = fieldKey(field),
      value = fieldValue(a, field);
    const label = schema.title || field.name.replaceAll("_", " ");
    const attrs = `data-api-field="${esc(key)}" aria-label="${esc(field.name)} (${
      field.location
    })" title="${esc(field.description || schema.description || "")}"`;
    let input;
    if (schema.enum) {
      input =
        `<select ${attrs}><option value="">—</option>` +
        schema.enum
          .map(
            (v) =>
              `<option value="${esc(v)}" ${
                String(v) === String(value) ? "selected" : ""
              }>${esc(v)}</option>`,
          )
          .join("") +
        "</select>";
    } else if (schema.type === "boolean") {
      input = `<select ${attrs}><option value="">—</option><option value="true" ${
        value === "true" ? "selected" : ""
      }>True</option><option value="false" ${
        value === "false" ? "selected" : ""
      }>False</option></select>`;
    } else if (
      ["object", "array"].includes(schema.type) ||
      field.location === "body_raw"
    ) {
      input = `<textarea ${attrs} rows="2" spellcheck="false" placeholder="${
        schema.type === "array" ? "[]" : "{}"
      }">${esc(value)}</textarea>`;
    } else {
      input = `<input ${attrs} value="${esc(value)}" placeholder="${esc(
        schema.default ?? schema.format ?? schema.type ?? "",
      )}" ${
        schema.type === "integer" || schema.type === "number"
          ? 'inputmode="decimal"'
          : ""
      }>`;
    }
    return `<label class="api-field"><span>${esc(label)}${
      field.required ? '<b aria-label="required"> *</b>' : ""
    }<small>${
      field.location === "body_raw" ? "body" : field.location
    }</small></span>${input}</label>`;
  }
  function apiFields(a) {
    if (!apiSchema)
      return `<div class="small muted">${
        apiError || "Loading API operations…"
      }</div>`;
    const op = operationOf(a),
      groups = [...new Set(apiOperations.map((o) => o.group))];
    let html =
      '<label class="api-operation-label">API operation<select class="api-operation" aria-label="API operation"><option value="">Choose an operation…</option>' +
      groups
        .map(
          (group) =>
            `<optgroup label="${esc(group)}">` +
            apiOperations
              .filter((o) => o.group === group)
              .map(
                (o) =>
                  `<option value="${esc(o.id)}" ${
                    o.id === a.operation ? "selected" : ""
                  }>${o.method} · ${esc(o.summary || o.path)}</option>`,
              )
              .join("") +
            "</optgroup>",
        )
        .join("") +
      "</select></label>";
    if (!op) return html;
    html += `<div class="api-route"><span>${op.method}</span><code>${esc(
      op.path,
    )}</code></div>`;
    const fields = fieldsFor(op),
      required = fields.filter((f) => f.required),
      optional = fields.filter((f) => !f.required);
    html += required.map((f) => inputField(a, f)).join("");
    if (optional.length)
      html +=
        `<details class="api-optional"><summary>Optional fields <span class="count">${optional.length}</span></summary>` +
        optional.map((f) => inputField(a, f)).join("") +
        "</details>";
    return html;
  }
  function configureOperation(a, id) {
    const op = apiOperations.find((o) => o.id === id);
    a.operation = id;
    a.args = {};
    a.method = op?.method || "POST";
    a.value = op?.path || "";
    if (op)
      for (const field of fieldsFor(op)) {
        if (
          field.location === "path" &&
          field.name === modelName(current.ref).toLowerCase() + "_id"
        )
          a.args[fieldKey(field)] = "{{ object.id }}";
      }
  }
  function typedValue(value, field) {
    const s = concreteSchema(field.schema);
    if (value.includes("{{")) return value;
    if (
      ["object", "array", "boolean", "integer", "number"].includes(s.type) ||
      field.location === "body_raw"
    ) {
      const parsed = JSON.parse(value);
      if (s.type === "integer" && !Number.isInteger(parsed))
        throw Error("Enter an integer for " + field.name);
      if (s.type === "number" && typeof parsed !== "number")
        throw Error("Enter a number for " + field.name);
      if (s.type === "boolean" && typeof parsed !== "boolean")
        throw Error("Enter true or false for " + field.name);
      if (s.type === "array" && !Array.isArray(parsed))
        throw Error("Enter an array for " + field.name);
      if (
        s.type === "object" &&
        (!parsed || Array.isArray(parsed) || typeof parsed !== "object")
      )
        throw Error("Enter an object for " + field.name);
      return parsed;
    }
    return value;
  }
  // WHY one compiler: the API picker only fills an HTTP request. operationId and
  // per-field editor values must not become a second delivery/execution system.
  // Paths, methods, parameter schemas and bodies come from Ninja's OpenAPI output.
  function requestFor(a, validate = false) {
    if (a.preset !== "archivebox")
      return {
        method: a.method || "POST",
        url: a.value,
        headers: a.headers || "{}",
        body:
          a.bodyText !== undefined
            ? a.bodyText
              ? JSON.parse(a.bodyText)
              : null
            : a.body,
      };
    const op = operationOf(a);
    if (!op) {
      if (validate) throw Error("Choose an API operation");
      return { method: "", url: "Choose an API operation" };
    }
    let url = op.path,
      body = {},
      headers = {},
      query = [];
    for (const field of fieldsFor(op)) {
      const value = fieldValue(a, field);
      if (value === "") {
        if (validate && field.required) throw Error("Enter " + field.name);
        continue;
      }
      const typed = typedValue(String(value), field);
      if (field.location === "path")
        url = url.replace(
          "{" + field.name + "}",
          String(value).includes("{{") ? value : encodeURIComponent(value),
        );
      else if (field.location === "query")
        query.push(
          encodeURIComponent(field.name) +
            "=" +
            encodeURIComponent(
              typeof typed === "object" ? JSON.stringify(typed) : String(typed),
            ),
        );
      else if (field.location === "header") headers[field.name] = typed;
      else if (field.location === "body_raw") body = typed;
      else body[field.name] = typed;
    }
    if (query.length) url += "?" + query.join("&");
    return {
      method: op.method,
      url,
      headers,
      body: fieldsFor(op).some(
        (f) =>
          (f.location === "body_raw" || f.location === "body") &&
          fieldValue(a, f) !== "",
      )
        ? body
        : undefined,
    };
  }
  function actionSummary(a) {
    if (["python", "shell"].includes(a.type))
      return types[a.type] + " · JSON stdin + UUID, type, event arguments";
    if (a.type !== "http_request")
      return (
        types[a.type] +
        ": " +
        (a.key ? a.key + " = " : "") +
        (a.value === "ytdlp" ? "yt-dlp" : a.value)
      );
    try {
      const r = requestFor(a);
      return (
        r.method +
        " " +
        r.url +
        (r.body ? "\n" + JSON.stringify(r.body, null, 2) : "")
      );
    } catch (error) {
      return error.message;
    }
  }
  // Fetch on load so adding an API endpoint needs no edits to this action catalog.
  async function loadCatalog() {
    try {
      const response = await fetch(root.dataset.apiUrl, { cache: "no-store" });
      if (!response.ok) throw Error();
      apiSchema = await response.json();
      apiOperations = Object.entries(apiSchema.paths).flatMap(([path, item]) =>
        Object.entries(item)
          .filter(([method]) =>
            [
              "get",
              "post",
              "put",
              "patch",
              "delete",
              "head",
              "options",
            ].includes(method),
          )
          .map(([method, op]) => ({
            ...op,
            path,
            method: method.toUpperCase(),
            id: op.operationId || method + " " + path,
            group: op.tags?.[0] || "API",
            parameters: [...(item.parameters || []), ...(op.parameters || [])],
          })),
      );
    } catch {
      apiError = "API catalog unavailable";
    }
    hooks.forEach((h) => h.actions.forEach(hydrateAPIPreset));
    if (current) {
      current.actions.forEach(hydrateAPIPreset);
      renderActions();
    }
  }
  loadCatalog();

  const snippetDefaults = {
    python:
      'import json\nimport sys\n\nobject_id, object_type, event_type, *extra_args = sys.argv[1:]\ndata = json.load(sys.stdin)\n\n# Object fields and event metadata are already in data.\nprint(f"{event_type}: {object_type} {object_id}")\nprint(json.dumps(data, indent=2))\n\n# Optional: call ArchiveBox\'s Python APIs.\n# from archivebox.config.django import setup_django\n# setup_django()\n',
    shell:
      '#!/usr/bin/env bash\nset -euo pipefail\n\nobject_id="$1"\nobject_type="$2"\nevent_type="$3"\nshift 3  # Remaining event arguments are in "$@".\n\n# Object fields and event metadata arrive as JSON on stdin.\ndata="$(cat)"\nprintf \'%s\\n\' "$data" > "hook-${object_id}.json"\nprintf \'%s: %s %s\\n\' "$event_type" "$object_type" "$object_id"\n\n# printf \'%s\\n\' "$data" | jq \'.url\'\n# archivebox status\n',
  };
  // Cosmetic highlighting only; the textarea remains the source of truth for code.
  // Escape every token before inserting markup so snippets never execute in this UI.
  function highlighted(code) {
    const pattern =
      /(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:import|from|as|if|else|for|in|is|not|None|True|False|def|return|with|try|except|raise|class)\b|\b(?:print|json|sys|setup_django|apps|set|printf|cat|echo|jq|archivebox)\b|\$[A-Za-z_][A-Za-z_0-9]*|\b\d+\b)/g;
    let result = "",
      offset = 0;
    for (const m of code.matchAll(pattern)) {
      result += esc(code.slice(offset, m.index));
      const t = m[0],
        kind = t.startsWith("#")
          ? "comment"
          : t.startsWith('"') || t.startsWith("'")
            ? "string"
            : /^\d+$/.test(t)
              ? "number"
              : t.startsWith("$")
                ? "variable"
                : /^(import|from|as|if|else|for|in|is|not|None|True|False|def|return|with|try|except|raise|class)$/.test(
                      t,
                    )
                  ? "keyword"
                  : "function";
      result += `<span class="syntax-${kind}">${esc(t)}</span>`;
      offset = m.index + t.length;
    }
    return result + esc(code.slice(offset)) + "\n";
  }
  function snippetFields(a) {
    const language = a.type === "python" ? "Python" : "Bash";
    return `<div class="code-caption"><span>${language}</span><span>JSON stdin · $1 UUID · $2 object_type · $3 event</span></div><div class="code-editor"><pre aria-hidden="true"><code>${highlighted(a.value)}</code></pre><textarea class="snippet-source" aria-label="${language} code" spellcheck="false" autocapitalize="off" autocomplete="off" wrap="off">${esc(
      a.value,
    )}</textarea></div>`;
  }
  function syncCodeEditor(input) {
    const pre = input.previousElementSibling;
    pre.scrollTop = input.scrollTop;
    pre.scrollLeft = input.scrollLeft;
  }
  document.addEventListener(
    "scroll",
    (e) => {
      if (e.target.classList?.contains("snippet-source"))
        syncCodeEditor(e.target);
    },
    true,
  );
  document.addEventListener("keydown", (e) => {
    if (
      e.key === "Tab" &&
      e.target.classList.contains("snippet-source") &&
      !e.shiftKey
    ) {
      e.preventDefault();
      e.target.setRangeText(
        "    ",
        e.target.selectionStart,
        e.target.selectionEnd,
        "end",
      );
      e.target.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });

  renderList();
  renderActivity();
  const selected = new URLSearchParams(location.search).get("webhook");
  if (selected && hooks.some((h) => h.id === selected)) {
    openEditor(selected);
    if (new URLSearchParams(location.search).has("preview"))
      $("preview-button").click();
  }
  const selectedView = new URLSearchParams(location.search).get("view");
  if (["subscriptions", "activity", "events"].includes(selectedView))
    document.querySelector(`[data-tab="${selectedView}"]`).click();
  function layout() {
    root.style.setProperty(
      "--webhook-top",
      Math.max(0, root.getBoundingClientRect().top) + "px",
    );
  }
  new ResizeObserver(layout).observe(document.getElementById("header"));
  window.addEventListener("resize", layout);
  layout();
})();
