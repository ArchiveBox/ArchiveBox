/** Prepare the gallery using the real audit form and native background Process. */
exports.prepare = async function prepare(page, adminBaseUrl) {
    await page.goto(`${adminBaseUrl}/admin/storage-audit/`, {waitUntil: 'networkidle0'});
    await Promise.all([
        page.waitForNavigation({waitUntil: 'networkidle0'}),
        page.click('form[action$="/scan/"] button'),
    ]);
    const auditUrl = page.url();
    const deadline = Date.now() + 120000;
    while (Date.now() < deadline) {
        const state = await page.evaluate(() => document.querySelector('.storage-audit').innerText);
        if (/Exit [1-9]/.test(state)) throw new Error(`Real storage audit failed: ${state}`);
        if (await page.$('[data-audit-complete]')) {
            for (const id of ['slowest-plugins', 'heaviest-plugins', 'largest-snapshots']) {
                if (!(await page.$(`#${id} tbody a`))) throw new Error(`No real ranking data in ${id}.`);
            }
            if (!(await page.$('.audit-extension'))) throw new Error('No verified duplicate files exist to review.');
            const extension = await page.$eval('.audit-extension', el => el.dataset.extension);
            return {auditUrl, extensionUrl: `${auditUrl}&extension=${encodeURIComponent(extension)}`};
        }
        await new Promise(resolve => setTimeout(resolve, 1000));
        await page.reload({waitUntil: 'networkidle0'});
    }
    throw new Error('Storage audit did not finish; no substitute report was generated.');
};

exports.preview = async function preview(page) {
    const extension = await page.$('.audit-extension');
    if (!extension) throw new Error('No verified duplicate files exist to review.');
    await extension.$eval('summary', el => el.click());
    await Promise.all([
        page.waitForNavigation({waitUntil: 'networkidle0'}),
        extension.$eval('form[action$="/preview/"] button', el => el.click()),
    ]);
    if (!(await page.$('form[action$="/apply/"]')) || !(await page.$('.audit-files tbody tr'))) throw new Error('Did not reach real file selection preview.');
};
