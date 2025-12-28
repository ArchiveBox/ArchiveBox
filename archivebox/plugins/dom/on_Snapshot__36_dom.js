#!/usr/bin/env node
/**
 * Dump the DOM of a URL using Chrome/Puppeteer.
 *
 * If a Chrome session exists (from chrome plugin), connects to it via CDP.
 * Otherwise launches a new Chrome instance.
 *
 * Usage: on_Snapshot__23_dom.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes dom/output.html
 *
 * Environment variables:
 *     CHROME_BINARY: Path to Chrome/Chromium binary
 *     CHROME_TIMEOUT: Timeout in seconds (default: 60)
 *     CHROME_RESOLUTION: Page resolution (default: 1440,2000)
 *     CHROME_USER_AGENT: User agent string (optional)
 *     CHROME_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: true)
 *     CHROME_HEADLESS: Run in headless mode (default: true)
 *     SAVE_DOM: Enable DOM extraction (default: true)
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

// Extractor metadata
const PLUGIN_NAME = 'dom';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'output.html';
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

function getEnvInt(name, defaultValue = 0) {
    const val = parseInt(getEnv(name, String(defaultValue)), 10);
    return isNaN(val) ? defaultValue : val;
}

// Check if staticfile extractor already downloaded this URL
const STATICFILE_DIR = '../staticfile';
function hasStaticFileOutput() {
    return fs.existsSync(STATICFILE_DIR) && fs.readdirSync(STATICFILE_DIR).length > 0;
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

// Find Chrome binary
function findChrome() {
    const chromeBinary = getEnv('CHROME_BINARY');
    if (chromeBinary && fs.existsSync(chromeBinary)) {
        return chromeBinary;
    }

    const candidates = [
        // Linux
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        // macOS
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
    ];

    for (const candidate of candidates) {
        if (candidate.startsWith('/') && fs.existsSync(candidate)) {
            return candidate;
        }
    }

    return null;
}

// Parse resolution string
function parseResolution(resolution) {
    const [width, height] = resolution.split(',').map(x => parseInt(x.trim(), 10));
    return { width: width || 1440, height: height || 2000 };
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
        const cdpUrl = getCdpUrl();
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
            const executablePath = findChrome();
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
        console.error('Usage: on_Snapshot__23_dom.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    try {
        // Check if DOM is enabled
        if (!getEnvBool('SAVE_DOM', true)) {
            console.error('Skipping DOM (SAVE_DOM=False)');
            // Feature disabled - no ArchiveResult, just exit
            process.exit(0);
        }
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
        } else {
            // Only wait for page load if using shared Chrome session
            const cdpUrl = getCdpUrl();
            if (cdpUrl) {
                // Wait for page to be fully loaded
                const pageLoaded = await waitForChromeTabLoaded(60000);
                if (!pageLoaded) {
                    throw new Error('Page not loaded after 60s (chrome_navigate must complete first)');
                }
            }

            const result = await dumpDom(url);

            if (result.success) {
                status = 'succeeded';
                output = result.output;
                const size = fs.statSync(output).size;
                console.error(`DOM saved (${size} bytes)`);
            } else {
                status = 'failed';
                error = result.error;
            }
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
