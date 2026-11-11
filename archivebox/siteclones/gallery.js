// Run against the real logged-in gallery browser. The caller runs the ordinary
// worker after this submission, then photographs the returned detail page.
async function prepare(page, adminBaseUrl) {
  await page.goto(`${adminBaseUrl}/admin/site-clones/`, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('#siteclone-form');
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
  await fill('#id_name', 'Hacker News · site clone gallery');
  await fill('#id_max_depth', '1');
  await fill('#id_max_urls', '5');
  await fill('#id_concurrency', '2');
  await fill('#id_timeout_minutes', '30');
  await page.click('#siteclone-form summary');
  await fill('#id_exclude_paths', '/login\n/logout\n/submit\n/vote\n/hide\n/fave');
  await fill('#id_tags', 'hacker-news,site-clone,screenshot-gallery');
  const plugins = ['wget', 'title', 'screenshot', 'readability', 'parse_dom_outlinks'];
  const selected = await page.select('#id_plugins', ...plugins);
  if (selected.length !== plugins.length || plugins.some(plugin => !selected.includes(plugin))) {
    throw new Error('Site clone capture plugins were not selected correctly.');
  }
  // Existing captures must not turn this demonstration into an empty queue.
  if (await page.$eval('#id_only_new', (input) => input.checked)) await page.click('#id_only_new');
  await Promise.all([
    page.waitForNavigation({waitUntil: 'domcontentloaded'}),
    page.click('#siteclone-form button[type="submit"]'),
  ]);
  const url = page.url();
  if (!/\/admin\/site-clones\/[a-f0-9-]{32,36}\/$/.test(url)) {
    throw new Error(`Site-clone form did not save: ${await page.$eval('main', (main) => main.innerText)}`);
  }
  return {name: 'Site clone progress', url, path: new URL(url).pathname, crawlId: new URL(url).pathname.split('/').filter(Boolean).pop(), source: 'archivebox/siteclones/templates/siteclones/detail.html'};
}

module.exports = {prepare};
