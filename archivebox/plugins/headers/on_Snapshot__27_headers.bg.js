#!/usr/bin/env node
/**
 * Capture original request + response headers for the main navigation.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate loads the page,
 * then waits for navigation to complete. It records the first top-level
 * request headers and the corresponding response headers (with :status).
 *
 * Usage: on_Snapshot__27_headers.bg.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes headers.json
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

const PLUGIN_NAME = 'headers';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'headers.json';
const CHROME_SESSION_DIR = '../chrome';
const CHROME_SESSION_REQUIRED_ERROR = 'No Chrome session found (chrome plugin must run first)';

let browser = null;
let page = null;
let client = null;
let shuttingDown = false;
let headersWritten = false;

let requestId = null;
let requestUrl = null;
let requestHeaders = null;
let responseHeaders = null;
let responseStatus = null;
let responseStatusText = null;
let responseUrl = null;
let originalUrl = null;

function getFinalUrl() {
    const finalUrlFile = path.join(CHROME_SESSION_DIR, 'final_url.txt');
    if (fs.existsSync(finalUrlFile)) {
        return fs.readFileSync(finalUrlFile, 'utf8').trim();
    }
    return page ? page.url() : null;
}

function writeHeadersFile() {
    if (headersWritten) return;
    if (!responseHeaders) return;

    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
    const responseHeadersWithStatus = {
        ...(responseHeaders || {}),
    };

    if (responseStatus !== null && responseStatus !== undefined &&
        responseHeadersWithStatus[':status'] === undefined) {
        responseHeadersWithStatus[':status'] = String(responseStatus);
    }

    const record = {
        url: requestUrl || originalUrl,
        final_url: getFinalUrl(),
        status: responseStatus !== undefined ? responseStatus : null,
        request_headers: requestHeaders || {},
        response_headers: responseHeadersWithStatus,
        headers: responseHeadersWithStatus, // backwards compatibility
    };

    if (responseStatusText) {
        record.statusText = responseStatusText;
    }
    if (responseUrl) {
        record.response_url = responseUrl;
    }

    fs.writeFileSync(outputPath, JSON.stringify(record, null, 2));
    headersWritten = true;
}

async function setupListener(url) {
    const timeout = getEnvInt('HEADERS_TIMEOUT', getEnvInt('TIMEOUT', 30)) * 1000;
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    const targetIdFile = path.join(CHROME_SESSION_DIR, 'target_id.txt');
    const pidFile = path.join(CHROME_SESSION_DIR, 'chrome.pid');

    if (!fs.existsSync(cdpFile) || !fs.existsSync(targetIdFile) || !fs.existsSync(pidFile)) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }
    try {
        const pid = parseInt(fs.readFileSync(pidFile, 'utf8').trim(), 10);
        if (!pid || Number.isNaN(pid)) throw new Error('Invalid pid');
        process.kill(pid, 0);
    } catch (e) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }

    const { browser, page } = await connectToPage({
        chromeSessionDir: CHROME_SESSION_DIR,
        timeoutMs: timeout,
        puppeteer,
    });

    client = await page.target().createCDPSession();
    await client.send('Network.enable');

    client.on('Network.requestWillBeSent', (params) => {
        try {
            if (requestId && !responseHeaders && params.redirectResponse && params.requestId === requestId) {
                responseHeaders = params.redirectResponse.headers || {};
                responseStatus = params.redirectResponse.status || null;
                responseStatusText = params.redirectResponse.statusText || null;
                responseUrl = params.redirectResponse.url || null;
                writeHeadersFile();
            }

            if (requestId) return;
            if (params.type && params.type !== 'Document') return;
            if (!params.request || !params.request.url) return;
            if (!params.request.url.startsWith('http')) return;

            requestId = params.requestId;
            requestUrl = params.request.url;
            requestHeaders = params.request.headers || {};
        } catch (e) {
            // Ignore errors
        }
    });

    client.on('Network.responseReceived', (params) => {
        try {
            if (!requestId || params.requestId !== requestId || responseHeaders) return;
            const response = params.response || {};
            responseHeaders = response.headers || {};
            responseStatus = response.status || null;
            responseStatusText = response.statusText || null;
            responseUrl = response.url || null;
            writeHeadersFile();
        } catch (e) {
            // Ignore errors
        }
    });

    return { browser, page };
}

function emitResult(status = 'succeeded', outputStr = OUTPUT_FILE) {
    if (shuttingDown) return;
    shuttingDown = true;

    console.log(JSON.stringify({
        type: 'ArchiveResult',
        status,
        output_str: outputStr,
    }));
}

async function handleShutdown(signal) {
    console.error(`\nReceived ${signal}, emitting final results...`);
    if (!headersWritten) {
        writeHeadersFile();
    }
    if (headersWritten) {
        emitResult('succeeded', OUTPUT_FILE);
    } else {
        emitResult('failed', 'No headers captured');
    }

    if (browser) {
        try {
            browser.disconnect();
        } catch (e) {}
    }
    process.exit(headersWritten ? 0 : 1);
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__27_headers.bg.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    originalUrl = url;

    if (!getEnvBool('HEADERS_ENABLED', true)) {
        console.error('Skipping (HEADERS_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'HEADERS_ENABLED=False'}));
        process.exit(0);
    }

    try {
        // Set up listeners BEFORE navigation
        const connection = await setupListener(url);
        browser = connection.browser;
        page = connection.page;

        // Register signal handlers for graceful shutdown
        process.on('SIGTERM', () => handleShutdown('SIGTERM'));
        process.on('SIGINT', () => handleShutdown('SIGINT'));

        // Wait for chrome_navigate to complete (non-fatal)
        try {
            const timeout = getEnvInt('HEADERS_TIMEOUT', getEnvInt('TIMEOUT', 30)) * 1000;
            await waitForPageLoaded(CHROME_SESSION_DIR, timeout * 4, 200);
        } catch (e) {
            console.error(`WARN: ${e.message}`);
        }

        // Keep alive until SIGTERM
        await new Promise(() => {});
        return;

    } catch (e) {
        const errorMessage = (e && e.message)
            ? `${e.name || 'Error'}: ${e.message}`
            : String(e || 'Unknown error');
        console.error(`ERROR: ${errorMessage}`);

        console.log(JSON.stringify({
            type: 'ArchiveResult',
            status: 'failed',
            output_str: errorMessage,
        }));
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
