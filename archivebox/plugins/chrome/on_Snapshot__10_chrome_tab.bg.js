#!/usr/bin/env node
/**
 * Create a Chrome tab for this snapshot in the shared crawl Chrome session.
 *
 * If a crawl-level Chrome session exists (from on_Crawl__90_chrome_launch.bg.js),
 * this connects to it and creates a new tab. Otherwise, falls back to launching
 * its own Chrome instance.
 *
 * Usage: on_Snapshot__10_chrome_tab.bg.js --url=<url> --snapshot-id=<uuid> --crawl-id=<uuid>
 * Output: Creates chrome/ directory under snapshot output dir with:
 *   - cdp_url.txt: WebSocket URL for CDP connection
 *   - chrome.pid: Chrome process ID (from crawl)
 *   - target_id.txt: Target ID of this snapshot's tab
 *   - url.txt: The URL to be navigated to
 *
 * Environment variables:
 *     CRAWL_OUTPUT_DIR: Crawl output directory (to find crawl's Chrome session)
 *     CHROME_BINARY: Path to Chromium binary (for fallback)
 *     CHROME_RESOLUTION: Page resolution (default: 1440,2000)
 *     CHROME_USER_AGENT: User agent string (optional)
 *     CHROME_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: true)
 *     CHROME_HEADLESS: Run in headless mode (default: true)
 *
 * This is a background hook that stays alive until SIGTERM so the tab
 * can be closed cleanly at the end of the snapshot run.
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const puppeteer = require('puppeteer');
const {
    findChromium,
    getEnv,
    getEnvBool,
    parseResolution,
    findFreePort,
    waitForDebugPort,
} = require('./chrome_utils.js');

// Extractor metadata
const PLUGIN_NAME = 'chrome_tab';
const OUTPUT_DIR = '.';  // Hook already runs in chrome/ output directory
const CHROME_SESSION_DIR = '.';

let finalStatus = 'failed';
let finalOutput = '';
let finalError = '';
let cmdVersion = '';
let finalized = false;

// Parse command line arguments
function parseArgs() {
    const args = {};
    process.argv.slice(2).forEach(arg => {
        if (arg.startsWith('--')) {
            const [key, ...valueParts] = arg.slice(2).split('=');
            args[key.replace(/-/g, '_')] = valueParts.join('=') || true;
        }
    });
    return args;
}

function emitResult(statusOverride) {
    if (finalized) return;
    finalized = true;

    const status = statusOverride || finalStatus;
    const outputStr = status === 'succeeded'
        ? finalOutput
        : (finalError || finalOutput || '');

    const result = {
        type: 'ArchiveResult',
        status,
        output_str: outputStr,
    };
    if (cmdVersion) {
        result.cmd_version = cmdVersion;
    }
    console.log(JSON.stringify(result));
}

// Cleanup handler for SIGTERM - close this snapshot's tab
async function cleanup(signal) {
    if (signal) {
        console.error(`\nReceived ${signal}, closing chrome tab...`);
    }
    try {
        const cdpFile = path.join(OUTPUT_DIR, 'cdp_url.txt');
        const targetIdFile = path.join(OUTPUT_DIR, 'target_id.txt');

        if (fs.existsSync(cdpFile) && fs.existsSync(targetIdFile)) {
            const cdpUrl = fs.readFileSync(cdpFile, 'utf8').trim();
            const targetId = fs.readFileSync(targetIdFile, 'utf8').trim();

            const browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });
            const pages = await browser.pages();
            const page = pages.find(p => p.target()._targetId === targetId);

            if (page) {
                await page.close();
            }
            browser.disconnect();
        }
    } catch (e) {
        // Best effort
    }
    emitResult();
    process.exit(finalStatus === 'succeeded' ? 0 : 1);
}

// Register signal handlers
process.on('SIGTERM', () => cleanup('SIGTERM'));
process.on('SIGINT', () => cleanup('SIGINT'));

// Try to find the crawl's Chrome session
function findCrawlChromeSession() {
    // Use CRAWL_OUTPUT_DIR env var set by get_config() in configset.py
    const crawlOutputDir = getEnv('CRAWL_OUTPUT_DIR', '');
    if (!crawlOutputDir) return null;

    const crawlChromeDir = path.join(crawlOutputDir, 'chrome');
    const cdpFile = path.join(crawlChromeDir, 'cdp_url.txt');
    const pidFile = path.join(crawlChromeDir, 'chrome.pid');

    if (fs.existsSync(cdpFile) && fs.existsSync(pidFile)) {
        try {
            const cdpUrl = fs.readFileSync(cdpFile, 'utf-8').trim();
            const pid = parseInt(fs.readFileSync(pidFile, 'utf-8').trim(), 10);

            // Verify the process is still running
            try {
                process.kill(pid, 0);  // Signal 0 = check if process exists
                return { cdpUrl, pid };
            } catch (e) {
                // Process not running
                return null;
            }
        } catch (e) {
            return null;
        }
    }

    return null;
}

// Create a new tab in an existing Chrome session
async function createTabInExistingChrome(cdpUrl, url, pid) {
    const resolution = getEnv('CHROME_RESOLUTION') || getEnv('RESOLUTION', '1440,2000');
    const userAgent = getEnv('CHROME_USER_AGENT') || getEnv('USER_AGENT', '');
    const { width, height } = parseResolution(resolution);

    console.log(`[*] Connecting to existing Chrome session: ${cdpUrl}`);

    // Connect Puppeteer to the running Chrome
    const browser = await puppeteer.connect({
        browserWSEndpoint: cdpUrl,
        defaultViewport: { width, height },
    });

    // Create a new tab for this snapshot
    const page = await browser.newPage();

    // Set viewport
    await page.setViewport({ width, height });

    // Set user agent if specified
    if (userAgent) {
        await page.setUserAgent(userAgent);
    }

    // Get the page target ID
    const target = page.target();
    const targetId = target._targetId;

    // Write session info
    fs.writeFileSync(path.join(OUTPUT_DIR, 'cdp_url.txt'), cdpUrl);
    fs.writeFileSync(path.join(OUTPUT_DIR, 'chrome.pid'), String(pid));
    fs.writeFileSync(path.join(OUTPUT_DIR, 'target_id.txt'), targetId);
    fs.writeFileSync(path.join(OUTPUT_DIR, 'url.txt'), url);

    // Disconnect Puppeteer (Chrome and tab stay alive)
    browser.disconnect();

    return { success: true, output: OUTPUT_DIR, cdpUrl, targetId, pid };
}

// Fallback: Launch a new Chrome instance for this snapshot
async function launchNewChrome(url, binary) {
    const resolution = getEnv('CHROME_RESOLUTION') || getEnv('RESOLUTION', '1440,2000');
    const userAgent = getEnv('CHROME_USER_AGENT') || getEnv('USER_AGENT', '');
    const checkSsl = getEnvBool('CHROME_CHECK_SSL_VALIDITY', getEnvBool('CHECK_SSL_VALIDITY', true));
    const headless = getEnvBool('CHROME_HEADLESS', true);

    const { width, height } = parseResolution(resolution);

    // Find a free port for Chrome DevTools
    const debugPort = await findFreePort();
    console.log(`[*] Launching new Chrome on port: ${debugPort}`);

    // Build Chrome arguments
    const chromeArgs = [
        `--remote-debugging-port=${debugPort}`,
        '--remote-debugging-address=127.0.0.1',
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-sync',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-default-apps',
        '--disable-infobars',
        '--disable-blink-features=AutomationControlled',
        '--disable-component-update',
        '--disable-domain-reliability',
        '--disable-breakpad',
        '--disable-background-networking',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--disable-ipc-flooding-protection',
        '--password-store=basic',
        '--use-mock-keychain',
        '--font-render-hinting=none',
        '--force-color-profile=srgb',
        `--window-size=${width},${height}`,
        ...(headless ? ['--headless=new'] : []),
        ...(checkSsl ? [] : ['--ignore-certificate-errors']),
        'about:blank',
    ];

    // Launch Chrome as a detached process (since no crawl-level Chrome exists)
    const chromeProcess = spawn(binary, chromeArgs, {
        detached: true,
        stdio: ['ignore', 'ignore', 'ignore'],
    });
    chromeProcess.unref();

    const chromePid = chromeProcess.pid;
    console.log(`[*] Launched Chrome (PID: ${chromePid}), waiting for debug port...`);

    // Write PID immediately for cleanup
    fs.writeFileSync(path.join(OUTPUT_DIR, 'chrome.pid'), String(chromePid));

    try {
        // Wait for Chrome to be ready
        const versionInfo = await waitForDebugPort(debugPort, 30000);
        console.log(`[+] Chrome ready: ${versionInfo.Browser}`);

        const wsUrl = versionInfo.webSocketDebuggerUrl;
        fs.writeFileSync(path.join(OUTPUT_DIR, 'cdp_url.txt'), wsUrl);

        // Connect Puppeteer to get page info
        const browser = await puppeteer.connect({
            browserWSEndpoint: wsUrl,
            defaultViewport: { width, height },
        });

        let pages = await browser.pages();
        let page = pages[0];

        if (!page) {
            page = await browser.newPage();
        }

        await page.setViewport({ width, height });

        if (userAgent) {
            await page.setUserAgent(userAgent);
        }

        const target = page.target();
        const targetId = target._targetId;

        fs.writeFileSync(path.join(OUTPUT_DIR, 'chrome.pid'), String(chromePid));
        fs.writeFileSync(path.join(OUTPUT_DIR, 'target_id.txt'), targetId);
        fs.writeFileSync(path.join(OUTPUT_DIR, 'url.txt'), url);

        browser.disconnect();

        return { success: true, output: OUTPUT_DIR, cdpUrl: wsUrl, targetId, pid: chromePid };

    } catch (e) {
        try {
            process.kill(chromePid, 'SIGTERM');
        } catch (killErr) {
            // Ignore
        }
        return { success: false, error: `${e.name}: ${e.message}` };
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;
    const crawlId = args.crawl_id || getEnv('CRAWL_ID', '');

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__10_chrome_tab.bg.js --url=<url> --snapshot-id=<uuid> [--crawl-id=<uuid>]');
        process.exit(1);
    }

    let status = 'failed';
    let output = '';
    let error = '';
    let version = '';

    try {
        const binary = findChromium();
        if (!binary) {
            console.error('ERROR: Chromium binary not found');
            console.error('DEPENDENCY_NEEDED=chromium');
            console.error('BIN_PROVIDERS=puppeteer,env,playwright,apt,brew');
            console.error('INSTALL_HINT=npx @puppeteer/browsers install chromium@latest');
            process.exit(1);
        }

        // Get Chrome version
        try {
            const { execSync } = require('child_process');
            version = execSync(`"${binary}" --version`, { encoding: 'utf8', timeout: 5000 }).trim().slice(0, 64);
        } catch (e) {
            version = '';
        }

        // Try to use existing crawl Chrome session
        const crawlSession = findCrawlChromeSession();
        let result;

        if (crawlSession) {
            console.log(`[*] Found existing Chrome session from crawl ${crawlId}`);
            result = await createTabInExistingChrome(crawlSession.cdpUrl, url, crawlSession.pid);
        } else {
            result = { success: false, error: 'No crawl Chrome session found (CRAWL_OUTPUT_DIR missing or chrome not running)' };
        }

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            console.log(`[+] Chrome tab ready`);
            console.log(`[+] CDP URL: ${result.cdpUrl}`);
            console.log(`[+] Page target ID: ${result.targetId}`);
        } else {
            status = 'failed';
            error = result.error;
        }
    } catch (e) {
        error = `${e.name}: ${e.message}`;
        status = 'failed';
    }

    if (error) {
        console.error(`ERROR: ${error}`);
    }

    finalStatus = status;
    finalOutput = output || '';
    finalError = error || '';
    cmdVersion = version || '';

    if (status !== 'succeeded') {
        emitResult(status);
        process.exit(1);
    }

    console.log('[*] Chrome tab created, waiting for cleanup signal...');
    await new Promise(() => {}); // Keep alive until SIGTERM
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
