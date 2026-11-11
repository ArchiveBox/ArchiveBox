// Exercise the actual storage forms and rclone worker against the gallery's captures.
// The destination must be outside the collection. No credentials are used.
async function setupStorage(page, {adminBaseUrl, destinationPath, runWorker}) {
    await page.goto(`${adminBaseUrl}/admin/storage/new/?provider=local`, {waitUntil: 'domcontentloaded'});
    await page.type('#id_name', 'Hacker News archive copies');
    await page.select('#id_provider', 'local');
    await page.type('#id_path', destinationPath);
    await Promise.all([
        page.waitForNavigation({waitUntil: 'domcontentloaded'}),
        page.click('.storage button[type="submit"]'),
    ]);
    if (page.url().includes('/new/')) {
        const errors = await page.$$eval('.errorlist', nodes => nodes.map(node => node.textContent).join(' '));
        throw new Error(`Storage destination was not saved: ${errors}`);
    }
    const destinationUrl = page.url();
    for (const action of ['install', 'check', 'copy']) {
        if (action === 'install') await page.click('.storage details summary');
        await Promise.all([
            page.waitForNavigation({waitUntil: 'domcontentloaded'}),
            page.click(`form[action$="/${action}/"] button`),
        ]);
        await runWorker();
        await page.goto(destinationUrl, {waitUntil: 'domcontentloaded'});
        await page.waitForFunction(() => {
            const latest = document.querySelector('tbody tr .badge');
            return latest && ['Succeeded', 'Failed', 'Cancelled'].includes(latest.textContent.trim());
        }, {timeout: 180000});
        const latest = await page.$eval('tbody tr', row => row.textContent);
        if (!latest.includes('Succeeded')) throw new Error(`Storage ${action} did not succeed: ${latest}`);
        if (action === 'copy' && !/Copied and verified [1-9][0-9]* sealed snapshots/.test(latest)) {
            throw new Error('Storage gallery requires verified copies of real sealed captures.');
        }
    }
    return destinationUrl;
}

module.exports = {setupStorage};
