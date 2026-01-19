#!/usr/bin/env node
/**
 * Extract and categorize outgoing links from a page's DOM.
 *
 * Categorizes links by type:
 * - hrefs: All <a> links
 * - images: <img src>
 * - css_stylesheets: <link rel=stylesheet>
 * - css_images: CSS background-image: url()
 * - js_scripts: <script src>
 * - iframes: <iframe src>
 * - links: <link> tags with rel/href
 *
 * Usage: on_Snapshot__75_parse_dom_outlinks.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes parse_dom_outlinks/outlinks.json and parse_dom_outlinks/urls.jsonl
 *
 * Environment variables:
 *     PARSE_DOM_OUTLINKS_ENABLED: Enable DOM outlinks extraction (default: true)
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

// Extractor metadata
const PLUGIN_NAME = 'parse_dom_outlinks';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'outlinks.json';
const URLS_FILE = 'urls.jsonl';  // For crawl system
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

function getEnvBool(name, defaultValue = false) {
    const val = getEnv(name, '').toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(val)) return true;
    if (['false', '0', 'no', 'off'].includes(val)) return false;
    return defaultValue;
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

// Get CDP URL from chrome plugin
function getCdpUrl() {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    if (fs.existsSync(cdpFile)) {
        return fs.readFileSync(cdpFile, 'utf8').trim();
    }
    return null;
}

// Extract outlinks
async function extractOutlinks(url) {
    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    let browser = null;

    try {
        // Connect to existing Chrome session
        const cdpUrl = getCdpUrl();
        if (!cdpUrl) {
            return { success: false, error: 'No Chrome session found (chrome plugin must run first)' };
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

        // Extract outlinks by category
        const outlinksData = await page.evaluate(() => {
            const LINK_REGEX = /https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)/gi;

            const filterDataUrls = (urls) => urls.filter(url => url && !url.startsWith('data:'));
            const filterW3Urls = (urls) => urls.filter(url => url && !url.startsWith('http://www.w3.org/'));

            // Get raw links from HTML
            const html = document.documentElement.outerHTML;
            const raw = Array.from(html.matchAll(LINK_REGEX)).map(m => m[0]);

            // Get all <a href> links
            const hrefs = Array.from(document.querySelectorAll('a[href]'))
                .map(elem => elem.href)
                .filter(url => url);

            // Get all <link> tags (not just stylesheets)
            const linksMap = {};
            document.querySelectorAll('link[href]').forEach(elem => {
                const rel = elem.rel || '';
                const href = elem.href;
                if (href && rel !== 'stylesheet') {
                    linksMap[href] = { rel, href };
                }
            });
            const links = Object.values(linksMap);

            // Get iframes
            const iframes = Array.from(document.querySelectorAll('iframe[src]'))
                .map(elem => elem.src)
                .filter(url => url);

            // Get images
            const images = Array.from(document.querySelectorAll('img[src]'))
                .map(elem => elem.src)
                .filter(url => url && !url.startsWith('data:'));

            // Get CSS background images
            const css_images = Array.from(document.querySelectorAll('*'))
                .map(elem => {
                    const bgImg = window.getComputedStyle(elem).getPropertyValue('background-image');
                    const match = /url\(\s*?['"]?\s*?(\S+?)\s*?["']?\s*?\)/i.exec(bgImg);
                    return match ? match[1] : null;
                })
                .filter(url => url);

            // Get stylesheets
            const css_stylesheets = Array.from(document.querySelectorAll('link[rel=stylesheet]'))
                .map(elem => elem.href)
                .filter(url => url);

            // Get JS scripts
            const js_scripts = Array.from(document.querySelectorAll('script[src]'))
                .map(elem => elem.src)
                .filter(url => url);

            return {
                url: window.location.href,
                raw: [...new Set(filterDataUrls(filterW3Urls(raw)))],
                hrefs: [...new Set(filterDataUrls(hrefs))],
                links,
                iframes: [...new Set(iframes)],
                images: [...new Set(filterDataUrls(images))],
                css_images: [...new Set(filterDataUrls(css_images))],
                css_stylesheets: [...new Set(filterDataUrls(css_stylesheets))],
                js_scripts: [...new Set(filterDataUrls(js_scripts))],
            };
        });

        // Write detailed output (for archival)
        fs.writeFileSync(outputPath, JSON.stringify(outlinksData, null, 2));

        // Write urls.jsonl for crawl system (only hrefs that are crawlable pages)
        const urlsPath = path.join(OUTPUT_DIR, URLS_FILE);
        const crawlableUrls = outlinksData.hrefs.filter(href => {
            // Only include http/https URLs, exclude static assets
            if (!href.startsWith('http://') && !href.startsWith('https://')) return false;
            // Exclude common static file extensions
            const staticExts = ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.eot', '.mp4', '.webm', '.mp3', '.pdf'];
            const urlPath = href.split('?')[0].split('#')[0].toLowerCase();
            return !staticExts.some(ext => urlPath.endsWith(ext));
        });

        const urlsJsonl = crawlableUrls.map(href => JSON.stringify({
            type: 'Snapshot',
            url: href,
            plugin: PLUGIN_NAME,
            depth: depth + 1,
            parent_snapshot_id: snapshotId || undefined,
            crawl_id: crawlId || undefined,
        })).join('\n');

        if (urlsJsonl) {
            fs.writeFileSync(urlsPath, urlsJsonl + '\n');
        }

        return { success: true, output: outputPath, outlinksData, crawlableCount: crawlableUrls.length };

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
    const crawlId = args.crawl_id || process.env.CRAWL_ID;
    const depth = parseInt(args.depth || process.env.SNAPSHOT_DEPTH || '0', 10) || 0;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__75_parse_dom_outlinks.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    try {
        // Check if enabled
        if (!getEnvBool('PARSE_DOM_OUTLINKS_ENABLED', true)) {
            console.log('Skipping DOM outlinks (PARSE_DOM_OUTLINKS_ENABLED=False)');
            // Output clean JSONL (no RESULT_JSON= prefix)
            console.log(JSON.stringify({
                type: 'ArchiveResult',
                status: 'skipped',
                output_str: 'PARSE_DOM_OUTLINKS_ENABLED=False',
            }));
            process.exit(0);
        }

        // Check if Chrome session exists, then wait for page load
        const cdpUrl = getCdpUrl();
        if (cdpUrl) {
            // Wait for page to be fully loaded
            const pageLoaded = await waitForChromeTabLoaded(60000);
            if (!pageLoaded) {
                throw new Error('Page not loaded after 60s (chrome_navigate must complete first)');
            }
        }

        const result = await extractOutlinks(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            const total = result.outlinksData.hrefs.length;
            const crawlable = result.crawlableCount;
            const images = result.outlinksData.images.length;
            const scripts = result.outlinksData.js_scripts.length;
            console.log(`DOM outlinks extracted: ${total} links (${crawlable} crawlable), ${images} images, ${scripts} scripts`);
        } else {
            status = 'failed';
            error = result.error;
        }
    } catch (e) {
        error = `${e.name}: ${e.message}`;
        status = 'failed';
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
