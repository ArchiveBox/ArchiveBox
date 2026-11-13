// Submit the real export form, then browse its unchanged recordings using the
// exported ReplayWeb.page player on an ordinary localhost static file server.
function matchesReplayUrl(frameUrl, playerUrl, originalUrl) {
  const replay = URL.parse(frameUrl);
  const prefix = new URL('replay/w/', playerUrl);
  if (!replay || replay.origin !== prefix.origin || !replay.pathname.startsWith(prefix.pathname)) return false;
  const embedded = replay.pathname.match(/\/(https?:\/\/.*)$/)?.[1];
  return Boolean(embedded) && URL.parse(embedded + replay.search + replay.hash)?.href === new URL(originalUrl).href;
}

async function exportPlayer(page, siteUrl, directory, baseUrl, format = 'replay') {
  const fs = require('fs');
  const path = require('path');
  if (!baseUrl) throw new Error('The WACZ gallery requires its localhost export server.');
  await page.goto(siteUrl, {waitUntil: 'domcontentloaded'});
  if (!(await page.$eval('.siteclone-export', element => element.open))) await page.click('.siteclone-export > summary');
  await page.select('#site-export-form select[name="format"]', format);
  const input = '#site-export-form input[name="directory"]';
  await page.focus(input);
  await page.keyboard.press('End');
  await page.keyboard.down('Shift');
  await page.keyboard.press('Home');
  await page.keyboard.up('Shift');
  await page.keyboard.press('Backspace');
  await page.type(input, directory);
  if (await page.$eval(input, el => el.value) !== directory) throw new Error('WACZ export destination was not entered correctly.');
  await Promise.all([
    page.waitForNavigation({waitUntil: 'domcontentloaded'}),
    page.click('#site-export-form button[type="submit"]'),
  ]);
  await page.waitForFunction(() => document.querySelector('#site-export-status')?.dataset.status === 'exited', {timeout: 120000});
  const status = await page.$eval('#site-export-status', element => ({...element.dataset}));
  if (status.exitCode !== '0') throw new Error('WACZ export failed; inspect its native Process log.');
  const exported = await page.$eval('#site-export-path', element => element.textContent.trim());
  const relative = path.relative(directory, exported);
  if (relative.startsWith('..') || path.isAbsolute(relative) || !fs.statSync(path.join(exported, 'site.wacz')).size) {
    throw new Error('WACZ export did not write its server-side archive.');
  }
  const url = new URL(`${relative.split(path.sep).map(encodeURIComponent).join('/')}/index.html`, baseUrl).href;
  return url;
}

async function exportViews(page, clone, directory, baseUrl) {
  const url = await exportPlayer(page, clone.exportUrl, directory, baseUrl);
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
  const siteUrl = `${adminBaseUrl}/admin/domains/site/export/?scope=${encodeURIComponent(new URL(storyUrl).hostname)}`;
  const url = await exportPlayer(page, siteUrl, directory, baseUrl);
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
  const exportUrl = await page.$eval('.folder-actions [data-export-format="wacz"]', link => link.href);
  if (new URL(exportUrl).searchParams.get('folder') !== new URL(libraryUrl).searchParams.get('folder')) {
    throw new Error('The WACZ export lost the selected folder.');
  }
  await exportPlayer(page, exportUrl, directory, baseUrl, 'wacz');
  const exportStatusUrl = page.url();
  const exportedWacz = path.join(await page.$eval('#site-export-path', element => element.textContent.trim()), 'site.wacz');
  const sourceDigest = await digest(exportedWacz);
  const url = await exportPlayer(page, exportUrl, directory, baseUrl);
  const playerDirectory = await page.$eval('#site-export-path', element => element.textContent.trim());
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
    selection: libraryUrl, exportUrl, exportStatusUrl, source: exportedWacz, player: playerWacz,
    sha256: sourceDigest, bytes: fs.statSync(exportedWacz).size,
    from: 'https://news.ycombinator.com/', to: storyUrl, frame: next.url(),
  }, null, 2) + '\n');
  return [
    {name: 'Folder WACZ export', url: exportStatusUrl, path: new URL(exportStatusUrl).pathname, source: 'archivebox/domains/export_service.py'},
    {name: 'Folder WACZ Hacker News', url: homepage, path: new URL(url).pathname, source: 'archivebox/domains/wacz.py', mode: 'wait-replay-url:https://news.ycombinator.com/'},
    {name: 'Folder WACZ story navigation', url: page.url(), path: new URL(url).pathname, source: 'archivebox/domains/wacz.py', mode: `wait-replay-url:${storyUrl}`},
  ];
}

module.exports = {exportViews, storyView, folderViews};
