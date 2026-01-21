#!/usr/bin/env node
/**
 * Dump the DOM of a URL using Chrome/Puppeteer.
 *
 * Requires a Chrome session (from chrome plugin) and connects to it via CDP.
 *
 * Usage: on_Snapshot__53_dom.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes dom/output.html
 *
 * Environment variables:
 *     DOM_ENABLED: Enable DOM extraction (default: true)
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const {
    getEnvBool,
    parseArgs,
    readCdpUrl,
} = require('../chrome/chrome_utils.js');

// Check if DOM is enabled BEFORE requiring puppeteer
if (!getEnvBool('DOM_ENABLED', true)) {
    console.error('Skipping DOM (DOM_ENABLED=False)');
    // Temporary failure (config disabled) - NO JSONL emission
    process.exit(0);
}

// Now safe to require puppeteer
const puppeteer = require('puppeteer-core');

// Extractor metadata
const PLUGIN_NAME = 'dom';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'output.html';
const CHROME_SESSION_DIR = '../chrome';

// Check if staticfile extractor already downloaded this URL
const STATICFILE_DIR = '../staticfile';
function hasStaticFileOutput() {
    if (!fs.existsSync(STATICFILE_DIR)) return false;
    const stdoutPath = path.join(STATICFILE_DIR, 'stdout.log');
    if (!fs.existsSync(stdoutPath)) return false;
    const stdout = fs.readFileSync(stdoutPath, 'utf8');
    for (const line of stdout.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('{')) continue;
        try {
            const record = JSON.parse(trimmed);
            if (record.type === 'ArchiveResult' && record.status === 'succeeded') {
                return true;
            }
        } catch (e) {}
    }
    return false;
}

// Wait for chrome tab to be fully loaded
async function waitForChromeTabLoaded(timeoutMs = 60000) {
    const navigationFile = path.join(CHROME_SESSION_DIR, 'navigation.json');
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        if (fs.existsSync(navigationFile)) {
            return true;
        }
        // Wait 100ms before checking again
        await new Promise(resolve => setTimeout(resolve, 100));
    }

    return false;
}

async function dumpDom(url) {
    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    let browser = null;
    let page = null;

    try {
        // Connect to existing Chrome session (required)
        const cdpUrl = readCdpUrl(CHROME_SESSION_DIR);
        if (!cdpUrl) {
            return { success: false, error: 'No Chrome session found (chrome plugin must run first)' };
        }

        browser = await puppeteer.connect({
            browserWSEndpoint: cdpUrl,
            defaultViewport: null,
        });

        // Get existing pages or create new one
        const pages = await browser.pages();
        page = pages.find(p => p.url().startsWith('http')) || pages[0];

        if (!page) {
            page = await browser.newPage();
        }

        // Get the full DOM content
        const domContent = await page.content();

        if (domContent && domContent.length > 100) {
            fs.writeFileSync(outputPath, domContent, 'utf8');
            return { success: true, output: outputPath };
        } else {
            return { success: false, error: 'DOM content too short or empty' };
        }

    } catch (e) {
        return { success: false, error: `${e.name}: ${e.message}` };
    } finally {
        if (browser) {
            browser.disconnect();
        }
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__53_dom.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    try {
        // Check if staticfile extractor already handled this (permanent skip)
        if (hasStaticFileOutput()) {
            console.error(`Skipping DOM - staticfile extractor already downloaded this`);
            // Permanent skip - emit ArchiveResult with status='skipped'
            console.log(JSON.stringify({
                type: 'ArchiveResult',
                status: 'skipped',
                output_str: 'staticfile already handled',
            }));
            process.exit(0);
        }

        const cdpUrl = readCdpUrl(CHROME_SESSION_DIR);
        if (!cdpUrl) {
            throw new Error('No Chrome session found (chrome plugin must run first)');
        }

        // Wait for page to be fully loaded
        const pageLoaded = await waitForChromeTabLoaded(60000);
        if (!pageLoaded) {
            throw new Error('Page not loaded after 60s (chrome_navigate must complete first)');
        }

        const result = await dumpDom(url);

        if (result.success) {
            // Success - emit ArchiveResult
            const size = fs.statSync(result.output).size;
            console.error(`DOM saved (${size} bytes)`);
            console.log(JSON.stringify({
                type: 'ArchiveResult',
                status: 'succeeded',
                output_str: result.output,
            }));
            process.exit(0);
        } else {
            // Transient error - emit NO JSONL
            console.error(`ERROR: ${result.error}`);
            process.exit(1);
        }
    } catch (e) {
        // Transient error - emit NO JSONL
        console.error(`ERROR: ${e.name}: ${e.message}`);
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
