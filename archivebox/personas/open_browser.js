#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const pluginsDir = process.env.ARCHIVEBOX_ABX_PLUGINS_DIR;
const {ensureNodeModuleResolution} = require(path.join(pluginsDir, 'base', 'utils.js'));
ensureNodeModuleResolution(module);
const installShutdownHandler = require(path.join(pluginsDir, 'base', 'daemon_lifecycle.js')).captureShutdownSignals();
const {
    acquireSessionLock,
    ensureChromeSession,
    getChromeSessionOptionsFromConfig,
    getChromeLaunchPrerequisites,
    connectToBrowserEndpoint,
    closeBrowserInChromeSession,
} = require(path.join(pluginsDir, 'chrome', 'chrome_utils.js'));

async function main() {
    const config = JSON.parse(fs.readFileSync(0, 'utf8'));
    const outputDir = path.join(path.dirname(config.CHROME_USER_DATA_DIR), '.browser');
    fs.mkdirSync(outputDir, {recursive: true});
    const release = await acquireSessionLock(path.join(outputDir, 'launch.lock'));
    let session;
    const {puppeteer, binary} = getChromeLaunchPrerequisites();
    try {
        session = await ensureChromeSession({
            ...getChromeSessionOptionsFromConfig(config),
            outputDir, puppeteer, binary,
        });
    } finally {
        release();
    }
    const browser = await connectToBrowserEndpoint(puppeteer, session.cdpUrl, {defaultViewport: null});
    installShutdownHandler(async () => {
        if (!session.reusedExisting) {
            await closeBrowserInChromeSession({
                outputDir, puppeteer, cdpUrl: session.cdpUrl, pid: session.pid, processIsLocal: true,
            });
        }
        await browser.disconnect();
        process.exit(0);
    });
    const pages = await browser.pages();
    const page = pages[0] || await browser.newPage();
    const windowSession = await page.createCDPSession();
    const {windowId} = await windowSession.send('Browser.getWindowForTarget');
    await windowSession.send('Browser.setWindowBounds', {windowId, bounds: {windowState: 'maximized'}});
    await windowSession.detach();
    await page.bringToFront();
    console.log(`Browser ready for persona ${config.ACTIVE_PERSONA || 'Default'}`);
    if (session.reusedExisting) {
        await browser.disconnect();
        return;
    }
    await new Promise(resolve => browser.once('disconnected', resolve));
}

main().catch(error => {
    console.error(error.message);
    process.exit(1);
});
