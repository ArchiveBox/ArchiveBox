#!/usr/bin/env node
/**
 * Save a page using the SingleFile Chrome extension via an existing Chrome session.
 *
 * Usage: singlefile_extension_save.js --url=<url>
 * Output: prints saved file path on success
 */

const fs = require('fs');
const path = require('path');

const CHROME_SESSION_DIR = '../chrome';
const DOWNLOADS_DIR = process.env.CHROME_DOWNLOADS_DIR ||
    path.join(process.env.DATA_DIR || './data', 'personas', process.env.ACTIVE_PERSONA || 'Default', 'chrome_downloads');

process.env.CHROME_DOWNLOADS_DIR = DOWNLOADS_DIR;

async function setDownloadDir(page, downloadDir) {
    try {
        await fs.promises.mkdir(downloadDir, { recursive: true });
        const client = await page.target().createCDPSession();
        try {
            await client.send('Page.setDownloadBehavior', {
                behavior: 'allow',
                downloadPath: downloadDir,
            });
        } catch (err) {
            // Fallback for newer protocol versions
            await client.send('Browser.setDownloadBehavior', {
                behavior: 'allow',
                downloadPath: downloadDir,
            });
        }
    } catch (err) {
        console.error(`[⚠️] Failed to set download directory: ${err.message || err}`);
    }
}

function parseArgs() {
    const args = {};
    process.argv.slice(2).forEach((arg) => {
        if (arg.startsWith('--')) {
            const [key, ...valueParts] = arg.slice(2).split('=');
            args[key.replace(/-/g, '_')] = valueParts.join('=') || true;
        }
    });
    return args;
}

async function main() {
    const args = parseArgs();
    const url = args.url;

    if (!url) {
        console.error('Usage: singlefile_extension_save.js --url=<url>');
        process.exit(1);
    }

    console.error(`[singlefile] helper start url=${url}`);
    console.error(`[singlefile] downloads_dir=${DOWNLOADS_DIR}`);
    if (process.env.CHROME_EXTENSIONS_DIR) {
        console.error(`[singlefile] extensions_dir=${process.env.CHROME_EXTENSIONS_DIR}`);
    }

    try {
        console.error('[singlefile] loading dependencies...');
        const puppeteer = require('puppeteer-core');
        const chromeUtils = require('../chrome/chrome_utils.js');
        const {
            EXTENSION,
            saveSinglefileWithExtension,
        } = require('./on_Crawl__82_singlefile_install.js');
        console.error('[singlefile] dependencies loaded');

        // Ensure extension is installed and metadata is cached
        console.error('[singlefile] ensuring extension cache...');
        const extension = await chromeUtils.installExtensionWithCache(
            EXTENSION,
            { extensionsDir: process.env.CHROME_EXTENSIONS_DIR }
        );
        if (!extension) {
            console.error('[❌] SingleFile extension not installed');
            process.exit(2);
        }
        if (extension.unpacked_path) {
            const runtimeId = chromeUtils.getExtensionId(extension.unpacked_path);
            if (runtimeId) {
                extension.id = runtimeId;
            }
        }
        console.error(`[singlefile] extension ready id=${extension.id} version=${extension.version}`);

        // Connect to existing Chrome session
        console.error('[singlefile] connecting to chrome session...');
        const { browser, page } = await chromeUtils.connectToPage({
            chromeSessionDir: CHROME_SESSION_DIR,
            timeoutMs: 60000,
            puppeteer,
        });
        console.error('[singlefile] connected to chrome');

        try {
            // Ensure CDP target discovery is enabled so service_worker targets appear
            try {
                const client = await page.createCDPSession();
                await client.send('Target.setDiscoverTargets', { discover: true });
                await client.send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
            } catch (err) {
                console.error(`[singlefile] failed to enable target discovery: ${err.message || err}`);
            }

            // Wait for extension target to be available, then attach dispatchAction
            console.error('[singlefile] waiting for extension target...');
            const deadline = Date.now() + 30000;
            let matchTarget = null;
            let matchInfo = null;
            let lastLog = 0;
            const wantedName = (extension.name || 'singlefile').toLowerCase();

            while (Date.now() < deadline && !matchTarget) {
                const targets = browser.targets();
                for (const target of targets) {
                    const info = await chromeUtils.isTargetExtension(target);
                    if (!info?.target_is_extension || !info?.extension_id) {
                        continue;
                    }
                    const manifestName = (info.manifest_name || '').toLowerCase();
                    const targetUrl = (info.target_url || '').toLowerCase();
                    const nameMatches = manifestName.includes(wantedName) || manifestName.includes('singlefile') || manifestName.includes('single-file');
                    const urlMatches = targetUrl.includes('singlefile') || targetUrl.includes('single-file') || targetUrl.includes('single-file-extension');
                    if (nameMatches || urlMatches) {
                        matchTarget = target;
                        matchInfo = info;
                        break;
                    }
                }

                if (!matchTarget) {
                    if (Date.now() - lastLog > 5000) {
                        const targetsSummary = [];
                        for (const target of targets) {
                            const info = await chromeUtils.isTargetExtension(target);
                            if (!info?.target_is_extension) {
                                continue;
                            }
                            targetsSummary.push({
                                type: info.target_type,
                                url: info.target_url,
                                extensionId: info.extension_id,
                                manifestName: info.manifest_name,
                            });
                        }
                        console.error(`[singlefile] waiting... targets total=${targets.length} extensions=${targetsSummary.length} details=${JSON.stringify(targetsSummary)}`);
                        lastLog = Date.now();
                    }
                    await new Promise(r => setTimeout(r, 500));
                }
            }

            if (!matchTarget || !matchInfo) {
                const targets = chromeUtils.getExtensionTargets(browser);
                console.error(`[singlefile] extension target not found (name=${extension.name})`);
                console.error(`[singlefile] available targets: ${JSON.stringify(targets)}`);
                await browser.disconnect();
                process.exit(5);
            }

            // Use the runtime extension id from the matched target
            extension.id = matchInfo.extension_id;

            console.error('[singlefile] loading extension from target...');
            await chromeUtils.loadExtensionFromTarget([extension], matchTarget);
            if (typeof extension.dispatchAction !== 'function') {
                const targets = chromeUtils.getExtensionTargets(browser);
                console.error(`[singlefile] extension dispatchAction missing for id=${extension.id}`);
                console.error(`[singlefile] available targets: ${JSON.stringify(targets)}`);
                await browser.disconnect();
                process.exit(6);
            }
            console.error('[singlefile] setting download dir...');
            await setDownloadDir(page, DOWNLOADS_DIR);

            console.error('[singlefile] triggering save via extension...');
            const output = await saveSinglefileWithExtension(page, extension, { downloadsDir: DOWNLOADS_DIR });
            if (output && fs.existsSync(output)) {
                console.error(`[singlefile] saved: ${output}`);
                console.log(output);
                await browser.disconnect();
                process.exit(0);
            }

            console.error('[❌] SingleFile extension did not produce output');
            await browser.disconnect();
            process.exit(3);
        } catch (err) {
            await browser.disconnect();
            throw err;
        }
    } catch (err) {
        console.error(`[❌] ${err.message || err}`);
        process.exit(4);
    }
}

if (require.main === module) {
    main();
}
