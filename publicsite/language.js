/* Optional landing-page languages. Remove this file, its script tag, and the
   es/fr/zh/ru/ar folders to retire the feature. No shared-site dependency. */
(() => {
  const script = document.currentScript;
  if (!script) return;
  const base = new URL('.', script.src);
  const languages = [
    ['en', '🇬🇧', 'English', 'Choose language'],
    ['es', '🇪🇸', 'Español', 'Elegir idioma'],
    ['fr', '🇫🇷', 'Français', 'Choisir la langue'],
    ['zh', '🇨🇳', '中文', '选择语言'],
    ['ru', '🇷🇺', 'Русский', 'Выбрать язык'],
    ['ar', '🇸🇦', 'العربية', 'اختر اللغة'],
  ];
  const codes = languages.map(([code]) => code);
  const relative = location.pathname.startsWith(base.pathname)
    ? location.pathname.slice(base.pathname.length) : null;
  const current = codes.includes(relative?.split('/')[0]) ? relative.split('/')[0] : 'en';
  const key = `archivebox-language:${base.pathname}`;
  const target = code => {
    const url = new URL(code === 'en' ? './' : `${code}/`, base);
    url.search = location.search;
    url.searchParams.delete('lang');
    url.hash = location.hash;
    return url;
  };
  // Explicit language URLs always win; only the original entry page detects.
  if (relative === '' || relative === 'index.html') {
    let saved;
    try { saved = localStorage.getItem(key); } catch { /* Storage is optional. */ }
    const detected = (navigator.languages || [navigator.language])
      .map(language => language.toLowerCase().split('-')[0])
      .find(language => codes.includes(language));
    const requested = new URL(location.href).searchParams.get('lang');
    const preferred = codes.includes(requested) ? requested : codes.includes(saved) ? saved : detected || 'en';
    if (preferred !== 'en') {
      location.replace(target(preferred));
      return;
    }
  }
  const active = languages.find(([code]) => code === current);
  const style = document.createElement('style');
  style.textContent = `
    .abx-language{position:relative;flex:0 0 auto;direction:ltr;font:13px/1.4 system-ui,sans-serif;color:#4d424b;letter-spacing:normal}
    .abx-language>summary{display:flex;align-items:center;justify-content:center;gap:5px;min-width:52px;min-height:36px;padding:4px;cursor:pointer;list-style:none;border-radius:6px;white-space:nowrap}
    .abx-language>summary::-webkit-details-marker{display:none}
    .abx-language>summary:hover{background:#f4e8ed}
    .abx-language>summary:focus-visible,.abx-language a:focus-visible{outline:2px solid #9b2854;outline-offset:2px}
    .abx-language .abx-language-flag{font-size:18px;line-height:1}
    .abx-language .abx-language-options{position:absolute;right:0;top:100%;z-index:1100;min-width:160px;padding:6px;background:#fcfaf7;color:#28252a;border:1px solid #ded4d8;border-radius:8px;box-shadow:0 6px 24px #28252a20;text-align:left}
    .abx-language .abx-language-options a{display:flex;gap:9px;align-items:center;margin:0;padding:8px 10px;border-radius:4px;color:#4d424b;text-decoration:none;font:14px/1.4 system-ui,sans-serif;white-space:nowrap}
    .abx-language .abx-language-options a:hover,.abx-language a[aria-current=page]{background:#f4e8ed}
    .abx-language-fallback{position:fixed;right:12px;top:10px;z-index:1000;background:#fcfaf7;border:1px solid #ded4d8;border-radius:8px}
    html[dir=rtl] .abx-header{direction:ltr}
    html[dir=rtl] main{direction:rtl;text-align:right}
    html[dir=rtl] pre,html[dir=rtl] code{direction:ltr;unicode-bidi:isolate}
  `;
  document.head.append(style);
  const menu = document.createElement('details');
  menu.className = 'abx-language';
  const summary = document.createElement('summary');
  summary.setAttribute('aria-label', `${active[3]}: ${active[2]}`);
  summary.title = active[3];
  const flag = document.createElement('span');
  flag.className = 'abx-language-flag';
  flag.setAttribute('aria-hidden', 'true');
  flag.textContent = active[1];
  const codeLabel = document.createElement('span');
  codeLabel.textContent = current.toUpperCase();
  summary.append(flag, codeLabel);
  const options = document.createElement('div');
  options.className = 'abx-language-options';
  for (const [code, emoji, name] of languages) {
    const link = document.createElement('a');
    link.href = target(code).href;
    link.lang = code;
    link.hreflang = code;
    if (code === current) link.setAttribute('aria-current', 'page');
    link.textContent = `${emoji} ${name}`;
    link.addEventListener('click', () => {
      try { localStorage.setItem(key, code); } catch {
        const url = target(code);
        url.searchParams.set('lang', code);
        link.href = url.href;
      }
    });
    options.append(link);
  }
  menu.append(summary, options);
  const fitMenu = () => {
    if (!menu.open) return;
    options.style.transform = '';
    const bounds = options.getBoundingClientRect();
    const shift = Math.max(8 - bounds.left, Math.min(0, innerWidth - 8 - bounds.right));
    options.style.transform = `translateX(${shift}px)`;
  };
  summary.addEventListener('click', event => {
    event.preventDefault();
    menu.open = !menu.open;
    fitMenu();
  });
  menu.addEventListener('toggle', fitMenu);
  window.addEventListener('resize', fitMenu);
  const nav = document.querySelector('.abx-header .abx-nav');
  if (nav) nav.append(menu);
  else { menu.classList.add('abx-language-fallback'); document.body.append(menu); }
  document.addEventListener('click', event => { if (!menu.contains(event.target)) menu.open = false; });
  menu.addEventListener('keydown', event => {
    if (event.key === 'Escape') { menu.open = false; summary.focus(); }
  });
})();
