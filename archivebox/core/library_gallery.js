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
    const existing = await page.$$eval('.folder-row', (rows, name) => rows.find(row => row.querySelector('.folder-link span').textContent === name)?.dataset.folderId, name);
    if (existing) return existing;
    await page.click('.folder-new');
    await page.type('#folder-name', name);
    if (parent) await page.select('#folder-parent', parent);
    await submit(page, '.folder-save');
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
  const result = {name: 'Nested snapshot folders', url: `${adminBaseUrl}/admin/core/snapshot/?folder=${parent}`, path: `/admin/core/snapshot/?folder=${parent}`, source: 'archivebox/core/admin_snapshots.py'};
  await page.goto(result.url, {waitUntil: 'domcontentloaded'});
  if (!await page.$('.folder-sidebar a[aria-current="page"]')) throw new Error('Saved folder filter is not selected.');
  return result;
}

module.exports = {prepare};
