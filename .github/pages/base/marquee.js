/* Scroll real gallery links once; keep them usable without JavaScript. */
(() => {
  document.querySelectorAll('.abx-marquee').forEach(gallery => {
    const viewport = gallery.querySelector('.abx-marquee-viewport');
    const button = gallery.querySelector('.abx-marquee-toggle');
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let paused = reducedMotion.matches;
    let hovering = false;
    let focused = false;
    let visible = false;
    let frame;
    let previous;
    let offset = viewport.scrollLeft;
    button.hidden = false;
    function label() {
      button.textContent = paused ? 'Play screenshots' : 'Pause screenshots';
      button.setAttribute('aria-label', button.textContent);
    }
    function tick(time) {
      const distance = viewport.scrollWidth - viewport.clientWidth;
      if (distance <= 0) return;
      if (previous !== undefined) {
        offset = Math.min(offset + Math.min(time - previous, 50) * 0.035, distance);
        viewport.scrollTo({ left: offset, behavior: 'instant' });
      }
      if (offset >= distance - 1) { paused = true; label(); return; }
      previous = time;
      frame = window.requestAnimationFrame(tick);
    }
    function sync() {
      window.cancelAnimationFrame(frame);
      previous = undefined;
      offset = viewport.scrollLeft;
      label();
      if (!paused && !hovering && !focused && visible && !document.hidden) frame = window.requestAnimationFrame(tick);
    }
    button.addEventListener('click', () => {
      paused = !paused;
      if (paused) viewport.scrollTo({ left: viewport.scrollLeft, behavior: 'instant' });
      if (!paused && viewport.scrollLeft >= viewport.scrollWidth - viewport.clientWidth - 1) viewport.scrollLeft = 0;
      sync();
    });
    viewport.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') { hovering = true; sync(); } });
    viewport.addEventListener('pointerleave', () => { hovering = false; sync(); });
    viewport.addEventListener('focusin', () => { focused = true; sync(); });
    viewport.addEventListener('focusout', event => { focused = viewport.contains(event.relatedTarget); sync(); });
    function pauseForInteraction() { paused = true; sync(); }
    viewport.addEventListener('pointerdown', pauseForInteraction);
    viewport.addEventListener('wheel', pauseForInteraction, { passive: true });
    viewport.addEventListener('keydown', pauseForInteraction);
    reducedMotion.addEventListener('change', () => { paused = reducedMotion.matches; sync(); });
    document.addEventListener('visibilitychange', sync);
    new window.IntersectionObserver(([entry]) => { visible = entry.isIntersecting; sync(); }).observe(gallery);
    new window.ResizeObserver(sync).observe(viewport);
    viewport.querySelectorAll('img').forEach(image => image.addEventListener('load', sync));
    label();
  });
})();
