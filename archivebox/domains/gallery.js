// Run against the real logged-in gallery browser. The caller runs the ordinary
// worker after this submission, then photographs the native snapshot list.
async function prepare(page, adminBaseUrl) {
  await page.goto(`${adminBaseUrl}/admin/domains/`, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('#siteclone-form');
  if (await page.$eval('#site-add-options', el => el.hidden)) await page.click('#site-add-button');
  async function fill(selector, text) {
    await page.focus(selector);
    await page.keyboard.press('End');
    await page.keyboard.down('Shift');
    await page.keyboard.press('Home');
    await page.keyboard.up('Shift');
    await page.keyboard.press('Backspace');
    await page.type(selector, text);
    if (await page.$eval(selector, input => input.value) !== text) {
      throw new Error(`Site clone field ${selector} was not entered correctly.`);
    }
  }
  await fill('#id_url', 'https://news.ycombinator.com/');
  await fill('#id_max_depth', '1');
  await fill('#id_max_urls', '5');
  await fill('#id_concurrency', '2');
  await fill('#id_timeout_minutes', '30');
  await page.click('#siteclone-form .url-filter-patterns > summary');
  await fill('#id_url_filters_denylist', '/(?:login|logout|submit|vote|hide|fave)(?:/|[?]|$)');
  for (const tag of ['hacker-news', 'site-clone', 'screenshot-gallery']) {
    await page.type('#id_tags_input', tag);
    await page.keyboard.press('Enter');
  }
  if (await page.$eval('#id_tags', input => input.value.split(',').sort().join(',')) !== 'hacker-news,screenshot-gallery,site-clone') {
    throw new Error('Native tag editor did not preserve the selected tags.');
  }
  // Existing captures must not turn this demonstration into an empty queue.
  if (await page.$eval('#id_url_filters_only_new', (input) => input.checked)) await page.click('#id_url_filters_only_new');
  const moreOptionsUrl = await page.$eval('#site-more-options', link => link.href);
  await Promise.all([
    page.waitForNavigation({waitUntil: 'domcontentloaded'}),
    page.click('#siteclone-form button[type="submit"]'),
  ]);
  const crawlId = new URL(page.url()).pathname.match(/^\/admin\/crawls\/crawl\/([a-f0-9-]{32,36})\/change\/$/)?.[1];
  if (!crawlId) {
    throw new Error(`Site-clone form did not save: ${await page.$eval('main', (main) => main.innerText)}`);
  }
  const url = `${adminBaseUrl}/admin/core/snapshot/?${new URLSearchParams({domain: '*.news.ycombinator.com'})}`;
  return {name: 'Domain snapshots', url, moreOptionsUrl, exportUrl: `${adminBaseUrl}/admin/domains/${crawlId}/export/`, path: new URL(url).pathname, crawlId, source: 'archivebox/templates/admin/core/snapshot/change_list.html'};
}

async function replayViews(page, clone) {
  await page.goto(new URL('/admin/domains/', clone.url).href, {waitUntil: 'domcontentloaded'});
  const authUrl = await page.$$eval('a[href*="original_domain="]', links => links.find(link => new URL(link.href).searchParams.get('original_domain') === 'news.ycombinator.com')?.href);
  if (!authUrl) throw new Error('The completed site crawl has no saved page to replay.');
  const response = await page.goto(authUrl, {waitUntil: 'domcontentloaded'});
  if (!response || response.status() !== 200 || !new URL(page.url()).hostname.startsWith('news.ycombinator.com.')) {
    throw new Error('Saved Hacker News did not load on its original-domain replay host.');
  }
  const next = await page.$$eval('a[href]', links => links.find(link => link.textContent.trim() === 'new')?.href);
  if (!next || new URL(next).origin !== new URL(page.url()).origin) throw new Error('The saved newest page is not available for internal replay.');
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click(`a[href="${next}"]`)]);
  if (page.url() !== next || !(await page.title()).includes('New Links')) throw new Error('Captured internal-link navigation failed.');
  const newestAuth = new URL(authUrl);
  newestAuth.searchParams.set('next', new URL(next).pathname + new URL(next).search);
  return [
    {name: 'Saved site replay', url: authUrl, path: '/', source: 'archivebox/core/views.py'},
    {name: 'Captured internal link replay', url: newestAuth.href, path: '/newest', source: 'archivebox/core/views.py'},
  ];
}

module.exports = {prepare, replayViews};

// Exports stay on the server filesystem. Exercise the same form as an operator,
// then open its actual output directly: the static export needs no replay server.
async function exportViews(page, clone, directory) {
  const fs = require('fs');
  const path = require('path');
  const {pathToFileURL, fileURLToPath} = require('url');
  fs.mkdirSync(directory, {recursive: true});
  await page.goto(new URL('/admin/domains/', clone.url).href, {waitUntil: 'domcontentloaded'});
  const destinationPrompt = new Promise(resolve => page.once('dialog', async dialog => {
    await dialog.accept(directory);
    resolve();
  }));
  await Promise.all([
    page.waitForNavigation({waitUntil: 'domcontentloaded'}),
    page.select('.site-domain-row-export[data-domain="*.ycombinator.com"]', 'html'),
    destinationPrompt,
  ]);
  await page.waitForFunction(() => document.querySelector('#site-export-status')?.dataset.status === 'exited', {timeout: 120000});
  const status = await page.$eval('#site-export-status', element => ({...element.dataset}));
  if (String(status.exitCode) !== '0') throw new Error('Static site export failed; inspect its process log.');
  const exported = await page.$eval('#site-export-path', element => element.textContent.trim());
  if (!path.isAbsolute(exported) || !fs.statSync(exported).isDirectory()) throw new Error('Export did not create its server directory.');
  if (!exported.startsWith(path.resolve(directory) + path.sep)) throw new Error('Export did not use the selected server directory.');
  const settingsUrl = page.url();
  const root = fs.realpathSync(exported) + path.sep;
  const index = pathToFileURL(path.join(exported, 'index.html')).href;
  await page.goto(index, {waitUntil: 'domcontentloaded'});
  await page.waitForFunction(() => location.pathname.includes('/pages/') && document.title.includes('Hacker News'));
  const first = page.url();
  if (!fs.realpathSync(fileURLToPath(first)).startsWith(root)) throw new Error('Static export left the output directory.');
  const next = await page.$$eval('a[href]', links => links.find(link => link.textContent.trim() === 'new')?.href);
  if (!next || !next.startsWith('file:') || !fs.realpathSync(fileURLToPath(next)).startsWith(root)) {
    throw new Error('Static export did not rewrite the captured newest page.');
  }
  const anchors = await page.$$('a[href]');
  let newest;
  for (const anchor of anchors) {
    if (await anchor.evaluate(element => element.textContent.trim() === 'new')) { newest = anchor; break; }
  }
  if (!newest) throw new Error('The exported newest link disappeared.');
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), newest.click()]);
  if (page.url() !== next || !(await page.title()).includes('New Links')) throw new Error('Static internal-link navigation failed.');
  return [
    {name: 'Site export settings', url: settingsUrl, path: new URL(settingsUrl).pathname, source: 'archivebox/domains/templates/domains/export.html'},
    {name: 'Static site export', url: first, path: '/index.html', source: 'archivebox/domains/exports.py'},
    {name: 'Static export internal navigation', url: next, path: '/newest', source: 'archivebox/domains/exports.py'},
  ];
}

module.exports.exportViews = exportViews;
