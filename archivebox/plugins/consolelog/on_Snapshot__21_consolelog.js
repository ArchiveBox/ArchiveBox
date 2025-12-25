#!/usr/bin/env node
/**
 * Capture console output from a page (DAEMON MODE).
 *
 * This hook daemonizes and stays alive to capture console logs throughout
 * the snapshot lifecycle. It's killed by chrome_cleanup at the end.
 *
 * Usage: on_Snapshot__21_consolelog.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes console.jsonl + listener.pid
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const EXTRACTOR_NAME = 'consolelog';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'console.jsonl';
const PID_FILE = 'listener.pid';
const CHROME_SESSION_DIR = '../chrome_session';

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

function getCdpUrl() {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    if (fs.existsSync(cdpFile)) {
        return fs.readFileSync(cdpFile, 'utf8').trim();
    }
    return null;
}

function getPageId() {
    const pageIdFile = path.join(CHROME_SESSION_DIR, 'page_id.txt');
    if (fs.existsSync(pageIdFile)) {
        return fs.readFileSync(pageIdFile, 'utf8').trim();
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

    const cdpUrl = getCdpUrl();
    if (!cdpUrl) {
        throw new Error('No Chrome session found');
    }

    const browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

    // Find our page
    const pages = await browser.pages();
    const pageId = getPageId();
    let page = null;

    if (pageId) {
        page = pages.find(p => {
            const target = p.target();
            return target && target._targetId === pageId;
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

    // Don't disconnect - keep browser connection alive
    return { browser, page };
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__21_consolelog.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    if (!getEnvBool('SAVE_CONSOLELOG', true)) {
        console.log('Skipping (SAVE_CONSOLELOG=False)');
        const result = {
            extractor: EXTRACTOR_NAME,
            status: 'skipped',
            url,
            snapshot_id: snapshotId,
        };
        console.log(`RESULT_JSON=${JSON.stringify(result)}`);
        process.exit(0);
    }

    const startTs = new Date();

    try {
        // Set up listeners
        await setupListeners();

        // Write PID file so chrome_cleanup can kill us
        fs.writeFileSync(path.join(OUTPUT_DIR, PID_FILE), String(process.pid));

        // Report success immediately (we're staying alive in background)
        const endTs = new Date();
        const duration = (endTs - startTs) / 1000;

        console.log(`START_TS=${startTs.toISOString()}`);
        console.log(`END_TS=${endTs.toISOString()}`);
        console.log(`DURATION=${duration.toFixed(2)}`);
        console.log(`OUTPUT=${OUTPUT_FILE}`);
        console.log(`STATUS=succeeded`);

        const result = {
            extractor: EXTRACTOR_NAME,
            url,
            snapshot_id: snapshotId,
            status: 'succeeded',
            start_ts: startTs.toISOString(),
            end_ts: endTs.toISOString(),
            duration: Math.round(duration * 100) / 100,
            output: OUTPUT_FILE,
        };
        console.log(`RESULT_JSON=${JSON.stringify(result)}`);

        // Daemonize: detach from parent and keep running
        // This process will be killed by chrome_cleanup
        if (process.stdin.isTTY) {
            process.stdin.pause();
        }
        process.stdin.unref();
        process.stdout.end();
        process.stderr.end();

        // Keep the process alive indefinitely
        // Will be killed by chrome_cleanup via the PID file
        setInterval(() => {}, 1000);

    } catch (e) {
        const error = `${e.name}: ${e.message}`;
        console.error(`ERROR=${error}`);

        const endTs = new Date();
        const result = {
            extractor: EXTRACTOR_NAME,
            url,
            snapshot_id: snapshotId,
            status: 'failed',
            start_ts: startTs.toISOString(),
            end_ts: endTs.toISOString(),
            error,
        };
        console.log(`RESULT_JSON=${JSON.stringify(result)}`);
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
