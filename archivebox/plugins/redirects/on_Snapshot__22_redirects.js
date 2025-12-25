#!/usr/bin/env node
/**
 * Track complete redirect chains for a URL.
 *
 * Captures:
 * - HTTP redirects (301, 302, 303, 307, 308)
 * - Meta refresh redirects
 * - JavaScript redirects (basic detection)
 * - Full redirect chain with timestamps
 *
 * Usage: on_Snapshot__15_redirects.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes redirects/redirects.json
 *
 * Environment variables:
 *     SAVE_REDIRECTS: Enable redirect tracking (default: true)
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

// Extractor metadata
const EXTRACTOR_NAME = 'redirects';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'redirects.json';
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

// Track redirect chain
async function trackRedirects(url) {
    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    let browser = null;
    const redirectChain = [];

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

        // Track all responses to capture redirects
        page.on('response', async (response) => {
            const status = response.status();
            const responseUrl = response.url();
            const headers = response.headers();

            // Check if it's a redirect
            if (status >= 300 && status < 400) {
                redirectChain.push({
                    timestamp: new Date().toISOString(),
                    url: responseUrl,
                    status,
                    statusText: response.statusText(),
                    location: headers['location'] || headers['Location'] || '',
                    type: 'http',
                });
            }
        });

        // Get the current URL (which is the final destination after redirects)
        const finalUrl = page.url();

        // Check for meta refresh redirects
        const metaRefresh = await page.evaluate(() => {
            const meta = document.querySelector('meta[http-equiv="refresh"]');
            if (meta) {
                const content = meta.getAttribute('content') || '';
                const match = content.match(/url=['"]?([^'"]+)['"]?/i);
                return {
                    content,
                    url: match ? match[1] : null,
                };
            }
            return null;
        });

        if (metaRefresh && metaRefresh.url) {
            redirectChain.push({
                timestamp: new Date().toISOString(),
                url: finalUrl,
                status: null,
                statusText: 'Meta Refresh',
                location: metaRefresh.url,
                type: 'meta_refresh',
                content: metaRefresh.content,
            });
        }

        // Check for JavaScript redirects (basic detection)
        const jsRedirect = await page.evaluate(() => {
            // Check for common JavaScript redirect patterns
            const html = document.documentElement.outerHTML;
            const patterns = [
                /window\.location\s*=\s*['"]([^'"]+)['"]/i,
                /window\.location\.href\s*=\s*['"]([^'"]+)['"]/i,
                /window\.location\.replace\s*\(\s*['"]([^'"]+)['"]\s*\)/i,
                /document\.location\s*=\s*['"]([^'"]+)['"]/i,
            ];

            for (const pattern of patterns) {
                const match = html.match(pattern);
                if (match) {
                    return {
                        pattern: pattern.toString(),
                        url: match[1],
                    };
                }
            }
            return null;
        });

        if (jsRedirect && jsRedirect.url) {
            redirectChain.push({
                timestamp: new Date().toISOString(),
                url: finalUrl,
                status: null,
                statusText: 'JavaScript Redirect',
                location: jsRedirect.url,
                type: 'javascript',
                pattern: jsRedirect.pattern,
            });
        }

        const redirectData = {
            original_url: url,
            final_url: finalUrl,
            redirect_count: redirectChain.length,
            redirects: redirectChain,
            is_redirect: redirectChain.length > 0,
        };

        // Write output
        fs.writeFileSync(outputPath, JSON.stringify(redirectData, null, 2));

        return { success: true, output: outputPath, redirectData };

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
        console.error('Usage: on_Snapshot__15_redirects.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    try {
        // Check if enabled
        if (!getEnvBool('SAVE_REDIRECTS', true)) {
            console.log('Skipping redirects (SAVE_REDIRECTS=False)');
            status = 'skipped';
            const endTs = new Date();
            console.log(`START_TS=${startTs.toISOString()}`);
            console.log(`END_TS=${endTs.toISOString()}`);
            console.log(`STATUS=${status}`);
            console.log(`RESULT_JSON=${JSON.stringify({extractor: EXTRACTOR_NAME, status, url, snapshot_id: snapshotId})}`);
            process.exit(0);
        }

        const result = await trackRedirects(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            const redirectCount = result.redirectData.redirect_count;
            const finalUrl = result.redirectData.final_url;
            if (redirectCount > 0) {
                console.log(`Tracked ${redirectCount} redirect(s) to: ${finalUrl}`);
            } else {
                console.log('No redirects detected');
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
