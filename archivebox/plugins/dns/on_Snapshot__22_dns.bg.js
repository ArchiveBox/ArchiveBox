#!/usr/bin/env node
/**
 * Record all DNS traffic (hostname -> IP resolutions) during page load.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate loads the page,
 * then waits for navigation to complete. The listeners capture all DNS
 * resolutions by extracting hostname/IP pairs from network responses.
 *
 * Usage: on_Snapshot__22_dns.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes dns.jsonl with one line per DNS resolution record
 */

const fs = require('fs');
const path = require('path');

// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const puppeteer = require('puppeteer-core');

// Import shared utilities from chrome_utils.js
const chromeUtils = require('../chrome/chrome_utils.js');
const { getEnv, getEnvBool, getEnvInt } = chromeUtils;

const PLUGIN_NAME = 'dns';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'dns.jsonl';
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

// Chrome session file helpers (these are local to each plugin's working directory)
async function waitForChromeTabOpen(timeoutMs = 60000) {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    const targetIdFile = path.join(CHROME_SESSION_DIR, 'target_id.txt');
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        if (fs.existsSync(cdpFile) && fs.existsSync(targetIdFile)) {
            return true;
        }
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

function extractHostname(url) {
    try {
        const urlObj = new URL(url);
        return urlObj.hostname;
    } catch (e) {
        return null;
    }
}

async function setupListener(targetUrl) {
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
    const timeout = getEnvInt('DNS_TIMEOUT', 30) * 1000;

    // Initialize output file
    fs.writeFileSync(outputPath, '');

    // Track seen hostname -> IP mappings to avoid duplicates per request
    const seenResolutions = new Map();
    // Track request IDs to their URLs for correlation
    const requestUrls = new Map();

    // Wait for chrome tab to be open
    const tabOpen = await waitForChromeTabOpen(timeout);
    if (!tabOpen) {
        throw new Error(`Chrome tab not open after ${timeout/1000}s (chrome plugin must run first)`);
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

    // Get CDP session for low-level network events
    const client = await page.target().createCDPSession();

    // Enable network domain to receive events
    await client.send('Network.enable');

    // Listen for request events to track URLs
    client.on('Network.requestWillBeSent', (params) => {
        requestUrls.set(params.requestId, params.request.url);
    });

    // Listen for response events which contain remoteIPAddress (the resolved IP)
    client.on('Network.responseReceived', (params) => {
        try {
            const response = params.response;
            const url = response.url;
            const remoteIPAddress = response.remoteIPAddress;
            const remotePort = response.remotePort;

            if (!url || !remoteIPAddress) {
                return;
            }

            const hostname = extractHostname(url);
            if (!hostname) {
                return;
            }

            // Skip if IP address is same as hostname (already an IP)
            if (hostname === remoteIPAddress) {
                return;
            }

            // Create a unique key for this resolution
            const resolutionKey = `${hostname}:${remoteIPAddress}`;

            // Skip if we've already recorded this resolution
            if (seenResolutions.has(resolutionKey)) {
                return;
            }
            seenResolutions.set(resolutionKey, true);

            // Determine record type (A for IPv4, AAAA for IPv6)
            const isIPv6 = remoteIPAddress.includes(':');
            const recordType = isIPv6 ? 'AAAA' : 'A';

            // Create DNS record
            const timestamp = new Date().toISOString();
            const dnsRecord = {
                ts: timestamp,
                hostname: hostname,
                ip: remoteIPAddress,
                port: remotePort || null,
                type: recordType,
                protocol: url.startsWith('https://') ? 'https' : 'http',
                url: url,
                requestId: params.requestId,
            };

            // Append to output file
            fs.appendFileSync(outputPath, JSON.stringify(dnsRecord) + '\n');

        } catch (e) {
            // Ignore errors
        }
    });

    // Listen for failed requests too - they still involve DNS
    client.on('Network.loadingFailed', (params) => {
        try {
            const requestId = params.requestId;
            const url = requestUrls.get(requestId);

            if (!url) {
                return;
            }

            const hostname = extractHostname(url);
            if (!hostname) {
                return;
            }

            // Check if this is a DNS-related failure
            const errorText = params.errorText || '';
            if (errorText.includes('net::ERR_NAME_NOT_RESOLVED') ||
                errorText.includes('net::ERR_NAME_RESOLUTION_FAILED')) {

                const timestamp = new Date().toISOString();
                const dnsRecord = {
                    ts: timestamp,
                    hostname: hostname,
                    ip: null,
                    port: null,
                    type: 'NXDOMAIN',
                    protocol: url.startsWith('https://') ? 'https' : 'http',
                    url: url,
                    requestId: requestId,
                    error: errorText,
                };

                fs.appendFileSync(outputPath, JSON.stringify(dnsRecord) + '\n');
            }
        } catch (e) {
            // Ignore errors
        }
    });

    return { browser, page, client };
}

async function waitForNavigation() {
    // Wait for chrome_navigate to complete (it writes page_loaded.txt)
    const pageLoadedMarker = path.join(CHROME_SESSION_DIR, 'page_loaded.txt');
    const maxWait = getEnvInt('DNS_TIMEOUT', 30) * 1000 * 4; // 4x timeout for navigation
    const pollInterval = 100;
    let waitTime = 0;

    while (!fs.existsSync(pageLoadedMarker) && waitTime < maxWait) {
        await new Promise(resolve => setTimeout(resolve, pollInterval));
        waitTime += pollInterval;
    }

    if (!fs.existsSync(pageLoadedMarker)) {
        throw new Error('Timeout waiting for navigation (chrome_navigate did not complete)');
    }

    // Wait a bit longer for any post-load DNS resolutions
    await new Promise(resolve => setTimeout(resolve, 500));
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__22_dns.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    if (!getEnvBool('DNS_ENABLED', true)) {
        console.error('Skipping (DNS_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'DNS_ENABLED=False'}));
        process.exit(0);
    }

    const startTs = new Date();

    try {
        // Set up listener BEFORE navigation
        await setupListener(url);

        // Note: PID file is written by run_hook() with hook-specific name
        // Snapshot.cleanup() kills all *.pid processes when done

        // Wait for chrome_navigate to complete (BLOCKING)
        await waitForNavigation();

        // Count DNS records
        const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
        let recordCount = 0;
        if (fs.existsSync(outputPath)) {
            const content = fs.readFileSync(outputPath, 'utf8');
            recordCount = content.split('\n').filter(line => line.trim()).length;
        }

        // Report success
        const endTs = new Date();

        // Output clean JSONL (no RESULT_JSON= prefix)
        console.log(JSON.stringify({
            type: 'ArchiveResult',
            status: 'succeeded',
            output_str: `${OUTPUT_FILE} (${recordCount} DNS records)`,
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
