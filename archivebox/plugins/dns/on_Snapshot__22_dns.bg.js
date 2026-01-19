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
const {
    getEnvBool,
    getEnvInt,
    parseArgs,
    connectToPage,
    waitForPageLoaded,
} = require('../chrome/chrome_utils.js');

const PLUGIN_NAME = 'dns';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'dns.jsonl';
const CHROME_SESSION_DIR = '../chrome';

let browser = null;
let page = null;
let recordCount = 0;
let shuttingDown = false;

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

    // Connect to Chrome page using shared utility
    const { browser, page } = await connectToPage({
        chromeSessionDir: CHROME_SESSION_DIR,
        timeoutMs: timeout,
        puppeteer,
    });

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
            recordCount += 1;

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

                // Create a unique key for this failed resolution
                const resolutionKey = `${hostname}:NXDOMAIN`;

                // Skip if we've already recorded this NXDOMAIN
                if (seenResolutions.has(resolutionKey)) {
                    return;
                }
                seenResolutions.set(resolutionKey, true);

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
                recordCount += 1;
            }
        } catch (e) {
            // Ignore errors
        }
    });

    return { browser, page, client };
}

function emitResult(status = 'succeeded') {
    if (shuttingDown) return;
    shuttingDown = true;

    console.log(JSON.stringify({
        type: 'ArchiveResult',
        status,
        output_str: `${OUTPUT_FILE} (${recordCount} DNS records)`,
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
        console.error('Usage: on_Snapshot__22_dns.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    if (!getEnvBool('DNS_ENABLED', true)) {
        console.error('Skipping (DNS_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'DNS_ENABLED=False'}));
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
            const timeout = getEnvInt('DNS_TIMEOUT', 30) * 1000;
            await waitForPageLoaded(CHROME_SESSION_DIR, timeout * 4, 500);
        } catch (e) {
            console.error(`WARN: ${e.message}`);
        }

        // console.error('DNS listener active, waiting for cleanup signal...');
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
