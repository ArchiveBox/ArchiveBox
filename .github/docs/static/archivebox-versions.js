/* ArchiveBox RTD picker policy. No requests, credentials, or documentation edits.
 * RTD event is read-only input: internal flyout rendering precedes the public
 * event, so changing its payload is not a supported rendering hook.
 * Targets: addons readthedocs-flyout shadow dl.versions, RTD theme 3.1 select,
 * and the legacy theme's Versions definition list. Other navigation is untouched.
 */
(function () {
  "use strict";

  function parse(slug) {
    const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-?rc(\d*))?$/i.exec(slug);
    if (!match) return null;
    return { slug, major: +match[1], minor: +match[2], patch: +match[3],
      rc: match[4] === undefined ? null : +(match[4] || 0) };
  }
  function compare(a, b) {
    return a.major - b.major || a.minor - b.minor || a.patch - b.patch ||
      (a.rc === null ? Infinity : a.rc) - (b.rc === null ? Infinity : b.rc) ||
      a.slug.localeCompare(b.slug);
  }
  function select(versions) {
    const published = versions.filter(v => v.active !== false && v.built !== false && !v.hidden);
    const parsed = published.map(v => parse(v.slug)).filter(Boolean);
    const minors = [...new Set(parsed.sort((a, b) => compare(b, a))
      .map(v => `${v.major}.${v.minor}`))];
    const winners = minors.map((minor, index) => parsed.filter(v =>
      `${v.major}.${v.minor}` === minor && (index < 2 ? v.rc !== null : v.rc === null))
      .sort((a, b) => compare(b, a))[0]).filter(Boolean).map(v => v.slug);
    return ["latest", "dev"].filter(slug => published.some(v => v.slug === slug)).concat(winners);
  }

  // Export only the pure policy for Node verification; browser has no new globals.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { parse, select };
    return;
  }
  const project = document.querySelector('meta[name="readthedocs-project-slug"]')?.content;
  if (project && project !== "archivebox") return;
  if (!document.querySelector('meta[name="readthedocs-addons-api-version"]')) {
    const meta = document.createElement("meta");
    meta.name = "readthedocs-addons-api-version";
    meta.content = "1";
    document.head.append(meta);
  }
  let wanted = null;
  const watched = new WeakSet();
  function reconcile(container) {
    if (!wanted) return;
    const isSelect = container.tagName === "SELECT";
    const children = [...container.children].filter(n => isSelect ? n.tagName === "OPTION" : n.tagName === "DD");
    const slug = n => isSelect ? n.value : n.querySelector("a")?.textContent.trim();
    const selected = isSelect ? container.value : null;
    const kept = wanted.map(s => children.find(n => slug(n) === s)).filter(Boolean);
    const current = children.filter(n => wanted.includes(slug(n)));
    for (const node of children) if (!wanted.includes(slug(node))) node.remove();
    if (kept.some((node, i) => node !== current[i])) {
      for (const node of kept) container.append(node);
    }
    if (isSelect) {
      container.value = selected;
      if (!kept.some(n => n.value === selected)) container.selectedIndex = -1;
    }
  }
  function watch(container) {
    reconcile(container);
    if (watched.has(container)) return;
    watched.add(container);
    new MutationObserver(() => reconcile(container)).observe(container, { childList: true, subtree: true });
  }
  function scan() {
    if (!wanted) return;
    document.querySelectorAll("div.switch-menus > div.version-switch select").forEach(watch);
    document.querySelectorAll(".rst-other-versions dl").forEach(dl => {
      if (dl.querySelector("dt")?.textContent.trim() === "Versions") watch(dl);
    });
    document.querySelectorAll("readthedocs-flyout").forEach(host => {
      const root = host.shadowRoot;
      if (!root) return;
      root.querySelectorAll("dl.versions").forEach(watch);
      if (!watched.has(root)) {
        watched.add(root);
        new MutationObserver(() => root.querySelectorAll("dl.versions").forEach(watch))
          .observe(root, { childList: true, subtree: true });
      }
    });
  }
  customElements.whenDefined("readthedocs-flyout").then(scan);
  let discovery;
  let stopDiscovery;
  function ready(eventData) {
    const config = eventData.data();
    if (config.projects?.current?.slug !== "archivebox" || !Array.isArray(config.versions?.active)) return;
    wanted = select(config.versions.active);
    if (!wanted.length) return;
    scan();
    // Discover asynchronously inserted picker containers for at most 10 seconds.
    // Afterwards, observers remain scoped to known picker/shadow containers only.
    discovery?.disconnect();
    clearTimeout(stopDiscovery);
    discovery = new MutationObserver(scan);
    discovery.observe(document.body, { childList: true, subtree: true });
    stopDiscovery = setTimeout(() => discovery.disconnect(), 10000);
  }
  document.addEventListener("readthedocs-addons-data-ready", event => ready(event.detail));
  if (globalThis.ReadTheDocsEventData) ready(globalThis.ReadTheDocsEventData);
})();
