// Use the real admin form; the collector runs `archivebox manage linkhealth
// --once` before capturing the returned page, if its normal worker is stopped.
async function prepare(page, adminBaseUrl) {
  await page.goto(`${adminBaseUrl}/admin/link-health/`, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('form[action$="/scan/"] button');
  await Promise.all([
    page.waitForNavigation({waitUntil: 'domcontentloaded'}),
    page.click('form[action$="/scan/"] button'),
  ]);
  if (new URL(page.url()).pathname !== '/admin/link-health/') throw new Error('Link check was not submitted.');
  return {name: 'Link health and duplicates', url: page.url(), path: '/admin/link-health/', source: 'archivebox/linkhealth/templates/linkhealth/index.html'};
}

module.exports = {prepare};
