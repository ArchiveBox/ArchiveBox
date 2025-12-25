#!/usr/bin/env node
/**
 * Extract SSL/TLS certificate details from a URL.
 *
 * Connects to Chrome session and retrieves security details including:
 * - Protocol (TLS 1.2, TLS 1.3, etc.)
 * - Cipher suite
 * - Certificate issuer, validity period
 * - Security state
 *
 * Usage: on_Snapshot__16_ssl.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes ssl/ssl.json
 *
 * Environment variables:
 *     SAVE_SSL: Enable SSL extraction (default: true)
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

// Extractor metadata
const EXTRACTOR_NAME = 'ssl';
const OUTPUT_DIR = 'ssl';
const OUTPUT_FILE = 'ssl.json';
const CHROME_SESSION_DIR = 'chrome_session';

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

// Extract SSL details
async function extractSsl(url) {
    // Create output directory
    if (!fs.existsSync(OUTPUT_DIR)) {
        fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    }
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    // Only extract SSL for HTTPS URLs
    if (!url.startsWith('https://')) {
        return { success: false, error: 'URL is not HTTPS' };
    }

    let browser = null;
    let sslInfo = {};

    try {
        // Connect to existing Chrome session
        const cdpUrl = getCdpUrl();
        if (!cdpUrl) {
            return { success: false, error: 'No Chrome session found (chrome_session extractor must run first)' };
        }

        browser = await puppeteer.connect({
            browserWSEndpoint: cdpUrl,
        });

        // Get the page
        const pages = await browser.pages();
        const page = pages.find(p => p.url().startsWith('http')) || pages[0];

        if (!page) {
            return { success: false, error: 'No page found in Chrome session' };
        }

        // Get CDP client for low-level access
        const client = await page.target().createCDPSession();

        // Enable Security domain
        await client.send('Security.enable');

        // Get security details from the loaded page
        const securityState = await client.send('Security.getSecurityState');

        sslInfo = {
            url,
            securityState: securityState.securityState,
            schemeIsCryptographic: securityState.schemeIsCryptographic,
            summary: securityState.summary || '',
        };

        // Try to get detailed certificate info if available
        if (securityState.securityStateIssueIds && securityState.securityStateIssueIds.length > 0) {
            sslInfo.issues = securityState.securityStateIssueIds;
        }

        // Get response security details from navigation
        let mainResponse = null;
        page.on('response', async (response) => {
            if (response.url() === url || response.request().isNavigationRequest()) {
                mainResponse = response;
            }
        });

        // If we have security details from response
        if (mainResponse) {
            try {
                const securityDetails = await mainResponse.securityDetails();
                if (securityDetails) {
                    sslInfo.protocol = securityDetails.protocol();
                    sslInfo.subjectName = securityDetails.subjectName();
                    sslInfo.issuer = securityDetails.issuer();
                    sslInfo.validFrom = securityDetails.validFrom();
                    sslInfo.validTo = securityDetails.validTo();
                    sslInfo.certificateId = securityDetails.subjectName();

                    const sanList = securityDetails.sanList();
                    if (sanList && sanList.length > 0) {
                        sslInfo.subjectAlternativeNames = sanList;
                    }
                }
            } catch (e) {
                // Security details not available
            }
        }

        await client.detach();

        // Write output
        fs.writeFileSync(outputPath, JSON.stringify(sslInfo, null, 2));

        return { success: true, output: outputPath, sslInfo };

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
        console.error('Usage: on_Snapshot__16_ssl.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    try {
        // Check if enabled
        if (!getEnvBool('SAVE_SSL', true)) {
            console.log('Skipping SSL (SAVE_SSL=False)');
            status = 'skipped';
            const endTs = new Date();
            console.log(`START_TS=${startTs.toISOString()}`);
            console.log(`END_TS=${endTs.toISOString()}`);
            console.log(`STATUS=${status}`);
            console.log(`RESULT_JSON=${JSON.stringify({extractor: EXTRACTOR_NAME, status, url, snapshot_id: snapshotId})}`);
            process.exit(0);
        }

        const result = await extractSsl(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            const protocol = result.sslInfo?.protocol || 'unknown';
            console.log(`SSL details extracted: ${protocol}`);
        } else {
            status = 'failed';
            error = result.error;
        }
    } catch (e) {
        error = `${e.name}: ${e.message}`;
        status = 'failed';
    }

    const endTs = new Date();
    const duration = (endTs - startTs) / 1000;

    // Print results
    console.log(`START_TS=${startTs.toISOString()}`);
    console.log(`END_TS=${endTs.toISOString()}`);
    console.log(`DURATION=${duration.toFixed(2)}`);
    if (output) {
        console.log(`OUTPUT=${output}`);
    }
    console.log(`STATUS=${status}`);

    if (error) {
        console.error(`ERROR=${error}`);
    }

    // Print JSON result
    const resultJson = {
        extractor: EXTRACTOR_NAME,
        url,
        snapshot_id: snapshotId,
        status,
        start_ts: startTs.toISOString(),
        end_ts: endTs.toISOString(),
        duration: Math.round(duration * 100) / 100,
        output,
        error: error || null,
    };
    console.log(`RESULT_JSON=${JSON.stringify(resultJson)}`);

    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
