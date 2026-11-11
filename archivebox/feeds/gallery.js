// Persist a real feed subscription and export the actual organized capture list.
async function submit(page, selector) {
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click(selector)]);
  const errors = await page.$$eval('.errorlist', nodes => nodes.map(node => node.textContent.trim()).join(' '));
  if (errors) throw new Error(errors);
}

async function prepare(page, adminBaseUrl, libraryUrl) {
  await page.goto(`${adminBaseUrl}/admin/feeds/`, {waitUntil: 'domcontentloaded'});
  const exported = await page.$$eval('article', cards => cards.some(card => card.querySelector('h2,h3')?.textContent.trim() === 'Hacker News reading list'));
  const subscription = await page.$$eval('table a', links => links.some(link => link.textContent === 'Hacker News RSS'));
  if (!subscription) {
    await page.type('#id_name', 'Hacker News RSS');
    await page.type('#id_url', 'https://news.ycombinator.com/rss');
    await page.click('.feed-subscribe details summary');
    await page.type('#id_tags', 'Hacker-News');
    await submit(page, '#content form button[type="submit"]');
    if (!page.url().includes('/admin/importers/')) throw new Error('Feed subscription was not saved.');
  }
  if (!exported) {
    await page.goto(libraryUrl, {waitUntil: 'domcontentloaded'});
    const link = await page.$eval('.folder-actions a[href*="/feeds/export/"]', node => node.href);
    await page.goto(link, {waitUntil: 'domcontentloaded'});
    await page.focus('#id_name');
    await page.keyboard.press('End');
    await page.keyboard.down('Shift');
    await page.keyboard.press('Home');
    await page.keyboard.up('Shift');
    await page.keyboard.press('Backspace');
    await page.type('#id_name', 'Hacker News reading list');
    if (await page.$eval('#id_name', input => input.value) !== 'Hacker News reading list') throw new Error('Feed name was not entered correctly.');
    await submit(page, '#content form button[type="submit"]');
  } else {
    await page.goto(`${adminBaseUrl}/admin/feeds/`, {waitUntil: 'domcontentloaded'});
  }
  if (!await page.$('a[href*="/feeds/read/"]')) throw new Error('RSS link was not saved.');
  return {name: 'RSS subscriptions and exported lists', url: `${adminBaseUrl}/admin/feeds/`, path: '/admin/feeds/', source: 'archivebox/feeds/views.py'};
}

module.exports = {prepare};
