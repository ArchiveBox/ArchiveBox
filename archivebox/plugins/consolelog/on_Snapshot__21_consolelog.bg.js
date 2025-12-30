#!/usr/bin/env node
/**
 * Capture console output from a page.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate loads the page,
 * then waits for navigation to complete. The listeners stay active through
 * navigation and capture all console output.
 *
 * Usage: on_Snapshot__21_consolelog.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes console.jsonl + listener.pid
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

const PLUGIN_NAME = 'consolelog';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'console.jsonl';
const PID_FILE = 'hook.pid';
const CHROME_SESSION_DIR = '../chrome';

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

function getEnv(name, defaultValue = '') {
    return (process.env[name] || defaultValue).trim();
}

function getEnvBool(name, defaultValue = false) {
    const val = getEnv(name, '').toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(val)) return true;
    if (['false', '0', 'no', 'off'].includes(val)) return false;
    return defaultValue;
}

async function waitForChromeTabOpen(timeoutMs = 60000) {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    const targetIdFile = path.join(CHROME_SESSION_DIR, 'target_id.txt');
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        if (fs.existsSync(cdpFile) && fs.existsSync(targetIdFile)) {
            return true;
        }
        // Wait 100ms before checking again
        await new Promise(resolve => setTimeout(resolve, 100));
    }

    return false;
}

function getCdpUrl() {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    if (fs.existsSync(cdpFile)) {
        return fs.readFileSync(cdpFile, 'utf8').trim();
    }
    return null;
}

function getPageId() {
    const targetIdFile = path.join(CHROME_SESSION_DIR, 'target_id.txt');
    if (fs.existsSync(targetIdFile)) {
        return fs.readFileSync(targetIdFile, 'utf8').trim();
    }
    return null;
}

async function serializeArgs(args) {
    const serialized = [];
    for (const arg of args) {
        try {
            const json = await arg.jsonValue();
            serialized.push(json);
        } catch (e) {
            try {
                serialized.push(String(arg));
            } catch (e2) {
                serialized.push('[Unserializable]');
            }
        }
    }
    return serialized;
}

async function setupListeners() {
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
    fs.writeFileSync(outputPath, ''); // Clear existing

    // Wait for chrome tab to be open (up to 60s)
    const tabOpen = await waitForChromeTabOpen(60000);
    if (!tabOpen) {
        throw new Error('Chrome tab not open after 60s (chrome plugin must run first)');
    }

    const cdpUrl = getCdpUrl();
    if (!cdpUrl) {
        throw new Error('No Chrome session found');
    }

    const browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

    // Find our page
    const pages = await browser.pages();
    const targetId = getPageId();
    let page = null;

    if (targetId) {
        page = pages.find(p => {
            const target = p.target();
            return target && target._targetId === targetId;
        });
    }
    if (!page) {
        page = pages[pages.length - 1];
    }

    if (!page) {
        throw new Error('No page found');
    }

    // Set up listeners that write directly to file
    page.on('console', async (msg) => {
        try {
            const logEntry = {
                timestamp: new Date().toISOString(),
                type: msg.type(),
                text: msg.text(),
                args: await serializeArgs(msg.args()),
                location: msg.location(),
            };
            fs.appendFileSync(outputPath, JSON.stringify(logEntry) + '\n');
        } catch (e) {
            // Ignore errors
        }
    });

    page.on('pageerror', (error) => {
        try {
            const logEntry = {
                timestamp: new Date().toISOString(),
                type: 'error',
                text: error.message,
                stack: error.stack || '',
            };
            fs.appendFileSync(outputPath, JSON.stringify(logEntry) + '\n');
        } catch (e) {
            // Ignore
        }
    });

    page.on('requestfailed', (request) => {
        try {
            const failure = request.failure();
            const logEntry = {
                timestamp: new Date().toISOString(),
                type: 'request_failed',
                text: `Request failed: ${request.url()}`,
                error: failure ? failure.errorText : 'Unknown error',
                url: request.url(),
            };
            fs.appendFileSync(outputPath, JSON.stringify(logEntry) + '\n');
        } catch (e) {
            // Ignore
        }
    });

    return { browser, page };
}

async function waitForNavigation() {
    // Wait for chrome_navigate to complete (it writes page_loaded.txt)
    const navDir = '../chrome';
    const pageLoadedMarker = path.join(navDir, 'page_loaded.txt');
    const maxWait = 120000; // 2 minutes
    const pollInterval = 100;
    let waitTime = 0;

    while (!fs.existsSync(pageLoadedMarker) && waitTime < maxWait) {
        await new Promise(resolve => setTimeout(resolve, pollInterval));
        waitTime += pollInterval;
    }

    if (!fs.existsSync(pageLoadedMarker)) {
        throw new Error('Timeout waiting for navigation (chrome_navigate did not complete)');
    }

    // Wait a bit longer for any post-load console output
    await new Promise(resolve => setTimeout(resolve, 500));
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__21_consolelog.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    if (!getEnvBool('CONSOLELOG_ENABLED', true)) {
        console.error('Skipping (CONSOLELOG_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'CONSOLELOG_ENABLED=False'}));
        process.exit(0);
    }

    const startTs = new Date();

    try {
        // Set up listeners BEFORE navigation
        await setupListeners();

        // Write PID file so chrome_cleanup can kill any remaining processes
        fs.writeFileSync(path.join(OUTPUT_DIR, PID_FILE), String(process.pid));

        // Wait for chrome_navigate to complete (BLOCKING)
        await waitForNavigation();

        // Report success
        const endTs = new Date();

        // Output clean JSONL (no RESULT_JSON= prefix)
        console.log(JSON.stringify({
            type: 'ArchiveResult',
            status: 'succeeded',
            output_str: OUTPUT_FILE,
        }));

        process.exit(0);

    } catch (e) {
        const error = `${e.name}: ${e.message}`;
        console.error(`ERROR: ${error}`);

        // Output clean JSONL (no RESULT_JSON= prefix)
        console.log(JSON.stringify({
            type: 'ArchiveResult',
            status: 'failed',
            output_str: error,
        }));
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
