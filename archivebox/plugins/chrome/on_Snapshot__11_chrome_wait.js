#!/usr/bin/env node
/**
 * Wait for Chrome session files to exist (cdp_url.txt + target_id.txt).
 *
 * This is a foreground hook that blocks until the Chrome tab is ready,
 * so downstream hooks can safely connect to CDP.
 *
 * Usage: on_Snapshot__11_chrome_wait.js --url=<url> --snapshot-id=<uuid>
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const {
    getEnvInt,
    waitForChromeSession,
    readCdpUrl,
    readTargetId,
} = require('./chrome_utils.js');

const CHROME_SESSION_DIR = '.';

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

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__11_chrome_wait.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const timeoutSeconds = getEnvInt('CHROME_TAB_TIMEOUT', getEnvInt('CHROME_TIMEOUT', getEnvInt('TIMEOUT', 60)));
    const timeoutMs = timeoutSeconds * 1000;

    console.error(`[chrome_wait] Waiting for Chrome session (timeout=${timeoutSeconds}s)...`);

    const ready = await waitForChromeSession(CHROME_SESSION_DIR, timeoutMs);
    if (!ready) {
        const error = `Chrome session not ready after ${timeoutSeconds}s (cdp_url.txt/target_id.txt missing)`;
        console.error(`[chrome_wait] ERROR: ${error}`);
        console.log(JSON.stringify({ type: 'ArchiveResult', status: 'failed', output_str: error }));
        process.exit(1);
    }

    const cdpUrl = readCdpUrl(CHROME_SESSION_DIR);
    const targetId = readTargetId(CHROME_SESSION_DIR);
    if (!cdpUrl || !targetId) {
        const error = 'Chrome session files incomplete (cdp_url.txt/target_id.txt missing)';
        console.error(`[chrome_wait] ERROR: ${error}`);
        console.log(JSON.stringify({ type: 'ArchiveResult', status: 'failed', output_str: error }));
        process.exit(1);
    }

    console.error(`[chrome_wait] Chrome session ready (cdp_url=${cdpUrl.slice(0, 32)}..., target_id=${targetId}).`);
    console.log(JSON.stringify({ type: 'ArchiveResult', status: 'succeeded', output_str: 'chrome session ready' }));
    process.exit(0);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
