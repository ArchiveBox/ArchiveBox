#!/usr/bin/env node
/**
 * Extract accessibility tree and page outline from a URL.
 *
 * Extracts:
 * - Page outline (headings h1-h6, sections, articles)
 * - Iframe tree
 * - Accessibility snapshot
 * - ARIA labels and roles
 *
 * Usage: on_Snapshot__39_accessibility.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes accessibility/accessibility.json
 *
 * Environment variables:
 *     SAVE_ACCESSIBILITY: Enable accessibility extraction (default: true)
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

// Extractor metadata
const PLUGIN_NAME = 'accessibility';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'accessibility.json';
const CHROME_SESSION_DIR = '../chrome';
const CHROME_SESSION_REQUIRED_ERROR = 'No Chrome session found (chrome plugin must run first)';

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

function assertChromeSession() {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    const targetIdFile = path.join(CHROME_SESSION_DIR, 'target_id.txt');
    const pidFile = path.join(CHROME_SESSION_DIR, 'chrome.pid');
    if (!fs.existsSync(cdpFile) || !fs.existsSync(targetIdFile) || !fs.existsSync(pidFile)) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }
    try {
        const pid = parseInt(fs.readFileSync(pidFile, 'utf8').trim(), 10);
        if (!pid || Number.isNaN(pid)) throw new Error('Invalid pid');
        process.kill(pid, 0);
    } catch (e) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }
    const cdpUrl = getCdpUrl();
    if (!cdpUrl) {
        throw new Error(CHROME_SESSION_REQUIRED_ERROR);
    }
    return cdpUrl;
}

// Extract accessibility info
async function extractAccessibility(url) {
    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    let browser = null;

    try {
        // Connect to existing Chrome session
        const cdpUrl = assertChromeSession();

        browser = await puppeteer.connect({
            browserWSEndpoint: cdpUrl,
        });

        // Get the page
        const pages = await browser.pages();
        const page = pages.find(p => p.url().startsWith('http')) || pages[0];

        if (!page) {
            return { success: false, error: 'No page found in Chrome session' };
        }

        // Get accessibility snapshot
        const accessibilityTree = await page.accessibility.snapshot({ interestingOnly: true });

        // Extract page outline (headings, sections, etc.)
        const outline = await page.evaluate(() => {
            const headings = [];
            const elements = document.querySelectorAll(
                'h1, h2, h3, h4, h5, h6, a[name], header, footer, article, main, aside, nav, section, figure, summary, table, form, iframe'
            );

            elements.forEach(elem => {
                // Skip unnamed anchors
                if (elem.tagName.toLowerCase() === 'a' && !elem.name) return;

                const tagName = elem.tagName.toLowerCase();
                const elemId = elem.id || elem.name || elem.getAttribute('aria-label') || elem.role || '';
                const elemClasses = (elem.className || '').toString().trim().split(/\s+/).slice(0, 3).join(' .');
                const action = elem.action?.split('/').pop() || '';

                let summary = (elem.innerText || '').slice(0, 128);
                if (summary.length >= 128) summary += '...';

                let prefix = '';
                let title = '';

                // Format headings with # prefix
                const level = parseInt(tagName.replace('h', ''));
                if (!isNaN(level)) {
                    prefix = '#'.repeat(level);
                    title = elem.innerText || elemId || elemClasses;
                } else {
                    // For other elements, create breadcrumb path
                    const parents = [tagName];
                    let node = elem.parentNode;
                    while (node && parents.length < 5) {
                        if (node.tagName) {
                            const tag = node.tagName.toLowerCase();
                            if (!['div', 'span', 'p', 'body', 'html'].includes(tag)) {
                                parents.unshift(tag);
                            } else {
                                parents.unshift('');
                            }
                        }
                        node = node.parentNode;
                    }
                    prefix = parents.join('>');

                    title = elemId ? `#${elemId}` : '';
                    if (!title && elemClasses) title = `.${elemClasses}`;
                    if (action) title += ` /${action}`;
                    if (summary && !title.includes(summary)) title += `: ${summary}`;
                }

                // Clean up title
                title = title.replace(/\s+/g, ' ').trim();

                if (prefix) {
                    headings.push(`${prefix} ${title}`);
                }
            });

            return headings;
        });

        // Get iframe tree
        const iframes = [];
        function dumpFrameTree(frame, indent = '>') {
            iframes.push(indent + frame.url());
            for (const child of frame.childFrames()) {
                dumpFrameTree(child, indent + '>');
            }
        }
        dumpFrameTree(page.mainFrame(), '');

        const accessibilityData = {
            url,
            headings: outline,
            iframes,
            tree: accessibilityTree,
        };

        // Write output
        fs.writeFileSync(outputPath, JSON.stringify(accessibilityData, null, 2));

        return { success: true, output: outputPath, accessibilityData };

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
        console.error('Usage: on_Snapshot__39_accessibility.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    try {
        // Check if enabled
        if (!getEnvBool('ACCESSIBILITY_ENABLED', true)) {
            console.log('Skipping accessibility (ACCESSIBILITY_ENABLED=False)');
            // Output clean JSONL (no RESULT_JSON= prefix)
            console.log(JSON.stringify({
                type: 'ArchiveResult',
                status: 'skipped',
                output_str: 'ACCESSIBILITY_ENABLED=False',
            }));
            process.exit(0);
        }

        // Check if Chrome session exists, then wait for page load
        assertChromeSession();
        const pageLoaded = await waitForChromeTabLoaded(60000);
        if (!pageLoaded) {
            throw new Error('Page not loaded after 60s (chrome_navigate must complete first)');
        }

        const result = await extractAccessibility(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            const headingCount = result.accessibilityData.headings.length;
            const iframeCount = result.accessibilityData.iframes.length;
            console.log(`Accessibility extracted: ${headingCount} headings, ${iframeCount} iframes`);
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
