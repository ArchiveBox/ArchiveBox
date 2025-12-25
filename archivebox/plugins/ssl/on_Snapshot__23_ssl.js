#!/usr/bin/env node
/**
 * Extract SSL/TLS certificate details from a URL (DAEMON MODE).
 *
 * This hook daemonizes and stays alive to capture SSL details throughout
 * the snapshot lifecycle. It's killed by chrome_cleanup at the end.
 *
 * Usage: on_Snapshot__23_ssl.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes ssl.json + listener.pid
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

// Extractor metadata
const EXTRACTOR_NAME = 'ssl';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'ssl.json';
const PID_FILE = 'listener.pid';
const CHROME_SESSION_DIR = '../chrome_session';

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

// Get environment variable with default
function getEnv(name, defaultValue = '') {
    return (process.env[name] || defaultValue).trim();
}

function getEnvBool(name, defaultValue = false) {
    const val = getEnv(name, '').toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(val)) return true;
    if (['false', '0', 'no', 'off'].includes(val)) return false;
    return defaultValue;
}

// Get CDP URL from chrome_session
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

// Set up SSL listener
async function setupListener(url) {
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    // Only extract SSL for HTTPS URLs
    if (!url.startsWith('https://')) {
        throw new Error('URL is not HTTPS');
    }

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

    // Set up listener to capture SSL details when chrome_navigate loads the page
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

        } catch (e) {
            // Ignore errors
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
        console.error('Usage: on_Snapshot__23_ssl.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    if (!getEnvBool('SAVE_SSL', true)) {
        console.log('Skipping (SAVE_SSL=False)');
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
        // Set up listener
        await setupListener(url);

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
