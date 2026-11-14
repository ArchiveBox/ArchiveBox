// Start a normal link-check process through the real admin form and wait for it.
async function prepare(page, adminBaseUrl, crawlId) {
  const query = crawlId ? `?crawl__id__exact=${encodeURIComponent(crawlId)}` : '';
  await page.goto(`${adminBaseUrl}/admin/link-health/${query}`, {waitUntil: 'domcontentloaded'});
  await Promise.all([
    page.waitForNavigation({waitUntil: 'domcontentloaded'}),
    page.click('button[name="scope"][value="all"]'),
  ]);
  const url = page.url();
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    await page.waitForSelector('#check-progress');
    const state = await page.$eval('#check-progress', node => ({status: node.dataset.processStatus, text: node.innerText}));
    if (state.status === 'exited') {
      if (!state.text.includes('Completed')) throw new Error(`Link check failed: ${state.text}`);
      return {name: 'Broken links', url, path: new URL(url).pathname + new URL(url).search, source: 'archivebox/linkhealth/templates/linkhealth/index.html'};
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
    await page.goto(url, {waitUntil: 'domcontentloaded'});
  }
  throw new Error('The real link-check process did not complete.');
}

module.exports = {prepare};
