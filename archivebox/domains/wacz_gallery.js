// Use the real inline export controls, then browse unchanged recordings using the
// installed ReplayWeb.page player in a shared localhost gallery harness.
function matchesReplayUrl(frameUrl, playerUrl, originalUrl) {
  const replay = URL.parse(frameUrl);
  const prefix = new URL('replay/w/', playerUrl);
  if (!replay || replay.origin !== prefix.origin || !replay.pathname.startsWith(prefix.pathname)) return false;
  const embedded = replay.pathname.match(/\/(https?:\/\/.*)$/)?.[1];
  return Boolean(embedded) && URL.parse(embedded + replay.search + replay.hash)?.href === new URL(originalUrl).href;
}

async function downloadWacz(page, directory, trigger) {
  const fs = require('fs');
  const path = require('path');
  fs.mkdirSync(directory, {recursive: true});
  const downloadDirectory = fs.mkdtempSync(path.join(directory, 'wacz-download-'));
  const before = page.url();
  const cdp = await page.browser().target().createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', {behavior: 'allowAndName', downloadPath: downloadDirectory, eventsEnabled: true});
  let downloadUrl, downloadTimeout;
  const downloaded = new Promise((resolve, reject) => {
    downloadTimeout = setTimeout(() => reject(new Error('WACZ did not finish downloading.')), 120000);
    cdp.on('Browser.downloadWillBegin', event => { downloadUrl = event.url; });
    cdp.on('Browser.downloadProgress', event => {
      if (event.state === 'completed') { clearTimeout(downloadTimeout); resolve(path.join(downloadDirectory, event.guid)); }
      if (event.state === 'canceled') { clearTimeout(downloadTimeout); reject(new Error('WACZ download was canceled.')); }
    });
  });
  let file;
  try {
    [file] = await Promise.all([
      downloaded,
      (async () => {
        await trigger();
        await page.waitForFunction(() => ['exited', 'failed'].includes(document.querySelector('.snapshot-export-status')?.dataset.status), {timeout: 120000});
        const status = await page.$eval('.snapshot-export-status', element => ({...element.dataset}));
        if (status.exitCode !== '0') throw new Error('WACZ export failed; inspect its native Process log.');
        if (page.url() !== before) throw new Error('WACZ export navigated away from the selected view.');
      })(),
    ]);
  } finally {
    clearTimeout(downloadTimeout);
    await cdp.detach();
  }
  const expectedDownload = await page.$eval('[data-export-download]', link => link.href);
  if (downloadUrl !== expectedDownload || !fs.statSync(file).size) throw new Error('The browser did not download the selected WACZ.');
  return {file, downloadUrl};
}

async function replayHarness(page, exportedWacz, directory, baseUrl, adminUrl, originalUrl) {
  const fs = require('fs');
  const path = require('path');
  if (!baseUrl) throw new Error('The WACZ gallery requires its localhost static server.');
  const playerDirectory = fs.mkdtempSync(path.join(directory, 'wacz-player-'));
  fs.mkdirSync(path.join(playerDirectory, 'replay'));
  await page.goto(new URL('/admin/domains/', adminUrl).href, {waitUntil: 'domcontentloaded'});
  const authUrl = await page.$$eval('a[href*="original_domain="]', (links, original) => links.find(link => new URL(link.href).searchParams.get('original_domain') === new URL(original).hostname)?.href, originalUrl);
  if (!authUrl) throw new Error('The captured site has no native replay authorization link.');
  // Reuse the installed plugin's real assets through its existing isolated
  // snapshot route. This harness is gallery infrastructure, not an export mode.
  const auth = new URL(authUrl);
  auth.searchParams.delete('original_domain');
  auth.searchParams.set('next', '/replay/ui.js');
  const first = await page.goto(auth.href, {waitUntil: 'domcontentloaded'});
  if (!first || first.status() !== 200 || !new URL(first.url()).pathname.endsWith('/replay/ui.js')) throw new Error('Installed ReplayWeb.page assets are unavailable.');
  fs.writeFileSync(path.join(playerDirectory, 'replay/ui.js'), await first.buffer());
  for (const name of ['sw.js', 'sw-index.js', 'replay.html']) {
    const response = await page.goto(new URL(name, first.url()).href, {waitUntil: 'domcontentloaded'});
    if (!response || response.status() !== 200) throw new Error(`Installed ReplayWeb.page asset is unavailable: ${name}`);
    fs.writeFileSync(path.join(playerDirectory, 'replay', name), await response.buffer());
  }
  fs.copyFileSync(exportedWacz, path.join(playerDirectory, 'site.wacz'));
  const escape = value => value.replace(/[&<>"']/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[character]));
  fs.writeFileSync(path.join(playerDirectory, 'index.html'),
    '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">' +
    '<title>ReplayWeb.page</title><script src="replay/ui.js"></script>' +
    '<style>html,body{margin:0;height:100%}replay-web-page{display:block;height:100%}</style></head><body>' +
    `<replay-web-page source="./site.wacz" replaybase="./replay/" embed="default" deepLink url="${escape(originalUrl)}"></replay-web-page></body></html>`);
  const relative = path.relative(directory, playerDirectory);
  return {directory: playerDirectory, url: new URL(`${relative.split(path.sep).map(encodeURIComponent).join('/')}/index.html`, baseUrl).href};
}

async function exportPlayer(page, siteUrl, directory, baseUrl, originalUrl = 'https://news.ycombinator.com/') {
  const domainsUrl = new URL('/admin/domains/', siteUrl).href;
  await page.goto(domainsUrl, {waitUntil: 'domcontentloaded'});
  if (page.url() !== domainsUrl) throw new Error('Domains redirected away from the gallery server.');
  const domain = await page.$$eval('.site-domain-row-export', (selects, original) => {
    const hostname = new URL(original).hostname;
    return selects.find(select => {
      const domain = select.dataset.domain.replace(/^\*\./, '');
      return hostname === domain || hostname.endsWith('.' + domain);
    })?.dataset.domain;
  }, originalUrl);
  if (!domain) throw new Error('The captured site is missing from Domains.');
  const {file} = await downloadWacz(page, directory, () => page.select(`.site-domain-row-export[data-domain="${domain}"]`, 'wacz'));
  return replayHarness(page, file, directory, baseUrl, siteUrl, originalUrl);
}

async function exportViews(page, clone, directory, baseUrl) {
  const {url} = await exportPlayer(page, clone.url, directory, baseUrl);
  await page.goto(url, {waitUntil: 'domcontentloaded'});
  const frame = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, 'https://news.ycombinator.com/'), {timeout: 45000});
  await frame.waitForSelector('#hnmain', {timeout: 45000});
  let newest;
  for (const anchor of await frame.$$('a[href]')) {
    if (await anchor.evaluate(element => element.textContent.trim() === 'new')) { newest = anchor; break; }
  }
  if (!newest) throw new Error('The WACZ recording has no native newest link.');
  await newest.click();
  const next = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, 'https://news.ycombinator.com/newest'), {timeout: 45000});
  await next.waitForFunction(() => document.title.includes('New Links') && Boolean(document.querySelector('#hnmain')));
  await page.waitForFunction(() => new URLSearchParams(location.hash.slice(1)).get('url') === 'https://news.ycombinator.com/newest');
  return [
    {name: 'WACZ site export', url, path: new URL(url).pathname, source: 'archivebox/domains/wacz.py', mode: 'wait-replay-url:https://news.ycombinator.com/'},
    {name: 'WACZ export internal navigation', url: page.url(), path: new URL(url).pathname, source: 'archivebox/domains/exports.py', mode: 'wait-replay-url:https://news.ycombinator.com/newest'},
  ];
}

async function storyView(page, adminBaseUrl, storyUrl, directory, baseUrl) {
  const {url} = await exportPlayer(page, adminBaseUrl, directory, baseUrl, storyUrl);
  const story = `${url}#${new URLSearchParams({url: storyUrl})}`;
  await page.goto(story, {waitUntil: 'domcontentloaded'});
  const frame = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, storyUrl), {timeout: 45000});
  await frame.waitForFunction(() => document.readyState === 'complete' && (document.body?.innerText.length || 0) > 80, {timeout: 45000});
  if (await frame.evaluate(() => document.body.innerText.includes('Archived Page Not Found'))) throw new Error('The captured news story is missing from the WACZ export.');
  return {name: 'WACZ archived news story', url: story, path: new URL(url).pathname, source: 'archivebox/domains/exports.py', mode: `wait-replay-url:${storyUrl}`};
}

async function folderViews(page, libraryUrl, stories, directory, baseUrl) {
  const fs = require('fs');
  const path = require('path');
  const {createHash} = require('crypto');
  const digest = async file => {
    const hash = createHash('sha256');
    for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
    return hash.digest('hex');
  };
  await page.goto(libraryUrl, {waitUntil: 'domcontentloaded'});
  if (page.url() !== libraryUrl) throw new Error('Folder redirected away from the selected gallery view.');
  await require('../core/library_gallery.js').openFolderMenu(page);
  const link = '.folder-row:has(.folder-link[aria-current="page"]) .folder-menu [data-export-format="wacz"]';
  const exportUrl = await page.$eval(link, link => link.href);
  if (new URL(exportUrl).searchParams.get('folder') !== new URL(libraryUrl).searchParams.get('folder')) {
    throw new Error('The WACZ export lost the selected folder.');
  }
  const {file: exportedWacz, downloadUrl} = await downloadWacz(page, directory, () => page.click(link));
  const sourceDigest = await digest(exportedWacz);
  const {url, directory: playerDirectory} = await replayHarness(page, exportedWacz, directory, baseUrl, libraryUrl, 'https://news.ycombinator.com/');
  const playerWacz = path.join(playerDirectory, 'site.wacz');
  if (await digest(playerWacz) !== sourceDigest) throw new Error('The player must use the exact standalone folder WACZ bytes.');

  const homepage = `${url}#${new URLSearchParams({url: 'https://news.ycombinator.com/'})}`;
  await page.goto(homepage, {waitUntil: 'domcontentloaded'});
  const frame = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, 'https://news.ycombinator.com/'), {timeout: 45000});
  await frame.waitForSelector('#hnmain', {timeout: 45000});
  let storyLink, storyUrl;
  for (const anchor of await frame.$$('a[href]')) {
    const href = await anchor.evaluate(element => element.href);
    const story = stories.find(candidate => new URL(candidate).href === href && new URL(candidate).hostname !== 'news.ycombinator.com');
    if (story) { storyLink = anchor; storyUrl = story; break; }
  }
  if (!storyLink) throw new Error('The folder WACZ has no Hacker News link to an actually captured story.');
  await storyLink.click();
  const next = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, storyUrl), {timeout: 45000});
  await next.waitForFunction(() => document.readyState === 'complete' && (document.body?.innerText.length || 0) > 80, {timeout: 45000});
  const text = await next.evaluate(() => document.body.innerText);
  if (text.includes('Archived Page Not Found')) throw new Error('The linked story is missing from the selected folder WACZ.');
  await page.waitForFunction(story => new URLSearchParams(location.hash.slice(1)).get('url') === story, {}, storyUrl);
  if (await digest(exportedWacz) !== sourceDigest || await digest(playerWacz) !== sourceDigest) {
    throw new Error('Browsing changed the exported folder WACZ bytes.');
  }
  fs.writeFileSync(path.join(playerDirectory, 'folder-wacz-proof.json'), JSON.stringify({
    selection: libraryUrl, exportUrl, downloadUrl, source: exportedWacz, player: playerWacz,
    sha256: sourceDigest, bytes: fs.statSync(exportedWacz).size,
    from: 'https://news.ycombinator.com/', to: storyUrl, frame: next.url(),
  }, null, 2) + '\n');
  return [
    {name: 'Export notification', url: libraryUrl, path: new URL(libraryUrl).pathname, source: 'archivebox/templates/static/exports.js', mode: 'export-notification'},
    {name: 'Folder WACZ Hacker News', url: homepage, path: new URL(url).pathname, source: 'archivebox/domains/wacz.py', mode: 'wait-replay-url:https://news.ycombinator.com/'},
    {name: 'Folder WACZ story navigation', url: page.url(), path: new URL(url).pathname, source: 'archivebox/domains/wacz.py', mode: `wait-replay-url:${storyUrl}`},
  ];
}

module.exports = {exportViews, storyView, folderViews};
