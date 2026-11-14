// Real primary-storage setup. Run only on the gallery's disposable collection.
// Requires a working FUSE device; failures are surfaced, never simulated.
async function setupStorage(page, {adminBaseUrl, destinationPath}) {
    const storageUrl = `${adminBaseUrl}/admin/storage/`;
    await page.goto(storageUrl, {waitUntil: 'domcontentloaded'});
    if (await page.$('.storage [data-archive-status="mounted"]')) return storageUrl;
    const reconnect = Boolean(await page.$('form[action$="/reconnect/"]'));
    if (!reconnect) {
    await page.goto(`${storageUrl}configure/?provider=local`, {waitUntil: 'domcontentloaded'});
    await page.$eval('#id_path', node => { node.value = ''; });
    await page.type('#id_path', destinationPath);
    await page.select('#id_provider', 'local');
    await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click('.storage button[type="submit"]')]);
    if (page.url().includes('/configure/')) {
        throw new Error(`Storage connection was not saved: ${await page.$$eval('.errorlist', nodes => nodes.map(node => node.textContent).join(' '))}`);
    }
    }
    for (const action of reconnect ? ['reconnect'] : ['install', 'check', 'activate']) {
        await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click(`form[action$="/${action}/"] button`)]);
        const deadline = Date.now() + 600000;
        while (true) {
            await page.goto(storageUrl, {waitUntil: 'domcontentloaded'});
            const latest = await page.$eval('.storage-operations tbody tr', row => ({action: row.querySelector('td a').textContent.trim().toLowerCase(), state: row.querySelector('.badge').textContent.trim(), text: row.textContent}));
            if (latest.action !== action) throw new Error(`Unexpected storage process: ${latest.text}`);
            if (latest.state === 'Succeeded') break;
            if (latest.state === 'Failed') throw new Error(`Storage ${action} failed: ${latest.text}`);
            if (Date.now() > deadline) throw new Error(`Storage ${action} is still running after ten minutes.`);
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
    }
    if (!(await page.$('.storage [data-archive-status="mounted"]'))) {
        throw new Error('Storage activation did not switch the primary archive.');
    }
    return storageUrl;
}

module.exports = {setupStorage};
