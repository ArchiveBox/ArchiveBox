#!/usr/bin/env node
/**
 * Extract SSL/TLS certificate details from a URL.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate loads the page,
 * then waits for navigation to complete. The listener captures SSL details
 * during the navigation request.
 *
 * Usage: on_Snapshot__23_ssl.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes ssl.jsonl
 */

const fs = require('fs');
const path = require('path');

// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const puppeteer = require('puppeteer-core');

// Import shared utilities from chrome_utils.js
const {
    getEnvBool,
    getEnvInt,
    parseArgs,
    connectToPage,
    waitForPageLoaded,
} = require('../chrome/chrome_utils.js');

const PLUGIN_NAME = 'ssl';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'ssl.jsonl';
const CHROME_SESSION_DIR = '../chrome';

let browser = null;
let page = null;
let sslCaptured = false;
let shuttingDown = false;

async function setupListener(url) {
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
    const timeout = getEnvInt('SSL_TIMEOUT', 30) * 1000;

    // Only extract SSL for HTTPS URLs
    if (!url.startsWith('https://')) {
        throw new Error('URL is not HTTPS');
    }

    // Connect to Chrome page using shared utility
    const { browser, page } = await connectToPage({
        chromeSessionDir: CHROME_SESSION_DIR,
        timeoutMs: timeout,
        puppeteer,
    });

    // Set up listener to capture SSL details during navigation
    page.on('response', async (response) => {
        try {
            const request = response.request();

            // Only capture the main navigation request
            if (!request.isNavigationRequest() || request.frame() !== page.mainFrame()) {
                return;
            }

            // Only capture if it's for our target URL
            if (!response.url().startsWith(url.split('?')[0])) {
                return;
            }

            // Get security details from the response
            const securityDetails = response.securityDetails();
            let sslInfo = {};

            if (securityDetails) {
                sslInfo.protocol = securityDetails.protocol();
                sslInfo.subjectName = securityDetails.subjectName();
                sslInfo.issuer = securityDetails.issuer();
                sslInfo.validFrom = securityDetails.validFrom();
                sslInfo.validTo = securityDetails.validTo();
                sslInfo.certificateId = securityDetails.subjectName();
                sslInfo.securityState = 'secure';
                sslInfo.schemeIsCryptographic = true;

                const sanList = securityDetails.sanList();
                if (sanList && sanList.length > 0) {
                    sslInfo.subjectAlternativeNames = sanList;
                }
            } else if (response.url().startsWith('https://')) {
                // HTTPS URL but no security details means something went wrong
                sslInfo.securityState = 'unknown';
                sslInfo.schemeIsCryptographic = true;
                sslInfo.error = 'No security details available';
            } else {
                // Non-HTTPS URL
                sslInfo.securityState = 'insecure';
                sslInfo.schemeIsCryptographic = false;
            }

            // Write output directly to file
            fs.writeFileSync(outputPath, JSON.stringify(sslInfo, null, 2));
            sslCaptured = true;

        } catch (e) {
            // Ignore errors
        }
    });

    return { browser, page };
}

function emitResult(status = 'succeeded') {
    if (shuttingDown) return;
    shuttingDown = true;

    const outputStr = sslCaptured ? OUTPUT_FILE : OUTPUT_FILE;
    console.log(JSON.stringify({
        type: 'ArchiveResult',
        status,
        output_str: outputStr,
    }));
}

async function handleShutdown(signal) {
    console.error(`\nReceived ${signal}, emitting final results...`);
    emitResult('succeeded');
    if (browser) {
        try {
            browser.disconnect();
        } catch (e) {}
    }
    process.exit(0);
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__23_ssl.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    if (!getEnvBool('SSL_ENABLED', true)) {
        console.error('Skipping (SSL_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'SSL_ENABLED=False'}));
        process.exit(0);
    }

    try {
        // Set up listener BEFORE navigation
        const connection = await setupListener(url);
        browser = connection.browser;
        page = connection.page;

        // Register signal handlers for graceful shutdown
        process.on('SIGTERM', () => handleShutdown('SIGTERM'));
        process.on('SIGINT', () => handleShutdown('SIGINT'));

        // Wait for chrome_navigate to complete (non-fatal)
        try {
            const timeout = getEnvInt('SSL_TIMEOUT', 30) * 1000;
            await waitForPageLoaded(CHROME_SESSION_DIR, timeout * 4);
        } catch (e) {
            console.error(`WARN: ${e.message}`);
        }

        // console.error('SSL listener active, waiting for cleanup signal...');
        await new Promise(() => {}); // Keep alive until SIGTERM
        return;

    } catch (e) {
        const error = `${e.name}: ${e.message}`;
        console.error(`ERROR: ${error}`);

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
