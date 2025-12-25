#!/usr/bin/env node
/**
 * Navigate the Chrome browser to the target URL.
 *
 * This extractor runs AFTER pre-load extractors (21-29) have registered their
 * CDP listeners. It connects to the existing Chrome session, navigates to the URL,
 * waits for page load, and captures response headers.
 *
 * Usage: on_Snapshot__30_chrome_navigate.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes to chrome_session/:
 *   - response_headers.json: HTTP response headers from main document
 *   - final_url.txt: Final URL after any redirects
 *   - page_loaded.txt: Marker file indicating navigation is complete
 *
 * Environment variables:
 *     CHROME_PAGELOAD_TIMEOUT: Timeout for page load in seconds (default: 60)
 *     CHROME_DELAY_AFTER_LOAD: Extra delay after load in seconds (default: 0)
 *     CHROME_WAIT_FOR: Wait condition (default: networkidle2)
 *         - domcontentloaded: DOM is ready, resources may still load
 *         - load: Page fully loaded including resources
 *         - networkidle0: No network activity for 500ms (strictest)
 *         - networkidle2: At most 2 network connections for 500ms
 *
 *     # Fallbacks
 *     TIMEOUT: Fallback timeout
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

// Extractor metadata
const EXTRACTOR_NAME = 'chrome_navigate';
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

function getEnvInt(name, defaultValue = 0) {
    const val = parseInt(getEnv(name, String(defaultValue)), 10);
    return isNaN(val) ? defaultValue : val;
}

function getEnvFloat(name, defaultValue = 0) {
    const val = parseFloat(getEnv(name, String(defaultValue)));
    return isNaN(val) ? defaultValue : val;
}

// Read CDP URL from chrome_session
function getCdpUrl() {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    if (!fs.existsSync(cdpFile)) {
        return null;
    }
    return fs.readFileSync(cdpFile, 'utf8').trim();
}

// Read URL from chrome_session (set by chrome_session extractor)
function getTargetUrl() {
    const urlFile = path.join(CHROME_SESSION_DIR, 'url.txt');
    if (!fs.existsSync(urlFile)) {
        return null;
    }
    return fs.readFileSync(urlFile, 'utf8').trim();
}

// Validate wait condition
function getWaitCondition() {
    const waitFor = getEnv('CHROME_WAIT_FOR', 'networkidle2').toLowerCase();
    const validConditions = ['domcontentloaded', 'load', 'networkidle0', 'networkidle2'];
    if (validConditions.includes(waitFor)) {
        return waitFor;
    }
    console.error(`Warning: Invalid CHROME_WAIT_FOR="${waitFor}", using networkidle2`);
    return 'networkidle2';
}

// Sleep helper
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function navigateToUrl(url, cdpUrl) {
    const timeout = (getEnvInt('CHROME_PAGELOAD_TIMEOUT') || getEnvInt('CHROME_TIMEOUT') || getEnvInt('TIMEOUT', 60)) * 1000;
    const delayAfterLoad = getEnvFloat('CHROME_DELAY_AFTER_LOAD', 0) * 1000;
    const waitUntil = getWaitCondition();

    let browser = null;
    let responseHeaders = {};
    let redirectChain = [];
    let finalUrl = url;

    try {
        // Connect to existing browser
        browser = await puppeteer.connect({
            browserWSEndpoint: cdpUrl,
        });

        // Get all pages and find our target page
        const pages = await browser.pages();
        if (pages.length === 0) {
            return { success: false, error: 'No pages found in browser' };
        }

        // Use the last created page (most likely the one chrome_session created)
        const page = pages[pages.length - 1];

        // Set up response interception to capture headers and redirects
        page.on('response', async (response) => {
            const request = response.request();

            // Track redirects
            if (response.status() >= 300 && response.status() < 400) {
                redirectChain.push({
                    url: response.url(),
                    status: response.status(),
                    location: response.headers()['location'] || null,
                });
            }

            // Capture headers from the main document request
            if (request.isNavigationRequest() && request.frame() === page.mainFrame()) {
                try {
                    responseHeaders = {
                        url: response.url(),
                        status: response.status(),
                        statusText: response.statusText(),
                        headers: response.headers(),
                    };
                    finalUrl = response.url();
                } catch (e) {
                    // Ignore errors capturing headers
                }
            }
        });

        // Navigate to URL and wait for load
        console.log(`Navigating to ${url} (wait: ${waitUntil}, timeout: ${timeout}ms)`);

        const response = await page.goto(url, {
            waitUntil,
            timeout,
        });

        // Capture final response if not already captured
        if (response && Object.keys(responseHeaders).length === 0) {
            responseHeaders = {
                url: response.url(),
                status: response.status(),
                statusText: response.statusText(),
                headers: response.headers(),
            };
            finalUrl = response.url();
        }

        // Apply optional delay after load
        if (delayAfterLoad > 0) {
            console.log(`Waiting ${delayAfterLoad}ms after load...`);
            await sleep(delayAfterLoad);
        }

        // Write response headers
        if (Object.keys(responseHeaders).length > 0) {
            // Add redirect chain to headers
            responseHeaders.redirect_chain = redirectChain;

            fs.writeFileSync(
                path.join(CHROME_SESSION_DIR, 'response_headers.json'),
                JSON.stringify(responseHeaders, null, 2)
            );
        }

        // Write final URL (after redirects)
        fs.writeFileSync(path.join(CHROME_SESSION_DIR, 'final_url.txt'), finalUrl);

        // Write marker file indicating page is loaded
        fs.writeFileSync(
            path.join(CHROME_SESSION_DIR, 'page_loaded.txt'),
            new Date().toISOString()
        );

        // Disconnect but leave browser running for post-load extractors
        browser.disconnect();

        return {
            success: true,
            output: CHROME_SESSION_DIR,
            finalUrl,
            status: responseHeaders.status,
            redirectCount: redirectChain.length,
        };

    } catch (e) {
        // Don't close browser on error - let cleanup handle it
        if (browser) {
            try {
                browser.disconnect();
            } catch (disconnectErr) {
                // Ignore
            }
        }
        return { success: false, error: `${e.name}: ${e.message}` };
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__30_chrome_navigate.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    try {
        // Check for chrome_session
        const cdpUrl = getCdpUrl();
        if (!cdpUrl) {
            console.error('ERROR: chrome_session not found (cdp_url.txt missing)');
            console.error('chrome_navigate requires chrome_session to run first');
            process.exit(1);
        }

        // Get URL from chrome_session or use provided URL
        const targetUrl = getTargetUrl() || url;

        const result = await navigateToUrl(targetUrl, cdpUrl);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            console.log(`Page loaded: ${result.finalUrl}`);
            console.log(`HTTP status: ${result.status}`);
            if (result.redirectCount > 0) {
                console.log(`Redirects: ${result.redirectCount}`);
            }
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
