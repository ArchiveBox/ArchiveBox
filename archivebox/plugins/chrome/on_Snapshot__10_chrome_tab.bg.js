#!/usr/bin/env node
/**
 * Create a Chrome tab for this snapshot in the shared crawl Chrome session.
 *
 * Connects to the crawl-level Chrome session (from on_Crawl__90_chrome_launch.bg.js)
 * and creates a new tab. This hook does NOT launch its own Chrome instance.
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
 *     CHROME_BINARY: Path to Chromium binary (optional, for version info)
 *
 * This is a background hook that stays alive until SIGTERM so the tab
 * can be closed cleanly at the end of the snapshot run.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const puppeteer = require('puppeteer');
const { getEnv, getEnvInt } = require('./chrome_utils.js');

// Extractor metadata
const PLUGIN_NAME = 'chrome_tab';
const OUTPUT_DIR = '.';  // Hook already runs in chrome/ output directory
const CHROME_SESSION_DIR = '.';
const CHROME_SESSION_REQUIRED_ERROR = 'No Chrome session found (chrome plugin must run first)';

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
function getCrawlChromeSession() {
    // Use CRAWL_OUTPUT_DIR env var set by get_config() in configset.py
    const crawlOutputDir = getEnv('CRAWL_OUTPUT_DIR', '');
    if (!crawlOutputDir) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }

    const crawlChromeDir = path.join(crawlOutputDir, 'chrome');
    const cdpFile = path.join(crawlChromeDir, 'cdp_url.txt');
    const pidFile = path.join(crawlChromeDir, 'chrome.pid');

    if (!fs.existsSync(cdpFile)) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }
    if (!fs.existsSync(pidFile)) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }

    const cdpUrl = fs.readFileSync(cdpFile, 'utf-8').trim();
    const pid = parseInt(fs.readFileSync(pidFile, 'utf-8').trim(), 10);
    if (!cdpUrl) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }
    if (!pid || Number.isNaN(pid)) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }

    // Verify the process is still running
    try {
        process.kill(pid, 0);  // Signal 0 = check if process exists
    } catch (e) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }

    return { cdpUrl, pid };
}

async function waitForCrawlChromeSession(timeoutMs, intervalMs = 250) {
    const startTime = Date.now();
    let lastError = null;

    while (Date.now() - startTime < timeoutMs) {
        try {
            return getCrawlChromeSession();
        } catch (e) {
            lastError = e;
        }
        await new Promise(resolve => setTimeout(resolve, intervalMs));
    }

    if (lastError) {
        throw lastError;
    }
    throw new Error(CHROME_SESSION_REQUIRED_ERROR);
}

// Create a new tab in an existing Chrome session
async function createTabInExistingChrome(cdpUrl, url, pid) {
    console.log(`[*] Connecting to existing Chrome session: ${cdpUrl}`);

    // Connect Puppeteer to the running Chrome
    const browser = await puppeteer.connect({
        browserWSEndpoint: cdpUrl,
        defaultViewport: null,
    });

    // Create a new tab for this snapshot
    const page = await browser.newPage();

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
        // Get Chrome version
        try {
            const binary = getEnv('CHROME_BINARY', '').trim();
            if (binary) {
                version = execSync(`"${binary}" --version`, { encoding: 'utf8', timeout: 5000 }).trim().slice(0, 64);
            }
        } catch (e) {
            version = '';
        }

        // Try to use existing crawl Chrome session (wait for readiness)
        const timeoutSeconds = getEnvInt('CHROME_TAB_TIMEOUT', getEnvInt('CHROME_TIMEOUT', getEnvInt('TIMEOUT', 60)));
        const crawlSession = await waitForCrawlChromeSession(timeoutSeconds * 1000);
        console.log(`[*] Found existing Chrome session from crawl ${crawlId}`);
        const result = await createTabInExistingChrome(crawlSession.cdpUrl, url, crawlSession.pid);

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
