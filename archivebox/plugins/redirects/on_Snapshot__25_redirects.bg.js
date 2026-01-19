#!/usr/bin/env node
/**
 * Capture redirect chain using CDP during page navigation.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate to capture the
 * redirect chain from the initial request. It stays alive through navigation
 * and emits JSONL on SIGTERM.
 *
 * Usage: on_Snapshot__25_redirects.bg.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes redirects.jsonl
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

const PLUGIN_NAME = 'redirects';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'redirects.jsonl';
const CHROME_SESSION_DIR = '../chrome';

// Global state
let redirectChain = [];
let originalUrl = '';
let finalUrl = '';
let page = null;
let browser = null;

async function setupRedirectListener() {
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
    const timeout = getEnvInt('REDIRECTS_TIMEOUT', 30) * 1000;

    fs.writeFileSync(outputPath, ''); // Clear existing

    // Connect to Chrome page using shared utility
    const connection = await connectToPage({
        chromeSessionDir: CHROME_SESSION_DIR,
        timeoutMs: timeout,
        puppeteer,
    });
    browser = connection.browser;
    page = connection.page;

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
        console.error('Usage: on_Snapshot__25_redirects.bg.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    originalUrl = url;

    if (!getEnvBool('REDIRECTS_ENABLED', true)) {
        console.error('Skipping (REDIRECTS_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'REDIRECTS_ENABLED=False'}));
        process.exit(0);
    }

    const timeout = getEnvInt('REDIRECTS_TIMEOUT', 30) * 1000;

    // Register signal handlers for graceful shutdown
    process.on('SIGTERM', () => handleShutdown('SIGTERM'));
    process.on('SIGINT', () => handleShutdown('SIGINT'));

    try {
        // Set up redirect listener BEFORE navigation
        await setupRedirectListener();

        // Wait for chrome_navigate to complete (non-fatal)
        try {
            await waitForPageLoaded(CHROME_SESSION_DIR, timeout * 4, 1000);
        } catch (e) {
            console.error(`WARN: ${e.message}`);
        }

        // Keep process alive until killed by cleanup
        // console.error('Redirect tracking complete, waiting for cleanup signal...');

        // Keep the process alive indefinitely
        await new Promise(() => {}); // Never resolves

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
