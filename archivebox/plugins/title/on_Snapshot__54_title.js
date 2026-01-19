#!/usr/bin/env node
/**
 * Extract the title of a URL.
 *
 * If a Chrome session exists (from chrome plugin), connects to it via CDP
 * to get the page title (which includes JS-rendered content).
 * Otherwise falls back to fetching the URL and parsing HTML.
 *
 * Usage: on_Snapshot__10_title.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes title/title.txt
 *
 * Environment variables:
 *     TIMEOUT: Timeout in seconds (default: 30)
 *     USER_AGENT: User agent string (optional)
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

// Extractor metadata
const PLUGIN_NAME = 'title';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'title.txt';
const CHROME_SESSION_DIR = '../chrome';

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

function getEnvInt(name, defaultValue = 0) {
    const val = parseInt(getEnv(name, String(defaultValue)), 10);
    return isNaN(val) ? defaultValue : val;
}

// Wait for chrome tab to be fully loaded
async function waitForChromeTabLoaded(timeoutMs = 60000) {
    const navigationFile = path.join(CHROME_SESSION_DIR, 'navigation.json');
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        if (fs.existsSync(navigationFile)) {
            return true;
        }
        // Wait 100ms before checking again
        await new Promise(resolve => setTimeout(resolve, 100));
    }

    return false;
}

// Get CDP URL from chrome plugin if available
function getCdpUrl() {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    if (fs.existsSync(cdpFile)) {
        return fs.readFileSync(cdpFile, 'utf8').trim();
    }
    return null;
}

// Extract title from HTML
function extractTitleFromHtml(html) {
    // Try <title> tag
    const titleMatch = html.match(/<title[^>]*>([^<]+)<\/title>/i);
    if (titleMatch) {
        return titleMatch[1].trim();
    }

    // Try og:title
    const ogMatch = html.match(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']/i);
    if (ogMatch) {
        return ogMatch[1].trim();
    }

    // Try twitter:title
    const twitterMatch = html.match(/<meta[^>]+name=["']twitter:title["'][^>]+content=["']([^"']+)["']/i);
    if (twitterMatch) {
        return twitterMatch[1].trim();
    }

    return null;
}

// Fetch URL and extract title (fallback method)
function fetchTitle(url) {
    return new Promise((resolve, reject) => {
        const timeout = getEnvInt('TIMEOUT', 30) * 1000;
        const userAgent = getEnv('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)');

        const client = url.startsWith('https') ? https : http;

        const req = client.get(url, {
            headers: { 'User-Agent': userAgent },
            timeout,
        }, (res) => {
            // Handle redirects
            if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
                fetchTitle(res.headers.location).then(resolve).catch(reject);
                return;
            }

            let data = '';
            res.on('data', chunk => {
                data += chunk;
                // Only need first 64KB to find title
                if (data.length > 65536) {
                    req.destroy();
                }
            });
            res.on('end', () => {
                const title = extractTitleFromHtml(data);
                if (title) {
                    resolve(title);
                } else {
                    reject(new Error('No title found in HTML'));
                }
            });
        });

        req.on('error', reject);
        req.on('timeout', () => {
            req.destroy();
            reject(new Error('Request timeout'));
        });
    });
}

// Get title using Puppeteer CDP connection
async function getTitleFromCdp(cdpUrl) {
    // Wait for page to be fully loaded
    const pageLoaded = await waitForChromeTabLoaded(60000);
    if (!pageLoaded) {
        throw new Error('Page not loaded after 60s (chrome_navigate must complete first)');
    }

    const puppeteer = require('puppeteer-core');

    const browser = await puppeteer.connect({
        browserWSEndpoint: cdpUrl,
    });

    try {
        // Get existing pages
        const pages = await browser.pages();
        const page = pages.find(p => p.url().startsWith('http')) || pages[0];

        if (!page) {
            throw new Error('No page found in Chrome session');
        }

        // Get title from page
        const title = await page.title();

        if (!title) {
            // Try getting from DOM directly
            const domTitle = await page.evaluate(() => {
                return document.title ||
                       document.querySelector('meta[property="og:title"]')?.content ||
                       document.querySelector('meta[name="twitter:title"]')?.content ||
                       document.querySelector('h1')?.textContent?.trim();
            });
            return domTitle;
        }

        return title;
    } finally {
        // Disconnect without closing browser
        browser.disconnect();
    }
}

async function extractTitle(url) {
    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    // Try Chrome session first
    const cdpUrl = getCdpUrl();
    if (cdpUrl) {
        try {
            const title = await getTitleFromCdp(cdpUrl);
            if (title) {
                fs.writeFileSync(outputPath, title, 'utf8');
                return { success: true, output: outputPath, title, method: 'cdp' };
            }
        } catch (e) {
            console.error(`CDP title extraction failed: ${e.message}, falling back to HTTP`);
        }
    }

    // Fallback to HTTP fetch
    try {
        const title = await fetchTitle(url);
        fs.writeFileSync(outputPath, title, 'utf8');
        return { success: true, output: outputPath, title, method: 'http' };
    } catch (e) {
        return { success: false, error: e.message };
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__10_title.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';
    let extractedTitle = null;

    try {
        const result = await extractTitle(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            extractedTitle = result.title;
            console.error(`Title extracted (${result.method}): ${result.title}`);
        } else {
            status = 'failed';
            error = result.error;
        }
    } catch (e) {
        error = `${e.name}: ${e.message}`;
        status = 'failed';
    }

    const endTs = new Date();

    if (error) {
        console.error(`ERROR: ${error}`);
    }

    // Update snapshot title via JSONL
    if (status === 'succeeded' && extractedTitle) {
        console.log(JSON.stringify({
            type: 'Snapshot',
            id: snapshotId,
            title: extractedTitle
        }));
    }

    // Output ArchiveResult JSONL
    const archiveResult = {
        type: 'ArchiveResult',
        status,
        output_str: output || error || '',
    };
    console.log(JSON.stringify(archiveResult));

    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
