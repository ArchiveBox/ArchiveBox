#!/usr/bin/env node
/**
 * Start a Chrome browser session for use by other extractors.
 *
 * This extractor ONLY launches Chrome and creates a blank page - it does NOT navigate.
 * Pre-load extractors (21-29) can connect via CDP to register listeners before navigation.
 * The chrome_navigate extractor (30) performs the actual page load.
 *
 * Usage: on_Snapshot__20_chrome_session.js --url=<url> --snapshot-id=<uuid>
 * Output: Creates chrome_session/ with:
 *   - cdp_url.txt: WebSocket URL for CDP connection
 *   - pid.txt: Chrome process ID (for cleanup)
 *   - page_id.txt: Target ID of the page for other extractors to use
 *   - url.txt: The URL to be navigated to (for chrome_navigate)
 *
 * Environment variables:
 *     CHROME_BINARY: Path to Chrome/Chromium binary
 *     CHROME_RESOLUTION: Page resolution (default: 1440,2000)
 *     CHROME_USER_AGENT: User agent string (optional)
 *     CHROME_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: true)
 *     CHROME_HEADLESS: Run in headless mode (default: true)
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

// Import extension utilities
const extensionUtils = require('../chrome_extensions/chrome_extension_utils.js');

// Extractor metadata
const EXTRACTOR_NAME = 'chrome_session';
const OUTPUT_DIR = 'chrome_session';

// Get extensions directory from environment or use default
const EXTENSIONS_DIR = process.env.CHROME_EXTENSIONS_DIR ||
    path.join(process.env.DATA_DIR || './data', 'personas', process.env.ACTIVE_PERSONA || 'Default', 'chrome_extensions');

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
        if (fs.existsSync(candidate)) {
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

// Load installed extensions from cache files
function loadInstalledExtensions() {
    const extensions = [];

    if (!fs.existsSync(EXTENSIONS_DIR)) {
        return extensions;
    }

    // Look for *.extension.json cache files created by extension plugins
    const files = fs.readdirSync(EXTENSIONS_DIR);
    const extensionFiles = files.filter(f => f.endsWith('.extension.json'));

    for (const file of extensionFiles) {
        try {
            const filePath = path.join(EXTENSIONS_DIR, file);
            const data = fs.readFileSync(filePath, 'utf-8');
            const extension = JSON.parse(data);

            // Verify extension is actually installed
            const manifestPath = path.join(extension.unpacked_path, 'manifest.json');
            if (fs.existsSync(manifestPath)) {
                extensions.push(extension);
                console.log(`[+] Loaded extension: ${extension.name} (${extension.webstore_id})`);
            }
        } catch (e) {
            console.warn(`[⚠️] Failed to load extension from ${file}: ${e.message}`);
        }
    }

    return extensions;
}


async function startChromeSession(url, binary) {
    const resolution = getEnv('CHROME_RESOLUTION') || getEnv('RESOLUTION', '1440,2000');
    const userAgent = getEnv('CHROME_USER_AGENT') || getEnv('USER_AGENT', '');
    const checkSsl = getEnvBool('CHROME_CHECK_SSL_VALIDITY', getEnvBool('CHECK_SSL_VALIDITY', true));
    const headless = getEnvBool('CHROME_HEADLESS', true);

    const { width, height } = parseResolution(resolution);

    // Load installed extensions
    const extensions = loadInstalledExtensions();
    const extensionArgs = extensionUtils.getExtensionLaunchArgs(extensions);

    if (extensions.length > 0) {
        console.log(`[*] Loading ${extensions.length} Chrome extensions...`);
    }

    // Create output directory
    if (!fs.existsSync(OUTPUT_DIR)) {
        fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    }

    let browser = null;

    try {
        // Launch browser with Puppeteer
        browser = await puppeteer.launch({
            executablePath: binary,
            headless: headless ? 'new' : false,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-sync',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-default-apps',
                '--disable-infobars',
                '--disable-blink-features=AutomationControlled',
                '--disable-component-update',
                '--disable-domain-reliability',
                '--disable-breakpad',
                '--disable-background-networking',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-ipc-flooding-protection',
                '--password-store=basic',
                '--use-mock-keychain',
                '--font-render-hinting=none',
                '--force-color-profile=srgb',
                `--window-size=${width},${height}`,
                ...(checkSsl ? [] : ['--ignore-certificate-errors']),
                ...extensionArgs,
            ],
            defaultViewport: { width, height },
        });

        // Get the WebSocket endpoint URL
        const cdpUrl = browser.wsEndpoint();
        fs.writeFileSync(path.join(OUTPUT_DIR, 'cdp_url.txt'), cdpUrl);

        // Write PID for cleanup
        const browserProcess = browser.process();
        if (browserProcess) {
            fs.writeFileSync(path.join(OUTPUT_DIR, 'pid.txt'), String(browserProcess.pid));
        }

        // Create a new page (but DON'T navigate yet)
        const page = await browser.newPage();

        // Set user agent if specified
        if (userAgent) {
            await page.setUserAgent(userAgent);
        }

        // Write the page target ID so other extractors can find this specific page
        const target = page.target();
        const targetId = target._targetId;
        fs.writeFileSync(path.join(OUTPUT_DIR, 'page_id.txt'), targetId);

        // Write the URL for chrome_navigate to use
        fs.writeFileSync(path.join(OUTPUT_DIR, 'url.txt'), url);

        // Connect to loaded extensions at runtime (only if not already done)
        const extensionsFile = path.join(OUTPUT_DIR, 'extensions.json');
        if (extensions.length > 0 && !fs.existsSync(extensionsFile)) {
            console.log('[*] Connecting to loaded extensions (first time setup)...');
            try {
                const loadedExtensions = await extensionUtils.loadAllExtensionsFromBrowser(browser, extensions);

                // Write loaded extensions metadata for other extractors to use
                fs.writeFileSync(extensionsFile, JSON.stringify(loadedExtensions, null, 2));

                console.log(`[+] Extensions loaded and available at ${extensionsFile}`);
                console.log(`[+] ${loadedExtensions.length} extensions ready for configuration by subsequent plugins`);
            } catch (e) {
                console.warn(`[⚠️] Failed to load extensions from browser: ${e.message}`);
            }
        } else if (extensions.length > 0) {
            console.log('[*] Extensions already loaded from previous snapshot');
        }

        // Don't close browser - leave it running for other extractors
        // Detach puppeteer from browser so it stays running
        browser.disconnect();

        return { success: true, output: OUTPUT_DIR, cdpUrl, targetId };

    } catch (e) {
        // Kill browser if startup failed
        if (browser) {
            try {
                await browser.close();
            } catch (closeErr) {
                // Ignore
            }
        }
        return { success: false, error: `${e.name}: ${e.message}` };
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__20_chrome_session.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';
    let version = '';

    try {
        // chrome_session launches Chrome and creates a blank page
        // Pre-load extractors (21-29) register CDP listeners
        // chrome_navigate (30) performs actual navigation
        const binary = findChrome();
        if (!binary) {
            console.error('ERROR: Chrome/Chromium binary not found');
            console.error('DEPENDENCY_NEEDED=chrome');
            console.error('BIN_PROVIDERS=puppeteer,env,playwright,apt,brew');
            console.error('INSTALL_HINT=npx @puppeteer/browsers install chrome@stable');
            process.exit(1);
        }

        // Get Chrome version
        try {
            const { execSync } = require('child_process');
            version = execSync(`"${binary}" --version`, { encoding: 'utf8', timeout: 5000 }).trim().slice(0, 64);
        } catch (e) {
            version = '';
        }

        const result = await startChromeSession(url, binary);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            console.log(`Chrome session started (no navigation yet): ${result.cdpUrl}`);
            console.log(`Page target ID: ${result.targetId}`);
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
    if (version) {
        console.log(`VERSION=${version}`);
    }
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
        cmd_version: version,
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
