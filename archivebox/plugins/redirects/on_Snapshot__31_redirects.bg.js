#!/usr/bin/env node
/**
 * Capture redirect chain using CDP during page navigation.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate to capture the
 * redirect chain from the initial request. It stays alive through navigation
 * and emits JSONL on SIGTERM.
 *
 * Usage: on_Snapshot__25_chrome_redirects.bg.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes redirects.jsonl + hook.pid
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

const PLUGIN_NAME = 'redirects';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'redirects.jsonl';
const PID_FILE = 'hook.pid';
const CHROME_SESSION_DIR = '../chrome';

// Global state
let redirectChain = [];
let originalUrl = '';
let finalUrl = '';
let page = null;
let browser = null;

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

async function waitForChromeTabOpen(timeoutMs = 60000) {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    const targetIdFile = path.join(CHROME_SESSION_DIR, 'target_id.txt');
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        if (fs.existsSync(cdpFile) && fs.existsSync(targetIdFile)) {
            return true;
        }
        // Wait 100ms before checking again
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

async function setupRedirectListener() {
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
    fs.writeFileSync(outputPath, ''); // Clear existing

    // Wait for chrome tab to be open (up to 60s)
    const tabOpen = await waitForChromeTabOpen(60000);
    if (!tabOpen) {
        throw new Error('Chrome tab not open after 60s (chrome plugin must run first)');
    }

    const cdpUrl = getCdpUrl();
    if (!cdpUrl) {
        throw new Error('No Chrome session found');
    }

    browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

    // Find our page
    const pages = await browser.pages();
    const targetId = getPageId();

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

    // Enable CDP Network domain to capture redirects
    const client = await page.target().createCDPSession();
    await client.send('Network.enable');

    // Track redirect chain using CDP
    client.on('Network.requestWillBeSent', (params) => {
        const { requestId, request, redirectResponse } = params;

        if (redirectResponse) {
            // This is a redirect
            const redirectEntry = {
                timestamp: new Date().toISOString(),
                from_url: redirectResponse.url,
                to_url: request.url,
                status: redirectResponse.status,
                type: 'http',
                request_id: requestId,
            };
            redirectChain.push(redirectEntry);
            fs.appendFileSync(outputPath, JSON.stringify(redirectEntry) + '\n');
        }

        // Update final URL
        if (request.url && request.url.startsWith('http')) {
            finalUrl = request.url;
        }
    });

    // After page loads, check for meta refresh and JS redirects
    page.on('load', async () => {
        try {
            // Small delay to let page settle
            await new Promise(resolve => setTimeout(resolve, 500));

            // Check for meta refresh
            const metaRefresh = await page.evaluate(() => {
                const meta = document.querySelector('meta[http-equiv="refresh"]');
                if (meta) {
                    const content = meta.getAttribute('content') || '';
                    const match = content.match(/url=['"]?([^'";\s]+)['"]?/i);
                    return { content, url: match ? match[1] : null };
                }
                return null;
            });

            if (metaRefresh && metaRefresh.url) {
                const entry = {
                    timestamp: new Date().toISOString(),
                    from_url: page.url(),
                    to_url: metaRefresh.url,
                    type: 'meta_refresh',
                    content: metaRefresh.content,
                };
                redirectChain.push(entry);
                fs.appendFileSync(outputPath, JSON.stringify(entry) + '\n');
            }

            // Check for JS redirects
            const jsRedirect = await page.evaluate(() => {
                const html = document.documentElement.outerHTML;
                const patterns = [
                    /window\.location\s*=\s*['"]([^'"]+)['"]/i,
                    /window\.location\.href\s*=\s*['"]([^'"]+)['"]/i,
                    /window\.location\.replace\s*\(\s*['"]([^'"]+)['"]\s*\)/i,
                ];
                for (const pattern of patterns) {
                    const match = html.match(pattern);
                    if (match) return { url: match[1], pattern: pattern.toString() };
                }
                return null;
            });

            if (jsRedirect && jsRedirect.url) {
                const entry = {
                    timestamp: new Date().toISOString(),
                    from_url: page.url(),
                    to_url: jsRedirect.url,
                    type: 'javascript',
                };
                redirectChain.push(entry);
                fs.appendFileSync(outputPath, JSON.stringify(entry) + '\n');
            }
        } catch (e) {
            // Ignore errors during meta/js redirect detection
        }
    });

    return { browser, page };
}

async function waitForNavigation() {
    // Wait for chrome_navigate to complete
    const navDir = '../chrome';
    const pageLoadedMarker = path.join(navDir, 'page_loaded.txt');
    const maxWait = 120000; // 2 minutes
    const pollInterval = 100;
    let waitTime = 0;

    while (!fs.existsSync(pageLoadedMarker) && waitTime < maxWait) {
        await new Promise(resolve => setTimeout(resolve, pollInterval));
        waitTime += pollInterval;
    }

    if (!fs.existsSync(pageLoadedMarker)) {
        throw new Error('Timeout waiting for navigation (chrome_navigate did not complete)');
    }

    // Wait a bit longer for any post-load analysis
    await new Promise(resolve => setTimeout(resolve, 1000));
}

function handleShutdown(signal) {
    console.error(`\nReceived ${signal}, emitting final results...`);

    // Emit final JSONL result to stdout
    const result = {
        type: 'ArchiveResult',
        status: 'succeeded',
        output_str: OUTPUT_FILE,
        plugin: PLUGIN_NAME,
        original_url: originalUrl,
        final_url: finalUrl || originalUrl,
        redirect_count: redirectChain.length,
        is_redirect: redirectChain.length > 0 || (finalUrl && finalUrl !== originalUrl),
    };

    console.log(JSON.stringify(result));
    process.exit(0);
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__25_chrome_redirects.bg.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    originalUrl = url;

    if (!getEnvBool('REDIRECTS_ENABLED', true)) {
        console.error('Skipping (REDIRECTS_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'REDIRECTS_ENABLED=False'}));
        process.exit(0);
    }

    // Register signal handlers for graceful shutdown
    process.on('SIGTERM', () => handleShutdown('SIGTERM'));
    process.on('SIGINT', () => handleShutdown('SIGINT'));

    try {
        // Set up redirect listener BEFORE navigation
        await setupRedirectListener();

        // Write PID file
        fs.writeFileSync(path.join(OUTPUT_DIR, PID_FILE), String(process.pid));

        // Wait for chrome_navigate to complete (BLOCKING)
        await waitForNavigation();

        // Keep process alive until killed by cleanup
        console.error('Redirect tracking complete, waiting for cleanup signal...');

        // Keep the process alive indefinitely
        await new Promise(() => {}); // Never resolves

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
