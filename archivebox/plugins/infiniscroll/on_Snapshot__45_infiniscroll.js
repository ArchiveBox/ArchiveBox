#!/usr/bin/env node
/**
 * Scroll the page down to trigger infinite scroll / lazy loading.
 *
 * Scrolls down 1 page at a time, up to INFINISCROLL_SCROLL_LIMIT times,
 * ensuring at least INFINISCROLL_MIN_HEIGHT (default 16,000px) is reached.
 * Stops early if no new content loads after a scroll.
 *
 * Usage: on_Snapshot__45_infiniscroll.js --url=<url> --snapshot-id=<uuid>
 * Output: JSONL with scroll stats (no files created)
 *
 * Environment variables:
 *     INFINISCROLL_ENABLED: Enable/disable (default: true)
 *     INFINISCROLL_TIMEOUT: Max timeout in seconds (default: 120)
 *     INFINISCROLL_SCROLL_DELAY: Delay between scrolls in ms (default: 2000)
 *     INFINISCROLL_SCROLL_DISTANCE: Pixels per scroll (default: 1600)
 *     INFINISCROLL_SCROLL_LIMIT: Max scroll iterations (default: 10)
 *     INFINISCROLL_MIN_HEIGHT: Min page height to reach in px (default: 16000)
 */

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

// Check if infiniscroll is enabled BEFORE requiring puppeteer
if (!getEnvBool('INFINISCROLL_ENABLED', true)) {
    console.error('Skipping infiniscroll (INFINISCROLL_ENABLED=False)');
    process.exit(0);
}

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const PLUGIN_NAME = 'infiniscroll';
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

async function waitForChromeTabLoaded(timeoutMs = 60000) {
    const navigationFile = path.join(CHROME_SESSION_DIR, 'navigation.json');
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        if (fs.existsSync(navigationFile)) {
            return true;
        }
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    return false;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function scrollDown(page, options = {}) {
    const {
        timeout = 120000,
        scrollDelay = 2000,
        scrollDistance = 1600,
        scrollLimit = 10,
        minHeight = 16000,
    } = options;

    const startTime = Date.now();

    // Get page height using multiple methods (some pages use different scroll containers)
    const getPageHeight = () => page.evaluate(() => {
        return Math.max(
            document.body.scrollHeight || 0,
            document.body.offsetHeight || 0,
            document.documentElement.scrollHeight || 0,
            document.documentElement.offsetHeight || 0
        );
    });

    const startingHeight = await getPageHeight();
    let lastHeight = startingHeight;
    let scrollCount = 0;
    let scrollPosition = 0;

    console.error(`Initial page height: ${startingHeight}px`);

    // Scroll to top first
    await page.evaluate(() => {
        window.scrollTo({ top: 0, left: 0, behavior: 'smooth' });
    });
    await sleep(500);

    while (scrollCount < scrollLimit) {
        // Check timeout
        const elapsed = Date.now() - startTime;
        if (elapsed >= timeout) {
            console.error(`Timeout reached after ${scrollCount} scrolls`);
            break;
        }

        scrollPosition = (scrollCount + 1) * scrollDistance;
        console.error(`Scrolling down ${scrollCount + 1}x ${scrollDistance}px... (${scrollPosition}/${lastHeight})`);

        await page.evaluate((yOffset) => {
            window.scrollTo({ top: yOffset, left: 0, behavior: 'smooth' });
        }, scrollPosition);

        scrollCount++;
        await sleep(scrollDelay);

        // Check if new content was added (infinite scroll detection)
        const newHeight = await getPageHeight();
        const addedPx = newHeight - lastHeight;

        if (addedPx > 0) {
            console.error(`Detected infini-scrolling: ${lastHeight}+${addedPx} => ${newHeight}`);
        } else if (scrollPosition >= newHeight + scrollDistance) {
            // Reached the bottom
            if (scrollCount > 2) {
                console.error(`Reached bottom of page at ${newHeight}px`);
                break;
            }
        }

        lastHeight = newHeight;

        // Check if we've reached minimum height and can stop
        if (lastHeight >= minHeight && scrollPosition >= lastHeight) {
            console.error(`Reached minimum height target (${minHeight}px)`);
            break;
        }
    }

    // Scroll to absolute bottom
    if (scrollPosition < lastHeight) {
        await page.evaluate(() => {
            window.scrollTo({ top: document.documentElement.scrollHeight, left: 0, behavior: 'smooth' });
        });
        await sleep(scrollDelay);
    }

    // Scroll back to top
    console.error(`Reached bottom of page at ${lastHeight}px, scrolling back to top...`);
    await page.evaluate(() => {
        window.scrollTo({ top: 0, left: 0, behavior: 'smooth' });
    });
    await sleep(scrollDelay);

    const totalElapsed = Date.now() - startTime;

    return {
        scrollCount,
        finalHeight: lastHeight,
        startingHeight,
        elapsedMs: totalElapsed,
    };
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__45_infiniscroll.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const timeout = getEnvInt('INFINISCROLL_TIMEOUT', 120) * 1000;
    const scrollDelay = getEnvInt('INFINISCROLL_SCROLL_DELAY', 2000);
    const scrollDistance = getEnvInt('INFINISCROLL_SCROLL_DISTANCE', 1600);
    const scrollLimit = getEnvInt('INFINISCROLL_SCROLL_LIMIT', 10);
    const minHeight = getEnvInt('INFINISCROLL_MIN_HEIGHT', 16000);

    const cdpUrl = getCdpUrl();
    if (!cdpUrl) {
        console.error('ERROR: Chrome CDP URL not found (chrome plugin must run first)');
        process.exit(1);
    }

    // Wait for page to be loaded
    const pageLoaded = await waitForChromeTabLoaded(60000);
    if (!pageLoaded) {
        console.error('ERROR: Page not loaded after 60s (chrome_navigate must complete first)');
        process.exit(1);
    }

    let browser = null;
    try {
        browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

        const pages = await browser.pages();
        if (pages.length === 0) {
            throw new Error('No pages found in browser');
        }

        // Find the right page by target ID
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

        // Set viewport to ensure proper page rendering
        const resolution = getEnv('CHROME_RESOLUTION', '1440,2000').split(',').map(x => parseInt(x.trim(), 10));
        await page.setViewport({ width: resolution[0] || 1440, height: resolution[1] || 2000 });

        console.error(`Starting infinite scroll on ${url}`);
        const result = await scrollDown(page, {
            timeout,
            scrollDelay,
            scrollDistance,
            scrollLimit,
            minHeight,
        });

        browser.disconnect();

        const elapsedSec = (result.elapsedMs / 1000).toFixed(1);
        const finalHeightStr = result.finalHeight.toLocaleString();
        const addedHeight = result.finalHeight - result.startingHeight;
        const addedStr = addedHeight > 0 ? `+${addedHeight.toLocaleString()}px new content` : 'no new content';
        const outputStr = `scrolled to ${finalHeightStr}px (${addedStr}) over ${elapsedSec}s`;

        console.error(`Success: ${outputStr}`);
        console.log(JSON.stringify({
            type: 'ArchiveResult',
            status: 'succeeded',
            output_str: outputStr,
        }));
        process.exit(0);

    } catch (e) {
        if (browser) browser.disconnect();
        console.error(`ERROR: ${e.name}: ${e.message}`);
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
