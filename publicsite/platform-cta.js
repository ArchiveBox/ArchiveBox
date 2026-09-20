// Highlight platform choices without changing links, tabs, or navigation.
(() => {
  const ua = navigator.userAgent;
  const platform = /Android/i.test(ua) ? 'android'
    : /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1) ? 'ios'
    : /Windows/i.test(ua) ? 'windows'
    : /Macintosh|Mac OS X/i.test(ua) ? 'macos'
    : /Linux/i.test(ua) ? 'linux' : '';
  document.querySelectorAll('[data-platform-group]').forEach(group => {
    const choices = Array.from(group.querySelectorAll('[data-platform]'));
    const matches = choices.filter(choice => platform && choice.dataset.platform.split(' ').includes(platform));
    const highlighted = matches.length ? matches : choices.filter(choice => choice.hasAttribute('data-platform-default'));
    choices.forEach(choice => choice.classList.toggle('is-platform-match', highlighted.includes(choice)));
  });
})();
