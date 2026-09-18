(() => {
  const tablist = document.querySelector('.install-tabs');
  const tabs = Array.from(tablist.querySelectorAll('.install-tab'));
  const panels = tabs.map(tab => document.querySelector(tab.getAttribute('href')));

  function selectTab(index) {
    tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      panels[i].hidden = i !== index;
    });
  }

  tablist.setAttribute('role', 'tablist');
  tabs.forEach((tab, index) => {
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', panels[index].id);
    panels[index].setAttribute('role', 'tabpanel');
    panels[index].tabIndex = 0;
    tab.addEventListener('click', event => {
      event.preventDefault();
      selectTab(index);
    });
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else if (event.key === ' ') next = index;
      else return;
      event.preventDefault();
      selectTab(next);
      tabs[next].focus();
    });
  });

  function selectHash() {
    const index = panels.findIndex(panel => `#${panel.id}` === location.hash);
    if (index !== -1) selectTab(index);
  }

  selectTab(0);
  selectHash();
  window.addEventListener('hashchange', selectHash);
})();
