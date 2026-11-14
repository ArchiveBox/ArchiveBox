// Use the real inline export controls, then browse unchanged recordings using the
// exported ReplayWeb.page player on an ordinary localhost static file server.
function matchesReplayUrl(frameUrl, playerUrl, originalUrl) {
  const replay = URL.parse(frameUrl);
  const prefix = new URL('replay/w/', playerUrl);
  if (!replay || replay.origin !== prefix.origin || !replay.pathname.startsWith(prefix.pathname)) return false;
  const embedded = replay.pathname.match(/\/(https?:\/\/.*)$/)?.[1];
  return Boolean(embedded) && URL.parse(embedded + replay.search + replay.hash)?.href === new URL(originalUrl).href;
}

async function exportPlayer(page, siteUrl, directory, baseUrl, originalUrl = 'https://news.ycombinator.com/') {
  const fs = require('fs');
  const path = require('path');
  if (!baseUrl) throw new Error('The WACZ gallery requires its localhost export server.');
  fs.mkdirSync(directory, {recursive: true});
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
  const before = page.url();
  const destinationPrompt = new Promise(resolve => page.once('dialog', async dialog => {
    await dialog.accept(directory);
    resolve();
  }));
  await Promise.all([
    page.select(`.site-domain-row-export[data-domain="${domain}"]`, 'replay'),
    destinationPrompt,
  ]);
  await page.waitForFunction(() => ['exited', 'failed'].includes(document.querySelector('.snapshot-export-status')?.dataset.status), {timeout: 120000});
  const status = await page.$eval('.snapshot-export-status', element => ({...element.dataset}));
  if (page.url() !== before) throw new Error('Replay export navigated away from Domains.');
  if (status.exitCode !== '0') throw new Error('WACZ export failed; inspect its native Process log.');
  const exported = status.exportPath;
  const relative = path.relative(directory, exported);
  if (relative.startsWith('..') || path.isAbsolute(relative) || !fs.statSync(path.join(exported, 'site.wacz')).size) {
    throw new Error('WACZ export did not write its server-side archive.');
  }
  return {
    directory: exported,
    url: new URL(`${relative.split(path.sep).map(encodeURIComponent).join('/')}/index.html`, baseUrl).href,
  };
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
  fs.mkdirSync(directory, {recursive: true});
  const downloadDirectory = fs.mkdtempSync(path.join(directory, 'folder-download-'));
  const cdp = await page.browser().target().createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', {behavior: 'allowAndName', downloadPath: downloadDirectory, eventsEnabled: true});
  let downloadUrl, downloadTimeout;
  const downloaded = new Promise((resolve, reject) => {
    downloadTimeout = setTimeout(() => reject(new Error('Folder WACZ did not finish downloading.')), 120000);
    cdp.on('Browser.downloadWillBegin', event => { downloadUrl = event.url; });
    cdp.on('Browser.downloadProgress', event => {
      if (event.state === 'completed') { clearTimeout(downloadTimeout); resolve(path.join(downloadDirectory, event.guid)); }
      if (event.state === 'canceled') { clearTimeout(downloadTimeout); reject(new Error('Folder WACZ download was canceled.')); }
    });
  });
  let exportedWacz;
  try {
    [exportedWacz] = await Promise.all([
      downloaded,
      (async () => {
        await page.click(link);
        await page.waitForFunction(() => ['exited', 'failed'].includes(document.querySelector('.snapshot-export-status')?.dataset.status), {timeout: 120000});
        const status = await page.$eval('.snapshot-export-status', element => ({...element.dataset}));
        if (status.exitCode !== '0') throw new Error('Folder WACZ export failed; inspect its native Process log.');
        if (page.url() !== libraryUrl) throw new Error('Folder export navigated away from the selected snapshots.');
      })(),
    ]);
  } finally {
    clearTimeout(downloadTimeout);
    await cdp.detach();
  }
  const expectedDownload = await page.$eval('[data-export-download]', link => link.href);
  if (downloadUrl !== expectedDownload || !fs.statSync(exportedWacz).size) throw new Error('The browser did not download the selected folder WACZ.');
  const sourceDigest = await digest(exportedWacz);
  const {url, directory: playerDirectory} = await exportPlayer(page, libraryUrl, directory, baseUrl);
  const playerWacz = path.join(playerDirectory, 'site.wacz');
  fs.copyFileSync(exportedWacz, playerWacz);
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
