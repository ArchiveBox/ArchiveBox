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
  await fill('#id_url_filters_denylist', '/(?:login|logout|submit|vote|hide|fave)(?:/|[?]|$)'); // codespell:ignore fave
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
  return {name: 'Domain snapshots', url, moreOptionsUrl, path: new URL(url).pathname, crawlId, source: 'archivebox/templates/admin/core/snapshot/change_list.html'};
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

// Exports stay on the server filesystem. Exercise the native inline control,
// then open its actual output directly: the static export needs no replay server.
async function exportViews(page, clone, directory, baseUrl) {
  const fs = require('fs');
  const path = require('path');
  if (!baseUrl) throw new Error('The static gallery requires its localhost export server.');
  fs.mkdirSync(directory, {recursive: true});
  await page.goto(new URL('/admin/domains/', clone.url).href, {waitUntil: 'domcontentloaded'});
  const destinationPrompt = new Promise(resolve => page.once('dialog', async dialog => {
    await dialog.accept(directory);
    resolve();
  }));
  await Promise.all([
    page.select('.site-domain-row-export[data-domain="*.ycombinator.com"]', 'html'),
    destinationPrompt,
  ]);
  await page.waitForFunction(() => ['exited', 'failed'].includes(document.querySelector('.snapshot-export-status')?.dataset.status), {timeout: 120000});
  const status = await page.$eval('.snapshot-export-status', element => ({...element.dataset}));
  if (new URL(page.url()).pathname !== '/admin/domains/') throw new Error('Export navigated away from Domains.');
  if (String(status.exitCode) !== '0') throw new Error('Static site export failed; inspect its process log.');
  const exported = status.exportPath;
  if (!path.isAbsolute(exported) || !fs.statSync(exported).isDirectory()) throw new Error('Export did not create its server directory.');
  if (!exported.startsWith(path.resolve(directory) + path.sep)) throw new Error('Export did not use the selected server directory.');
  const relative = path.relative(directory, exported);
  const root = new URL(`${relative.split(path.sep).map(encodeURIComponent).join('/')}/`, baseUrl);
  const index = new URL('index.html', root).href;
  const pages = JSON.parse(fs.readFileSync(path.join(exported, 'pages.json'), 'utf8'));
  const home = pages.find(item => item.url === 'https://news.ycombinator.com/');
  const next = pages.find(item => item.url === 'https://news.ycombinator.com/newest');
  if (!home || !next) throw new Error('The native export omitted captured Hacker News pages.');
  const homeUrl = new URL(home.path, root).href;
  const nextUrl = new URL(next.path, root).href;
  const snapshotId = home.path.split('/')[1];
  await page.goto(index, {waitUntil: 'domcontentloaded'});
  let snapshotLink;
  for (const link of await page.$$('a.snapshot-title')) {
    if (await link.evaluate((element, id) => new URL(element.href).pathname.endsWith(`/${id}/index.html`), snapshotId)) { snapshotLink = link; break; }
  }
  if (!snapshotLink) throw new Error('The native static index has no Hacker News detail link.');
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), snapshotLink.click()]);
  const detail = page.url();
  if (!detail.startsWith(root.href)) throw new Error('The native detail left the exported directory.');
  await page.click('.output-stack-html');
  let htmlCard;
  for (const card of await page.$$('.thumb-card[data-output-group="html"]')) {
    if (await card.evaluate((element, expected) => new URL(element.dataset.previewUrl, location.href).href === expected, homeUrl)) { htmlCard = card; break; }
  }
  if (!htmlCard) throw new Error('The native detail has no rewritten HTML output card.');
  const plugin = await htmlCard.evaluate(element => element.dataset.pluginName);
  // Click the native output link, not its download action or thumbnail iframe.
  await page.click(`.stack-tray .thumb-card[data-plugin-name="${plugin}"] h4`);
  const frame = await page.waitForFrame(frame => frame.name() === 'preview' && frame.url() === homeUrl);
  await frame.waitForSelector('#hnmain');
  let newest;
  for (const anchor of await frame.$$('a[href]')) {
    if (await anchor.evaluate(element => element.textContent.trim() === 'new')) { newest = anchor; break; }
  }
  if (!newest || await newest.evaluate(element => element.href) !== nextUrl) throw new Error('Static export did not rewrite the captured newest page.');
  await newest.click();
  const nextFrame = await page.waitForFrame(frame => frame.url() === nextUrl);
  await nextFrame.waitForFunction(() => document.title.includes('New Links') && Boolean(document.querySelector('#hnmain')));
  fs.writeFileSync(path.join(exported, 'gallery-navigation-proof.json'), JSON.stringify({index, detail, plugin, snapshotId, from: homeUrl, to: nextUrl}, null, 2) + '\n');
  return [
    {name: 'Static snapshot index', url: index, path: '/index.html', source: 'archivebox/core/querysets.py'},
    {name: 'Static snapshot detail', url: `${detail}#${plugin}`, path: new URL(detail).pathname, source: 'archivebox/templates/core/snapshot.html'},
    {name: 'Static site export', url: homeUrl, path: new URL(homeUrl).pathname, source: 'archivebox/domains/exports.py'},
    {name: 'Static export internal navigation', url: nextUrl, path: '/newest', source: 'archivebox/domains/exports.py'},
  ];
}

module.exports.exportViews = exportViews;
