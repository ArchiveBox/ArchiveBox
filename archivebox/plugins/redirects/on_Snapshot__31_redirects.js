#!/usr/bin/env node
/**
 * Detect redirects by comparing original URL to final URL.
 *
 * This runs AFTER chrome_navigate and checks:
 * - URL changed (HTTP redirect occurred)
 * - Meta refresh tags (pending redirects)
 * - JavaScript redirects (basic detection)
 *
 * Usage: on_Snapshot__31_redirects.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes redirects.json
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const EXTRACTOR_NAME = 'redirects';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'redirects.json';
const CHROME_SESSION_DIR = '../chrome_session';
const CHROME_NAVIGATE_DIR = '../chrome_navigate';

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

function getFinalUrl() {
    // Try chrome_navigate output first
    const navFile = path.join(CHROME_NAVIGATE_DIR, 'final_url.txt');
    if (fs.existsSync(navFile)) {
        return fs.readFileSync(navFile, 'utf8').trim();
    }
    return null;
}

async function detectRedirects(originalUrl) {
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
    const redirects = [];

    // Get final URL from chrome_navigate
    let finalUrl = getFinalUrl() || originalUrl;

    // Check if URL changed (indicates redirect)
    const urlChanged = originalUrl !== finalUrl;
    if (urlChanged) {
        redirects.push({
            timestamp: new Date().toISOString(),
            from_url: originalUrl,
            to_url: finalUrl,
            type: 'http',
            detected_by: 'url_comparison',
        });
    }

    // Connect to Chrome to check for meta refresh and JS redirects
    const cdpUrl = getCdpUrl();
    if (cdpUrl) {
        let browser = null;
        try {
            browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

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
                page = pages.find(p => p.url().startsWith('http')) || pages[pages.length - 1];
            }

            if (page) {
                // Update finalUrl from actual page
                const pageUrl = page.url();
                if (pageUrl && pageUrl !== 'about:blank') {
                    finalUrl = pageUrl;
                }

                // Check for meta refresh
                try {
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
                        redirects.push({
                            timestamp: new Date().toISOString(),
                            from_url: finalUrl,
                            to_url: metaRefresh.url,
                            type: 'meta_refresh',
                            content: metaRefresh.content,
                        });
                    }
                } catch (e) { /* ignore */ }

                // Check for JS redirects
                try {
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
                        redirects.push({
                            timestamp: new Date().toISOString(),
                            from_url: finalUrl,
                            to_url: jsRedirect.url,
                            type: 'javascript',
                        });
                    }
                } catch (e) { /* ignore */ }
            }

            browser.disconnect();
        } catch (e) {
            console.error(`Warning: Could not connect to Chrome: ${e.message}`);
        }
    }

    const result = {
        original_url: originalUrl,
        final_url: finalUrl,
        redirect_count: redirects.length,
        redirects,
        is_redirect: originalUrl !== finalUrl || redirects.length > 0,
    };

    fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
    return { success: true, output: outputPath, data: result };
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__31_redirects.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    if (!getEnvBool('SAVE_REDIRECTS', true)) {
        console.log('Skipping redirects (SAVE_REDIRECTS=False)');
        status = 'skipped';
    } else {
        try {
            const result = await detectRedirects(url);
            status = 'succeeded';
            output = result.output;

            if (result.data.is_redirect) {
                console.log(`Redirect detected: ${url} -> ${result.data.final_url}`);
            } else {
                console.log('No redirects detected');
            }
        } catch (e) {
            error = `${e.name}: ${e.message}`;
        }
    }

    const endTs = new Date();

    if (error) console.error(`ERROR: ${error}`);

    // Output clean JSONL (no RESULT_JSON= prefix)
    console.log(JSON.stringify({
        type: 'ArchiveResult',
        status,
        output_str: output || error || '',
    }));

    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
