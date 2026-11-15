// Run against the real logged-in gallery browser. The caller runs the ordinary
// worker after this submission, then photographs the native snapshot list.
async function prepare(page, adminBaseUrl, homeUrl) {
  const nextUrl = new URL('chapter.html', homeUrl).href;
  const domain = new URL(homeUrl).hostname;
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
  await fill('#id_url', homeUrl);
  await fill('#id_max_depth', '1');
  await fill('#id_max_urls', '2');
  await fill('#id_concurrency', '2');
  await fill('#id_timeout_minutes', '30');
  await page.click('#siteclone-form .url-filter-patterns > summary');
  const escapeRegex = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  await fill('#id_url_filters_allowlist', `^(?:${[homeUrl, nextUrl].map(escapeRegex).join('|')})$`);
  for (const tag of ['replay-contract', 'site-clone', 'screenshot-gallery']) {
    await page.type('#id_tags_input', tag);
    await page.keyboard.press('Enter');
  }
  if (await page.$eval('#id_tags', input => input.value.split(',').sort().join(',')) !== 'replay-contract,screenshot-gallery,site-clone') {
    throw new Error('Native tag editor did not preserve the selected tags.');
  }
  // A backlink must not capture the same page twice.
  if (!await page.$eval('#id_url_filters_only_new', (input) => input.checked)) await page.click('#id_url_filters_only_new');
  const moreOptionsUrl = await page.$eval('#site-more-options', link => link.href);
  await Promise.all([
    page.waitForNavigation({waitUntil: 'domcontentloaded'}),
    page.click('#siteclone-form button[type="submit"]'),
  ]);
  const crawlId = new URL(page.url()).pathname.match(/^\/admin\/crawls\/crawl\/([a-f0-9-]{32,36})\/change\/$/)?.[1];
  if (!crawlId) {
    throw new Error(`Site-clone form did not save: ${await page.$eval('main', (main) => main.innerText)}`);
  }
  const url = `${adminBaseUrl}/admin/core/snapshot/?${new URLSearchParams({domain})}`;
  return {name: 'Domain snapshots', homeUrl, nextUrl, domain, url, moreOptionsUrl, path: new URL(url).pathname, crawlId, source: 'archivebox/templates/admin/core/snapshot/change_list.html'};
}

async function replayViews(page, clone) {
  await page.goto(new URL('/admin/domains/', clone.url).href, {waitUntil: 'domcontentloaded'});
  const authUrl = await page.$$eval('a[href*="original_domain="]', (links, domain) => links.find(link => new URL(link.href).searchParams.get('original_domain') === domain)?.href, new URL(clone.homeUrl).hostname);
  if (!authUrl) throw new Error('The completed site crawl has no saved page to replay.');
  const homeAuth = new URL(authUrl);
  homeAuth.searchParams.set('next', new URL(clone.homeUrl).pathname);
  const response = await page.goto(homeAuth.href, {waitUntil: 'domcontentloaded'});
  if (!response || response.status() !== 200 || !new URL(page.url()).hostname.startsWith(new URL(clone.homeUrl).hostname + '.')) {
    throw new Error('Saved site did not load on its original-domain replay host.');
  }
  await assertCapturedPage(page, 'Field Notes');
  const next = await page.$eval('#chapter-link', link => link.href);
  if (!next || new URL(next).origin !== new URL(page.url()).origin) {
    const current = new URL(page.url());
    const link = next ? new URL(next) : null;
    throw new Error(`The saved chapter is not available for internal replay: ${JSON.stringify({
      page: current.origin + current.pathname,
      title: (await page.title()).slice(0, 160),
      next: link ? link.origin + link.pathname : null,
    })}`);
  }
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click(`a[href="${next}"]`)]);
  if (page.url() !== next) throw new Error('Captured internal-link navigation failed.');
  await assertCapturedPage(page, 'A Walk by the River');
  await page.goBack({waitUntil: 'domcontentloaded'});
  await assertCapturedPage(page, 'Field Notes');
  await page.goForward({waitUntil: 'domcontentloaded'});
  await assertCapturedPage(page, 'A Walk by the River');
  const nextAuth = new URL(authUrl);
  nextAuth.searchParams.set('next', new URL(next).pathname + new URL(next).search);
  return [
    {name: 'Saved site replay', url: homeAuth.href, path: new URL(clone.homeUrl).pathname, source: 'archivebox/core/views.py'},
    {name: 'Captured internal link replay', url: nextAuth.href, path: new URL(clone.nextUrl).pathname, source: 'archivebox/core/views.py'},
  ];
}

// Assert captured text and subresources, not merely the replay frame's URL.
async function assertCapturedPage(frame, title) {
  await frame.waitForFunction(expected => {
    const image = document.querySelector('#notebook');
    return document.title === expected && document.querySelector('h1')?.textContent === expected &&
      document.querySelector('#description')?.textContent === (expected === 'Field Notes'
        ? 'Keep the pages, pictures, and paths that connect them.'
        : 'Willow branches leaned over the water as the afternoon light faded.') &&
      image?.complete && image.naturalWidth === 96 &&
      getComputedStyle(document.querySelector('#field-notes')).borderTopColor === 'rgb(47, 111, 78)';
  }, {}, title);
}

module.exports = {prepare, replayViews, assertCapturedPage};

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
    page.select(`.site-domain-row-export[data-domain="${clone.domain}"]`, 'html'),
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
  const home = pages.find(item => item.url === clone.homeUrl);
  const next = pages.find(item => item.url === clone.nextUrl);
  if (!home || !next) throw new Error('The native export omitted captured site pages.');
  const homeUrl = new URL(home.path, root).href;
  const nextUrl = new URL(next.path, root).href;
  const snapshotId = home.path.split('/')[1];
  await page.goto(index, {waitUntil: 'domcontentloaded'});
  let snapshotLink;
  for (const link of await page.$$('a.snapshot-title')) {
    if (await link.evaluate((element, id) => new URL(element.href).pathname.endsWith(`/${id}/index.html`), snapshotId)) { snapshotLink = link; break; }
  }
  if (!snapshotLink) throw new Error('The native static index has no captured site detail link.');
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
  await assertCapturedPage(frame, 'Field Notes');
  const chapterLink = await frame.$('#chapter-link');
  if (!chapterLink || await chapterLink.evaluate(element => element.href) !== nextUrl) throw new Error('Static export did not rewrite the captured chapter link.');
  await chapterLink.click();
  const nextFrame = await page.waitForFrame(frame => frame.url() === nextUrl);
  await assertCapturedPage(nextFrame, 'A Walk by the River');
  await page.evaluate(() => history.back());
  await assertCapturedPage(await page.waitForFrame(frame => frame.url() === homeUrl), 'Field Notes');
  await page.evaluate(() => history.forward());
  await assertCapturedPage(await page.waitForFrame(frame => frame.url() === nextUrl), 'A Walk by the River');
  fs.writeFileSync(path.join(exported, 'gallery-navigation-proof.json'), JSON.stringify({index, detail, plugin, snapshotId, from: homeUrl, to: nextUrl}, null, 2) + '\n');
  return [
    {name: 'Static snapshot index', url: index, path: new URL(index).pathname, source: 'archivebox/core/querysets.py'},
    {name: 'Static snapshot detail', url: `${detail}#${plugin}`, path: new URL(detail).pathname, source: 'archivebox/templates/core/snapshot.html'},
    {name: 'Static site export', url: homeUrl, path: new URL(homeUrl).pathname, source: 'archivebox/domains/exports.py'},
    {name: 'Static export internal navigation', url: nextUrl, path: new URL(nextUrl).pathname, source: 'archivebox/domains/exports.py'},
  ];
}

module.exports.exportViews = exportViews;
