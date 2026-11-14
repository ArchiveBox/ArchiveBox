// Publish only the real news captures in the isolated gallery collection.
async function prepare(page, publicBaseUrl, libraryUrl) {
  if (!publicBaseUrl) throw new Error('The gallery requires its configured public URL.');
  await page.goto(libraryUrl, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('#result_list input.action-select');
  const snapshotIds = await page.$$eval('#result_list input.action-select', nodes => nodes.map(node => node.value.replaceAll('-', '')).sort());
  await page.click('#action-toggle');
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.select('.action-permissions-select', 'public')]);
  const message = await page.$eval('.messagelist', node => node.textContent);
  if (!message.includes('Set permissions to public')) throw new Error(`Publishing the gallery captures failed: ${message}`);
  const url = new URL('/public/', publicBaseUrl);
  url.search = new URL(libraryUrl).search;
  const context = await page.browser().createBrowserContext();
  try {
    const visitor = await context.newPage();
    const response = await visitor.goto(url.href, {waitUntil: 'domcontentloaded'});
    if (response.status() !== 200 || !await visitor.$('.folder-link[aria-current="page"]')) throw new Error('Public folders did not render real captured pages.');
    await visitor.waitForFunction(expected => {
      const ids = [...document.querySelectorAll('#table-bookmarks tbody .snapshot-title')].map(link => new URL(link.href).pathname.match(/\/([a-f0-9]{32})\/?$/)?.[1]).sort();
      return JSON.stringify(ids) === JSON.stringify(expected);
    }, {}, snapshotIds);
    if (await visitor.$('.folder-new,.folder-edit,.folder-drop-target,#folder-dialog')) throw new Error('Public folders exposed editing controls.');
  } finally {
    await context.close();
  }
  return {name: 'Public snapshot folders', url: url.href, path: '/public/', source: 'archivebox/templates/core/folder_sidebar.html', mode: 'public'};
}
module.exports = {prepare};
