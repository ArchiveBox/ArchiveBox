// Publish only the real news captures in the isolated gallery collection.
async function prepare(page, publicBaseUrl, libraryUrl) {
  if (!publicBaseUrl) throw new Error('The gallery requires its configured public URL.');
  await page.goto(libraryUrl, {waitUntil: 'domcontentloaded'});
  await page.click('#action-toggle');
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.select('.action-permissions-select', 'public')]);
  if (!(await page.$eval('.messagelist', node => node.textContent)).includes('Set permissions to public')) throw new Error('Publishing the gallery captures failed.');
  const url = new URL('/public/', publicBaseUrl);
  url.searchParams.set('folder', new URL(libraryUrl).searchParams.get('folder'));
  const context = await page.browser().createBrowserContext();
  try {
    const visitor = await context.newPage();
    const response = await visitor.goto(url.href, {waitUntil: 'domcontentloaded'});
    if (response.status() !== 200 || !await visitor.$('.folder-link[aria-current="page"]') || !await visitor.$('#table-bookmarks tbody .snapshot-title')) throw new Error('Public folders did not render real captured pages.');
    if (await visitor.$('.folder-new,.folder-edit,.folder-drop-target,#folder-dialog')) throw new Error('Public folders exposed editing controls.');
  } finally {
    await context.close();
  }
  return {name: 'Public snapshot folders', url: url.href, path: '/public/', source: 'archivebox/templates/core/folder_sidebar.html', mode: 'public'};
}
module.exports = {prepare};
