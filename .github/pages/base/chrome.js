/*
Shared ArchiveBox website navigation styles and behavior.
Keep this file in sync with .github/pages/base/chrome.js in:
ArchiveBox/ArchiveBox, abx-plugins, abxpkg, android-archivebox,
electron-archivebox, ios-archivebox, and archivebox-browser-extension (all repositories are in the ArchiveBox GitHub organization).
Each site builds its committed copy independently; there is no central generator.
Keep site-specific navigation, CTAs, and extra footer links outside this base.
Also review the inline navbar/footer in abx-dl/website/index.html and
 debian-archivebox/website/index.html when shared links or branding change.
*/
(() => {
  const menu = document.querySelector('.abx-apps');
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu?.open) { menu.open = false; menu.querySelector('summary').focus(); }
  });
  document.addEventListener('click', event => { if (menu?.open && !menu.contains(event.target)) menu.open = false; });
  function revealAnchor() {
    let target;
    try { target = document.getElementById(decodeURIComponent(window.location.hash.slice(1))); } catch { return; }
    if (!target) return;
    let details = target.closest('details');
    let opened = false;
    while (details) { if (!details.open) { details.open = true; opened = true; } details = details.parentElement.closest('details'); }
    if (opened) window.requestAnimationFrame(() => target.scrollIntoView());
  }
  window.addEventListener('hashchange', revealAnchor);
  revealAnchor();
})();
