#!/usr/bin/env node
/**
 * Extract the title of a URL.
 *
 * Requires a Chrome session (from chrome plugin) and connects to it via CDP
 * to get the page title (which includes JS-rendered content).
 *
 * Usage: on_Snapshot__10_title.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes title/title.txt
 *
 * Environment variables:
 *     TITLE_TIMEOUT: Timeout in seconds (default: 30)
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

// Import shared utilities from chrome_utils.js
const {
    getEnvInt,
    parseArgs,
    connectToPage,
    waitForPageLoaded,
} = require('../chrome/chrome_utils.js');

// Extractor metadata
const PLUGIN_NAME = 'title';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'title.txt';
const CHROME_SESSION_DIR = '../chrome';

async function extractTitle(url) {
    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
    const timeoutMs = getEnvInt('TITLE_TIMEOUT', getEnvInt('TIMEOUT', 30)) * 1000;
    let browser = null;

    try {
        const connection = await connectToPage({
            chromeSessionDir: CHROME_SESSION_DIR,
            timeoutMs,
            puppeteer,
        });
        browser = connection.browser;
        const page = connection.page;

        await waitForPageLoaded(CHROME_SESSION_DIR, timeoutMs * 4, 200);

        // Get title from page
        let title = await page.title();

        if (!title) {
            // Try getting from DOM directly
            title = await page.evaluate(() => {
                return document.title ||
                       document.querySelector('meta[property="og:title"]')?.content ||
                       document.querySelector('meta[name="twitter:title"]')?.content ||
                       document.querySelector('h1')?.textContent?.trim();
            });
        }

        if (title) {
            fs.writeFileSync(outputPath, title, 'utf8');
            return { success: true, output: outputPath, title, method: 'cdp' };
        }
        return { success: false, error: 'No title found in Chrome session' };
    } catch (e) {
        return { success: false, error: e.message };
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
        console.error('Usage: on_Snapshot__10_title.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';
    let extractedTitle = null;

    try {
        const result = await extractTitle(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            extractedTitle = result.title;
            console.error(`Title extracted (${result.method}): ${result.title}`);
        } else {
            status = 'failed';
            error = result.error;
        }
    } catch (e) {
        error = `${e.name}: ${e.message}`;
        status = 'failed';
    }

    const endTs = new Date();

    if (error) {
        console.error(`ERROR: ${error}`);
    }

    // Update snapshot title via JSONL
    if (status === 'succeeded' && extractedTitle) {
        console.log(JSON.stringify({
            type: 'Snapshot',
            id: snapshotId,
            title: extractedTitle
        }));
    }

    // Output ArchiveResult JSONL
    const archiveResult = {
        type: 'ArchiveResult',
        status,
        output_str: output || error || '',
    };
    console.log(JSON.stringify(archiveResult));

    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
