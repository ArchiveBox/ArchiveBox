#!/usr/bin/env node
/**
 * Navigate the Chrome browser to the target URL.
 *
 * This is a simple hook that ONLY navigates - nothing else.
 * Pre-load hooks (21-29) should set up their own CDP listeners.
 * Post-load hooks (31+) can then read from the loaded page.
 *
 * Usage: on_Snapshot__30_chrome_navigate.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes page_loaded.txt marker when navigation completes
 *
 * Environment variables:
 *     CHROME_PAGELOAD_TIMEOUT: Timeout in seconds (default: 60)
 *     CHROME_DELAY_AFTER_LOAD: Extra delay after load in seconds (default: 0)
 *     CHROME_WAIT_FOR: Wait condition (default: networkidle2)
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer');

const PLUGIN_NAME = 'chrome_navigate';
const CHROME_SESSION_DIR = '.';
const OUTPUT_DIR = '.';

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

function getEnvInt(name, defaultValue = 0) {
    const val = parseInt(getEnv(name, String(defaultValue)), 10);
    return isNaN(val) ? defaultValue : val;
}

function getEnvFloat(name, defaultValue = 0) {
    const val = parseFloat(getEnv(name, String(defaultValue)));
    return isNaN(val) ? defaultValue : val;
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
    if (!fs.existsSync(cdpFile)) return null;
    return fs.readFileSync(cdpFile, 'utf8').trim();
}

function getPageId() {
    const targetIdFile = path.join(CHROME_SESSION_DIR, 'target_id.txt');
    if (!fs.existsSync(targetIdFile)) return null;
    return fs.readFileSync(targetIdFile, 'utf8').trim();
}

function getWaitCondition() {
    const waitFor = getEnv('CHROME_WAIT_FOR', 'networkidle2').toLowerCase();
    const valid = ['domcontentloaded', 'load', 'networkidle0', 'networkidle2'];
    return valid.includes(waitFor) ? waitFor : 'networkidle2';
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function navigate(url, cdpUrl) {
    const timeout = (getEnvInt('CHROME_PAGELOAD_TIMEOUT') || getEnvInt('CHROME_TIMEOUT') || getEnvInt('TIMEOUT', 60)) * 1000;
    const delayAfterLoad = getEnvFloat('CHROME_DELAY_AFTER_LOAD', 0) * 1000;
    const waitUntil = getWaitCondition();
    const targetId = getPageId();

    let browser = null;
    const navStartTime = Date.now();

    try {
        browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

        const pages = await browser.pages();
        if (pages.length === 0) {
            return { success: false, error: 'No pages found in browser', waitUntil, elapsed: Date.now() - navStartTime };
        }

        // Find page by target ID if available
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

        // Navigate
        console.log(`Navigating to ${url} (wait: ${waitUntil}, timeout: ${timeout}ms)`);
        const response = await page.goto(url, { waitUntil, timeout });

        // Optional delay
        if (delayAfterLoad > 0) {
            console.log(`Waiting ${delayAfterLoad}ms after load...`);
            await sleep(delayAfterLoad);
        }

        const finalUrl = page.url();
        const status = response ? response.status() : null;
        const elapsed = Date.now() - navStartTime;

        // Write navigation state as JSON
        const navigationState = {
            waitUntil,
            elapsed,
            url,
            finalUrl,
            status,
            timestamp: new Date().toISOString()
        };
        fs.writeFileSync(path.join(OUTPUT_DIR, 'navigation.json'), JSON.stringify(navigationState, null, 2));

        // Write marker files for backwards compatibility
        fs.writeFileSync(path.join(OUTPUT_DIR, 'page_loaded.txt'), new Date().toISOString());
        fs.writeFileSync(path.join(OUTPUT_DIR, 'final_url.txt'), finalUrl);

        browser.disconnect();

        return { success: true, finalUrl, status, waitUntil, elapsed };

    } catch (e) {
        if (browser) browser.disconnect();
        const elapsed = Date.now() - navStartTime;
        return { success: false, error: `${e.name}: ${e.message}`, waitUntil, elapsed };
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__30_chrome_navigate.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    // Wait for chrome tab to be open (up to 60s)
    const tabOpen = await waitForChromeTabOpen(60000);
    if (!tabOpen) {
        console.error('ERROR: Chrome tab not open after 60s (chrome_tab must run first)');
        process.exit(1);
    }

    const cdpUrl = getCdpUrl();
    if (!cdpUrl) {
        console.error('ERROR: Chrome CDP URL not found (chrome tab not initialized)');
        process.exit(1);
    }

    const result = await navigate(url, cdpUrl);

    if (result.success) {
        status = 'succeeded';
        output = 'navigation.json';
        console.log(`Page loaded: ${result.finalUrl} (HTTP ${result.status}) in ${result.elapsed}ms (waitUntil: ${result.waitUntil})`);
    } else {
        error = result.error;
        // Save navigation state even on failure
        const navigationState = {
            waitUntil: result.waitUntil,
            elapsed: result.elapsed,
            url,
            error: result.error,
            timestamp: new Date().toISOString()
        };
        fs.writeFileSync(path.join(OUTPUT_DIR, 'navigation.json'), JSON.stringify(navigationState, null, 2));
    }

    const endTs = new Date();

    if (error) console.error(`ERROR: ${error}`);

    // Output clean JSONL (no RESULT_JSON= prefix)
    console.log(JSON.stringify({
        type: 'ArchiveResult',
        status,
        output_str: output || error || '',
    }));

    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
