#!/usr/bin/env node
/**
 * Scroll the page down to trigger infinite scroll / lazy loading.
 *
 * Scrolls down 1 page at a time, up to INFINISCROLL_SCROLL_LIMIT times,
 * ensuring at least INFINISCROLL_MIN_HEIGHT (default 16,000px) is reached.
 * Stops early if no new content loads after a scroll.
 *
 * Optionally expands <details> elements and clicks "load more" buttons.
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
 *     INFINISCROLL_EXPAND_DETAILS: Expand <details> and comments (default: true)
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const {
    getEnv,
    getEnvBool,
    getEnvInt,
} = require('../chrome/chrome_utils.js');

// Check if infiniscroll is enabled BEFORE requiring puppeteer
if (!getEnvBool('INFINISCROLL_ENABLED', true)) {
    console.error('Skipping infiniscroll (INFINISCROLL_ENABLED=False)');
    process.exit(0);
}

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

/**
 * Expand <details> elements and click "load more" buttons for comments.
 * Based on archivebox.ts expandComments function.
 */
async function expandDetails(page, options = {}) {
    const {
        timeout = 30000,
        limit = 500,
        delay = 500,
    } = options;

    const startTime = Date.now();

    // First, expand all <details> elements
    const detailsExpanded = await page.evaluate(() => {
        let count = 0;
        // Generic <details> elements
        document.querySelectorAll('details:not([open])').forEach(el => {
            el.open = true;
            count++;
        });
        // Github README details sections
        document.querySelectorAll('article details:not([open])').forEach(el => {
            el.open = true;
            count++;
        });
        // Github issue discussion hidden comments
        document.querySelectorAll('div.js-discussion details:not(.details-overlay):not([open])').forEach(el => {
            el.open = true;
            count++;
        });
        // HedgeDoc/Markdown details sections
        document.querySelectorAll('.markdown-body details:not([open])').forEach(el => {
            el.open = true;
            count++;
        });
        return count;
    });

    if (detailsExpanded > 0) {
        console.error(`Expanded ${detailsExpanded} <details> elements`);
    }

    // Then click "load more" buttons for comments
    const numExpanded = await page.evaluate(async ({ timeout, limit, delay }) => {
        // Helper to find elements by XPath
        function getElementsByXPath(xpath) {
            const results = [];
            const xpathResult = document.evaluate(
                xpath,
                document,
                null,
                XPathResult.ORDERED_NODE_ITERATOR_TYPE,
                null
            );
            let node;
            while ((node = xpathResult.iterateNext()) != null) {
                results.push(node);
            }
            return results;
        }

        const wait = (ms) => new Promise(res => setTimeout(res, ms));

        // Find all "load more" type buttons/links
        const getLoadMoreLinks = () => [
            // Reddit (new)
            ...document.querySelectorAll('faceplate-partial[loading=action]'),
            // Reddit (old) - show more replies
            ...document.querySelectorAll('a[onclick^="return morechildren"]'),
            // Reddit (old) - show hidden replies
            ...document.querySelectorAll('a[onclick^="return togglecomment"]'),
            // Twitter/X - show more replies
            ...getElementsByXPath("//*[text()='Show more replies']"),
            ...getElementsByXPath("//*[text()='Show replies']"),
            // Generic "load more" / "show more" buttons
            ...getElementsByXPath("//*[contains(text(),'Load more')]"),
            ...getElementsByXPath("//*[contains(text(),'Show more')]"),
            // Hacker News
            ...document.querySelectorAll('a.morelink'),
        ];

        let expanded = 0;
        let loadMoreLinks = getLoadMoreLinks();
        const startTime = Date.now();

        while (loadMoreLinks.length > 0) {
            for (const link of loadMoreLinks) {
                // Skip certain elements
                if (link.slot === 'children') continue;

                try {
                    link.scrollIntoView({ behavior: 'smooth' });
                    link.click();
                    expanded++;
                    await wait(delay);
                } catch (e) {
                    // Ignore click errors
                }

                // Check limits
                if (expanded >= limit) return expanded;
                if (Date.now() - startTime >= timeout) return expanded;
            }

            // Check for new load more links after clicking
            await wait(delay);
            loadMoreLinks = getLoadMoreLinks();
        }

        return expanded;
    }, { timeout, limit, delay });

    if (numExpanded > 0) {
        console.error(`Clicked ${numExpanded} "load more" buttons`);
    }

    return {
        detailsExpanded,
        commentsExpanded: numExpanded,
        total: detailsExpanded + numExpanded,
    };
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
    const expandDetailsEnabled = getEnvBool('INFINISCROLL_EXPAND_DETAILS', true);

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

        // Expand <details> and comments before scrolling (if enabled)
        let expandResult = { total: 0, detailsExpanded: 0, commentsExpanded: 0 };
        if (expandDetailsEnabled) {
            console.error('Expanding <details> and comments...');
            expandResult = await expandDetails(page, {
                timeout: Math.min(timeout / 4, 30000),
                limit: 500,
                delay: scrollDelay / 4,
            });
        }

        const result = await scrollDown(page, {
            timeout,
            scrollDelay,
            scrollDistance,
            scrollLimit,
            minHeight,
        });

        // Expand again after scrolling (new content may have loaded)
        if (expandDetailsEnabled) {
            const expandResult2 = await expandDetails(page, {
                timeout: Math.min(timeout / 4, 30000),
                limit: 500,
                delay: scrollDelay / 4,
            });
            expandResult.total += expandResult2.total;
            expandResult.detailsExpanded += expandResult2.detailsExpanded;
            expandResult.commentsExpanded += expandResult2.commentsExpanded;
        }

        browser.disconnect();

        const elapsedSec = (result.elapsedMs / 1000).toFixed(1);
        const finalHeightStr = result.finalHeight.toLocaleString();
        const addedHeight = result.finalHeight - result.startingHeight;
        const addedStr = addedHeight > 0 ? `+${addedHeight.toLocaleString()}px new content` : 'no new content';
        const expandStr = expandResult.total > 0 ? `, expanded ${expandResult.total}` : '';
        const outputStr = `scrolled to ${finalHeightStr}px (${addedStr}${expandStr}) over ${elapsedSec}s`;

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
