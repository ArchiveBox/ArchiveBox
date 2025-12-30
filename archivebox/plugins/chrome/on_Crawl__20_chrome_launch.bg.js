#!/usr/bin/env node
/**
 * Launch a shared Chromium browser session for the entire crawl.
 *
 * This runs once per crawl and keeps Chromium alive for all snapshots to share.
 * Each snapshot creates its own tab via on_Snapshot__20_chrome_tab.bg.js.
 *
 * NOTE: We use Chromium instead of Chrome because Chrome 137+ removed support for
 * --load-extension and --disable-extensions-except flags.
 *
 * Usage: on_Crawl__20_chrome_launch.bg.js --crawl-id=<uuid> --source-url=<url>
 * Output: Creates chrome/ directory under crawl output dir with:
 *   - cdp_url.txt: WebSocket URL for CDP connection
 *   - chrome.pid: Chromium process ID (for cleanup)
 *   - port.txt: Debug port number
 *   - extensions.json: Loaded extensions metadata
 *
 * Environment variables:
 *     NODE_MODULES_DIR: Path to node_modules directory for module resolution
 *     CHROME_BINARY: Path to Chromium binary (falls back to auto-detection)
 *     CHROME_RESOLUTION: Page resolution (default: 1440,2000)
 *     CHROME_HEADLESS: Run in headless mode (default: true)
 *     CHROME_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: true)
 *     CHROME_EXTENSIONS_DIR: Directory containing Chrome extensions
 */

// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) {
    module.paths.unshift(process.env.NODE_MODULES_DIR);
}

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');
const {
    findChromium,
    launchChromium,
    killChrome,
    getEnv,
    writePidWithMtime,
} = require('./chrome_utils.js');

// Extractor metadata
const PLUGIN_NAME = 'chrome_launch';
const OUTPUT_DIR = 'chrome';

// Global state for cleanup
let chromePid = null;
let browserInstance = null;

// Parse command line arguments
function parseArgs() {
    const args = {};
    process.argv.slice(2).forEach((arg) => {
        if (arg.startsWith('--')) {
            const [key, ...valueParts] = arg.slice(2).split('=');
            args[key.replace(/-/g, '_')] = valueParts.join('=') || true;
        }
    });
    return args;
}

// Cleanup handler for SIGTERM
async function cleanup() {
    console.error('[*] Cleaning up Chrome session...');

    // Try graceful browser close first
    if (browserInstance) {
        try {
            console.error('[*] Closing browser gracefully...');
            await browserInstance.close();
            browserInstance = null;
            console.error('[+] Browser closed gracefully');
        } catch (e) {
            console.error(`[!] Graceful close failed: ${e.message}`);
        }
    }

    // Kill Chrome process
    if (chromePid) {
        await killChrome(chromePid, OUTPUT_DIR);
    }

    process.exit(0);
}

// Register signal handlers
process.on('SIGTERM', cleanup);
process.on('SIGINT', cleanup);

async function main() {
    const args = parseArgs();
    const crawlId = args.crawl_id;

    try {
        const binary = findChromium();
        if (!binary) {
            console.error('ERROR: Chromium binary not found');
            console.error('DEPENDENCY_NEEDED=chromium');
            console.error('BIN_PROVIDERS=puppeteer,env,playwright,apt,brew');
            console.error('INSTALL_HINT=npx @puppeteer/browsers install chromium@latest');
            process.exit(1);
        }

        // Get Chromium version
        let version = '';
        try {
            const { execSync } = require('child_process');
            version = execSync(`"${binary}" --version`, { encoding: 'utf8', timeout: 5000 })
                .trim()
                .slice(0, 64);
        } catch (e) {}

        console.error(`[*] Using browser: ${binary}`);
        if (version) console.error(`[*] Version: ${version}`);

        // Load installed extensions
        const extensionsDir = getEnv('CHROME_EXTENSIONS_DIR') ||
            path.join(getEnv('DATA_DIR', '.'), 'personas', getEnv('ACTIVE_PERSONA', 'Default'), 'chrome_extensions');

        const installedExtensions = [];
        const extensionPaths = [];
        if (fs.existsSync(extensionsDir)) {
            const files = fs.readdirSync(extensionsDir);
            for (const file of files) {
                if (file.endsWith('.extension.json')) {
                    try {
                        const extPath = path.join(extensionsDir, file);
                        const extData = JSON.parse(fs.readFileSync(extPath, 'utf-8'));
                        if (extData.unpacked_path && fs.existsSync(extData.unpacked_path)) {
                            installedExtensions.push(extData);
                            extensionPaths.push(extData.unpacked_path);
                            console.error(`[*] Loading extension: ${extData.name || file}`);
                        }
                    } catch (e) {
                        console.warn(`[!] Skipping invalid extension cache: ${file}`);
                    }
                }
            }
        }

        if (installedExtensions.length > 0) {
            console.error(`[+] Found ${installedExtensions.length} extension(s) to load`);
        }

        // Write hook's own PID
        const hookStartTime = Date.now() / 1000;
        if (!fs.existsSync(OUTPUT_DIR)) {
            fs.mkdirSync(OUTPUT_DIR, { recursive: true });
        }
        writePidWithMtime(path.join(OUTPUT_DIR, 'hook.pid'), process.pid, hookStartTime);

        // Launch Chromium using consolidated function
        const result = await launchChromium({
            binary,
            outputDir: OUTPUT_DIR,
            extensionPaths,
        });

        if (!result.success) {
            console.error(`ERROR: ${result.error}`);
            process.exit(1);
        }

        chromePid = result.pid;
        const cdpUrl = result.cdpUrl;

        // Write extensions metadata
        if (installedExtensions.length > 0) {
            fs.writeFileSync(
                path.join(OUTPUT_DIR, 'extensions.json'),
                JSON.stringify(installedExtensions, null, 2)
            );
        }

        // Connect puppeteer for extension verification
        console.error(`[*] Connecting puppeteer to CDP...`);
        const browser = await puppeteer.connect({
            browserWSEndpoint: cdpUrl,
            defaultViewport: null,
        });
        browserInstance = browser;

        // Verify extensions loaded
        if (extensionPaths.length > 0) {
            await new Promise(r => setTimeout(r, 3000));

            const targets = browser.targets();
            console.error(`[*] All browser targets (${targets.length}):`);
            for (const t of targets) {
                console.error(`    - ${t.type()}: ${t.url().slice(0, 80)}`);
            }

            const extTargets = targets.filter(t =>
                t.url().startsWith('chrome-extension://') ||
                t.type() === 'service_worker' ||
                t.type() === 'background_page'
            );

            // Filter out built-in extensions
            const builtinIds = [
                'nkeimhogjdpnpccoofpliimaahmaaome',
                'fignfifoniblkonapihmkfakmlgkbkcf',
                'ahfgeienlihckogmohjhadlkjgocpleb',
                'mhjfbmdgcfjbbpaeojofohoefgiehjai',
            ];
            const customExtTargets = extTargets.filter(t => {
                const url = t.url();
                if (!url.startsWith('chrome-extension://')) return false;
                const extId = url.split('://')[1].split('/')[0];
                return !builtinIds.includes(extId);
            });

            console.error(`[+] Found ${customExtTargets.length} custom extension target(s)`);

            for (const target of customExtTargets) {
                const url = target.url();
                const extId = url.split('://')[1].split('/')[0];
                console.error(`[+] Extension loaded: ${extId} (${target.type()})`);
            }

            if (customExtTargets.length === 0 && extensionPaths.length > 0) {
                console.error(`[!] Warning: No custom extensions detected. Extension loading may have failed.`);
                console.error(`[!] Make sure you are using Chromium, not Chrome (Chrome 137+ removed --load-extension support)`);
            }
        }

        console.error(`[+] Chromium session started for crawl ${crawlId}`);
        console.error(`[+] CDP URL: ${cdpUrl}`);
        console.error(`[+] PID: ${chromePid}`);

        // Stay alive to handle cleanup on SIGTERM
        console.log('[*] Chromium launch hook staying alive to handle cleanup...');
        setInterval(() => {}, 1000000);

    } catch (e) {
        console.error(`ERROR: ${e.name}: ${e.message}`);
        process.exit(1);
    }
}

main().catch((e) => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
