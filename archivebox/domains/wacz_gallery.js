// Submit the real export form, then browse its unchanged recordings using the
// exported ReplayWeb.page player on an ordinary localhost static file server.
function matchesReplayUrl(frameUrl, playerUrl, originalUrl) {
  const replay = URL.parse(frameUrl);
  const prefix = new URL('replay/w/', playerUrl);
  if (!replay || replay.origin !== prefix.origin || !replay.pathname.startsWith(prefix.pathname)) return false;
  const embedded = replay.pathname.match(/\/(https?:\/\/.*)$/)?.[1];
  return Boolean(embedded) && URL.parse(embedded + replay.search + replay.hash)?.href === new URL(originalUrl).href;
}

async function exportPlayer(page, siteUrl, directory, baseUrl) {
  const fs = require('fs');
  const path = require('path');
  if (!baseUrl) throw new Error('The WACZ gallery requires its localhost export server.');
  await page.goto(siteUrl, {waitUntil: 'domcontentloaded'});
  if (!(await page.$eval('.siteclone-export', element => element.open))) await page.click('.siteclone-export > summary');
  await page.select('#site-export-form select[name="format"]', 'replay');
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

module.exports = {exportViews, storyView};
