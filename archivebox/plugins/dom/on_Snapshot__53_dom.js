#!/usr/bin/env node
/**
 * Dump the DOM of a URL using Chrome/Puppeteer.
 *
 * If a Chrome session exists (from chrome plugin), connects to it via CDP.
 * Otherwise launches a new Chrome instance.
 *
 * Usage: on_Snapshot__53_dom.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes dom/output.html
 *
 * Environment variables:
 *     CHROME_BINARY: Path to Chrome/Chromium binary
 *     CHROME_TIMEOUT: Timeout in seconds (default: 60)
 *     CHROME_RESOLUTION: Page resolution (default: 1440,2000)
 *     CHROME_USER_AGENT: User agent string (optional)
 *     CHROME_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: true)
 *     CHROME_HEADLESS: Run in headless mode (default: true)
 *     DOM_ENABLED: Enable DOM extraction (default: true)
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const {
    findChromium,
    getEnv,
    getEnvBool,
    getEnvInt,
    parseResolution,
    parseArgs,
    readCdpUrl,
} = require('../chrome/chrome_utils.js');

// Check if DOM is enabled BEFORE requiring puppeteer
if (!getEnvBool('DOM_ENABLED', true)) {
    console.error('Skipping DOM (DOM_ENABLED=False)');
    // Temporary failure (config disabled) - NO JSONL emission
    process.exit(0);
}

// Now safe to require puppeteer
const puppeteer = require('puppeteer-core');

// Extractor metadata
const PLUGIN_NAME = 'dom';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'output.html';
const CHROME_SESSION_DIR = '../chrome';

// Check if staticfile extractor already downloaded this URL
const STATICFILE_DIR = '../staticfile';
function hasStaticFileOutput() {
    if (!fs.existsSync(STATICFILE_DIR)) return false;
    const stdoutPath = path.join(STATICFILE_DIR, 'stdout.log');
    if (!fs.existsSync(stdoutPath)) return false;
    const stdout = fs.readFileSync(stdoutPath, 'utf8');
    for (const line of stdout.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('{')) continue;
        try {
            const record = JSON.parse(trimmed);
            if (record.type === 'ArchiveResult' && record.status === 'succeeded') {
                return true;
            }
        } catch (e) {}
    }
    return false;
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

async function dumpDom(url) {
    const timeout = (getEnvInt('CHROME_TIMEOUT') || getEnvInt('TIMEOUT', 60)) * 1000;
    const resolution = getEnv('CHROME_RESOLUTION') || getEnv('RESOLUTION', '1440,2000');
    const userAgent = getEnv('CHROME_USER_AGENT') || getEnv('USER_AGENT', '');
    const checkSsl = getEnvBool('CHROME_CHECK_SSL_VALIDITY', getEnvBool('CHECK_SSL_VALIDITY', true));
    const headless = getEnvBool('CHROME_HEADLESS', true);

    const { width, height } = parseResolution(resolution);

    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    let browser = null;
    let page = null;
    let connectedToSession = false;

    try {
        // Try to connect to existing Chrome session
        const cdpUrl = readCdpUrl(CHROME_SESSION_DIR);
        if (cdpUrl) {
            try {
                browser = await puppeteer.connect({
                    browserWSEndpoint: cdpUrl,
                    defaultViewport: { width, height },
                });
                connectedToSession = true;

                // Get existing pages or create new one
                const pages = await browser.pages();
                page = pages.find(p => p.url().startsWith('http')) || pages[0];

                if (!page) {
                    page = await browser.newPage();
                }

                // Set viewport on the page
                await page.setViewport({ width, height });

            } catch (e) {
                console.error(`Failed to connect to CDP session: ${e.message}`);
                browser = null;
            }
        }

        // Fall back to launching new browser
        if (!browser) {
            const executablePath = findChromium();
            if (!executablePath) {
                return { success: false, error: 'Chrome binary not found' };
            }

            browser = await puppeteer.launch({
                executablePath,
                headless: headless ? 'new' : false,
                args: [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    `--window-size=${width},${height}`,
                    ...(checkSsl ? [] : ['--ignore-certificate-errors']),
                ],
                defaultViewport: { width, height },
            });

            page = await browser.newPage();

            // Navigate to URL (only if we launched fresh browser)
            if (userAgent) {
                await page.setUserAgent(userAgent);
            }

            await page.goto(url, {
                waitUntil: 'networkidle2',
                timeout,
            });
        }

        // Get the full DOM content
        const domContent = await page.content();

        if (domContent && domContent.length > 100) {
            fs.writeFileSync(outputPath, domContent, 'utf8');
            return { success: true, output: outputPath };
        } else {
            return { success: false, error: 'DOM content too short or empty' };
        }

    } catch (e) {
        return { success: false, error: `${e.name}: ${e.message}` };
    } finally {
        // Only close browser if we launched it (not if we connected to session)
        if (browser && !connectedToSession) {
            await browser.close();
        }
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__53_dom.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    try {
        // Check if staticfile extractor already handled this (permanent skip)
        if (hasStaticFileOutput()) {
            console.error(`Skipping DOM - staticfile extractor already downloaded this`);
            // Permanent skip - emit ArchiveResult with status='skipped'
            console.log(JSON.stringify({
                type: 'ArchiveResult',
                status: 'skipped',
                output_str: 'staticfile already handled',
            }));
            process.exit(0);
        }

        // Only wait for page load if using shared Chrome session
        const cdpUrl = readCdpUrl(CHROME_SESSION_DIR);
        if (cdpUrl) {
            // Wait for page to be fully loaded
            const pageLoaded = await waitForChromeTabLoaded(60000);
            if (!pageLoaded) {
                throw new Error('Page not loaded after 60s (chrome_navigate must complete first)');
            }
        }

        const result = await dumpDom(url);

        if (result.success) {
            // Success - emit ArchiveResult
            const size = fs.statSync(result.output).size;
            console.error(`DOM saved (${size} bytes)`);
            console.log(JSON.stringify({
                type: 'ArchiveResult',
                status: 'succeeded',
                output_str: result.output,
            }));
            process.exit(0);
        } else {
            // Transient error - emit NO JSONL
            console.error(`ERROR: ${result.error}`);
            process.exit(1);
        }
    } catch (e) {
        // Transient error - emit NO JSONL
        console.error(`ERROR: ${e.name}: ${e.message}`);
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
