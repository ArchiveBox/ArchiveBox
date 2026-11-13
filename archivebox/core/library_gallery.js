// Exercise the ordinary Django folder forms and bulk actions on real captures.
async function submit(page, selector) {
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click(selector)]);
  const errors = await page.$$eval('.errornote,.errorlist', nodes => nodes.map(node => node.textContent.trim()).join(' '));
  if (errors) throw new Error(errors);
}

async function prepare(page, adminBaseUrl, crawlId) {
  if (!crawlId) throw new Error('A real captured crawl is required for the folder gallery.');
  async function folder(name, parent = '') {
    await page.goto(`${adminBaseUrl}/admin/core/snapshot/`, {waitUntil: 'domcontentloaded'});
    if (await page.$('.folder-sidebar-reopen:not([hidden])')) await page.click('.folder-sidebar-reopen');
    const existing = await page.$$eval('.folder-row', (rows, name) => rows.find(row => row.querySelector('.folder-link span').textContent === name)?.dataset.folderId, name);
    if (existing) return existing;
    if (parent) {
      const row = `.folder-row[data-folder-id="${parent}"]`;
      await page.hover(row);
      await page.click(`${row} .folder-new`);
    } else {
      await page.goto(`${adminBaseUrl}/add/?url=https%3A%2F%2Fnews.ycombinator.com%2F`, {waitUntil: 'domcontentloaded'});
      await page.click('.folder-field .folder-new');
    }
    await page.type('#folder-name', name);
    if (await page.$eval('#folder-parent', select => select.value) !== parent) throw new Error('New folder dialog lost the selected parent.');
    const saved = page.waitForResponse(response => response.url().endsWith('/admin/core/folder/save/') && response.request().method() === 'POST');
    if (parent) await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click('.folder-save')]);
    else await page.click('.folder-save');
    const response = await saved;
    if (!response.ok()) throw new Error(`Creating the gallery folder failed: HTTP ${response.status()}`);
    if (!parent) {
      const created = await response.json();
      await page.waitForSelector('#folder-dialog:not([open])');
      if (await page.$eval('#id_folder', select => select.value) !== String(created.id) || await page.$eval('#id_url', input => input.value) !== 'https://news.ycombinator.com/') throw new Error('Creating a folder lost the Add form state.');
    }
    await page.goto(`${adminBaseUrl}/admin/core/snapshot/`, {waitUntil: 'domcontentloaded'});
    const id = await page.$$eval('.folder-row', (rows, name) => rows.find(row => row.querySelector('.folder-link span').textContent === name)?.dataset.folderId, name);
    if (!id) throw new Error(`Folder was not saved: ${name}`);
    return id;
  }
  const parent = await folder('Hacker News');
  const child = await folder('Recent top stories', parent);
  await page.goto(`${adminBaseUrl}/admin/core/snapshot/?crawl_id=${encodeURIComponent(crawlId)}`, {waitUntil: 'domcontentloaded'});
  const rows = await page.$$('#result_list tbody tr');
  if (!rows.length) throw new Error('No real captures in the gallery crawl.');
  await page.click('#action-toggle');
  const source = await page.$('#result_list tbody tr .field-title_str');
  const target = await page.$(`.folder-row[data-folder-id="${child}"]`);
  const from = await source.boundingBox();
  const to = await target.boundingBox();
  if (!from || !to) throw new Error('The real drag source or destination is not visible.');
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, {steps: 15});
  // Chrome emits dragover on a subsequent move after dragenter.
  await page.mouse.move(to.x + to.width / 2 + 1, to.y + to.height / 2);
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.mouse.up()]);
  const message = await page.$eval('.messagelist', node => node.textContent);
  if (!message.includes(`Moved ${rows.length} snapshot(s)`)) throw new Error('Dragging the checked captures did not save their folder.');
  const result = {name: 'Nested snapshot folders', url: `${adminBaseUrl}/admin/core/snapshot/?folder=${parent}`, path: `/admin/core/snapshot/?folder=${parent}`, source: 'archivebox/core/admin_snapshots.py', addUrl: `${adminBaseUrl}/add/?${new URLSearchParams({folder: child, url: 'https://news.ycombinator.com/'})}`};
  await page.goto(result.url, {waitUntil: 'domcontentloaded'});
  if (!await page.$('.folder-sidebar a.library-link[href="/admin/domains/"]')) throw new Error('Folder sidebar has no Domains link.');
  if (!await page.$('.folder-sidebar a[aria-current="page"]')) throw new Error('Saved folder filter is not selected.');
  if (await page.$('.library-context,.library-breadcrumbs')) throw new Error('The removed folder header is still present.');
  if (!await page.$('#toolbar .folder-sidebar-reopen')) throw new Error('The folder restore control is outside the snapshot toolbar.');
  await page.click('.folder-mobile-toggle');
  await page.waitForSelector('.snapshot-library.sidebar-hidden');
  if (!await page.$eval('.folder-sidebar-reopen', button => !button.hidden && button.getAttribute('aria-expanded') === 'false' && document.activeElement === button)) throw new Error('Hidden desktop folders have no focused reopen control.');
  await page.reload({waitUntil: 'domcontentloaded'});
  await page.waitForSelector('.snapshot-library.sidebar-hidden');
  await page.goto(`${adminBaseUrl}/admin/core/snapshot/grid/?folder=${parent}`, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('.snapshot-library.sidebar-hidden');
  await page.click('.folder-sidebar-reopen');
  await page.waitForSelector('.snapshot-library:not(.sidebar-hidden)');
  if (!await page.$eval('.folder-mobile-toggle', button => button.getAttribute('aria-expanded') === 'true' && document.activeElement === button)) throw new Error('Restoring desktop folders lost keyboard focus.');
  await page.goto(result.url, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('.snapshot-library:not(.sidebar-hidden)');
  // Keep the real-capture gallery checking the flush sidebar at responsive sizes.
  const viewport = page.viewport();
  for (const [width, height] of [[1440, 1000], [1024, 768], [768, 1024], [390, 844], [320, 640]]) {
    await page.setViewport({width, height});
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    if (width < 768) {
      if (await page.$eval('.folder-current', node => node.textContent.trim()) !== 'Hacker News') throw new Error('The mobile folder bar lost the selected folder.');
      await page.click('.folder-mobile-toggle');
    }
    const layout = await page.evaluate(() => {
      const sidebar = document.querySelector('.folder-sidebar').getBoundingClientRect();
      const table = document.querySelector('#result_list').getBoundingClientRect();
      return {left: sidebar.left, bottom: sidebar.bottom, gap: table.left - sidebar.right, overflow: document.documentElement.scrollWidth > innerWidth};
    });
    if (layout.overflow || Math.abs(layout.left) > 1 || (width >= 768 && (Math.abs(layout.gap) > 1 || Math.abs(layout.bottom - height) > 1))) {
      throw new Error(`Folder layout at ${width}x${height}: ${JSON.stringify(layout)}`);
    }
    if (width < 768) await page.click('.folder-mobile-toggle');
  }
  await page.setViewport(viewport);
  await page.goto(result.addUrl, {waitUntil: 'domcontentloaded'});
  if (await page.$eval('#id_folder', select => select.value) !== child) throw new Error('The Add gallery did not select the nested folder.');
  await page.goto(result.url, {waitUntil: 'domcontentloaded'});
  return result;
}

module.exports = {prepare};

async function openFolderMenu(page) {
  if (await page.$('.folder-sidebar.is-collapsed')) await page.click('.folder-mobile-toggle');
  if (await page.$('.snapshot-library.sidebar-hidden')) await page.click('.folder-sidebar-reopen');
  const row = '.folder-row:has(.folder-link[aria-current="page"])';
  await page.waitForSelector(row);
  await page.hover(row);
  if (await page.$eval(`${row} .folder-menu-toggle`, node => node.getAttribute('aria-expanded')) !== 'true') await page.click(`${row} .folder-menu-toggle`);
  await page.waitForSelector(`${row} .folder-menu:popover-open`);
  const menu = await page.$eval(`${row} .folder-menu`, node => {
    const box = node.getBoundingClientRect();
    return {left:box.left,right:box.right,top:box.top,bottom:box.bottom,width:innerWidth,height:innerHeight,formats:[...node.querySelectorAll('[data-export-format]')].map(link=>link.dataset.exportFormat)};
  });
  if (menu.left < 0 || menu.top < 0 || menu.right > menu.width || menu.bottom > menu.height) throw new Error('Folder menu extends beyond the viewport.');
  const expected = await page.$$eval('.folder-actions [data-export-format]', links => links.map(link => link.dataset.exportFormat));
  if (expected.some(format => !menu.formats.includes(format))) throw new Error('Folder menu omitted a supported export format.');
}
module.exports.openFolderMenu = openFolderMenu;

async function openImportMenu(page) {
  if (await page.$('.folder-sidebar.is-collapsed')) await page.click('.folder-mobile-toggle');
  if (await page.$('.snapshot-library.sidebar-hidden')) await page.click('.folder-sidebar-reopen');
  await page.click('.library-import-toggle');
  await page.waitForSelector('#library-import-menu:popover-open');
  const menu = await page.$eval('#library-import-menu', node => {
    const box = node.getBoundingClientRect();
    return {left:box.left,right:box.right,top:box.top,bottom:box.bottom,width:innerWidth,height:innerHeight,links:[...node.querySelectorAll('a')].map(link=>({text:link.textContent,href:link.getAttribute('href')}))};
  });
  if (menu.left < 0 || menu.top < 0 || menu.right > menu.width || menu.bottom > menu.height) throw new Error('Import menu extends beyond the viewport.');
  const expected = ['From Browser History / Bookmarks', 'From RSS or Social Media'];
  if (await page.$('.library-primary a[href="/admin/domains/"]')) expected.push('Clone an entire site');
  expected.push('Watch a site for changes', 'Other options...');
  if (JSON.stringify(menu.links.map(link => link.text)) !== JSON.stringify(expected)) throw new Error('Import menu is missing a source.');
}
module.exports.openImportMenu = openImportMenu;
