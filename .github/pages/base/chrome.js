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
