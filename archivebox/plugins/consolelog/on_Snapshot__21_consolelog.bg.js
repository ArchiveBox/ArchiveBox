#!/usr/bin/env node
/**
 * Capture console output from a page.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate loads the page,
 * then waits for navigation to complete. The listeners stay active through
 * navigation and capture all console output.
 *
 * Usage: on_Snapshot__21_consolelog.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes console.jsonl
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

const PLUGIN_NAME = 'consolelog';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'console.jsonl';
const CHROME_SESSION_DIR = '../chrome';

let browser = null;
let page = null;
let logCount = 0;
let errorCount = 0;
let requestFailCount = 0;
let shuttingDown = false;

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
    const timeout = getEnvInt('CONSOLELOG_TIMEOUT', 30) * 1000;

    fs.writeFileSync(outputPath, ''); // Clear existing

    // Connect to Chrome page using shared utility
    const { browser, page } = await connectToPage({
        chromeSessionDir: CHROME_SESSION_DIR,
        timeoutMs: timeout,
        puppeteer,
    });

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
            logCount += 1;
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
            errorCount += 1;
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
            requestFailCount += 1;
        } catch (e) {
            // Ignore
        }
    });

    return { browser, page };
}

function emitResult(status = 'succeeded') {
    if (shuttingDown) return;
    shuttingDown = true;

    const counts = `${logCount} console, ${errorCount} errors, ${requestFailCount} failed requests`;
    console.log(JSON.stringify({
        type: 'ArchiveResult',
        status,
        output_str: `${OUTPUT_FILE} (${counts})`,
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
        console.error('Usage: on_Snapshot__21_consolelog.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    if (!getEnvBool('CONSOLELOG_ENABLED', true)) {
        console.error('Skipping (CONSOLELOG_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'CONSOLELOG_ENABLED=False'}));
        process.exit(0);
    }

    try {
        // Set up listeners BEFORE navigation
        const connection = await setupListeners();
        browser = connection.browser;
        page = connection.page;

        // Register signal handlers for graceful shutdown
        process.on('SIGTERM', () => handleShutdown('SIGTERM'));
        process.on('SIGINT', () => handleShutdown('SIGINT'));

        // Wait for chrome_navigate to complete (non-fatal)
        try {
            const timeout = getEnvInt('CONSOLELOG_TIMEOUT', 30) * 1000;
            await waitForPageLoaded(CHROME_SESSION_DIR, timeout * 4, 500);
        } catch (e) {
            console.error(`WARN: ${e.message}`);
        }

        // console.error('Consolelog active, waiting for cleanup signal...');
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
