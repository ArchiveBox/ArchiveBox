#!/usr/bin/env node
/**
 * Launch a shared Chromium browser session for the entire crawl.
 *
 * This runs once per crawl and keeps Chromium alive for all snapshots to share.
 * Each snapshot creates its own tab via on_Snapshot__10_chrome_tab.bg.js.
 *
 * NOTE: We use Chromium instead of Chrome because Chrome 137+ removed support for
 * --load-extension and --disable-extensions-except flags.
 *
 * Usage: on_Crawl__90_chrome_launch.bg.js --crawl-id=<uuid> --source-url=<url>
 * Output: Writes to current directory (executor creates chrome/ dir):
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
const puppeteer = require('puppeteer');
const {
    findChromium,
    launchChromium,
    killChrome,
    getEnv,
    writePidWithMtime,
    getExtensionsDir,
} = require('./chrome_utils.js');

// Extractor metadata
const PLUGIN_NAME = 'chrome_launch';
const OUTPUT_DIR = '.';

// Global state for cleanup
let chromePid = null;
let browserInstance = null;

function parseCookiesTxt(contents) {
    const cookies = [];
    let skipped = 0;

    for (const rawLine of contents.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line) continue;

        let httpOnly = false;
        let dataLine = line;

        if (dataLine.startsWith('#HttpOnly_')) {
            httpOnly = true;
            dataLine = dataLine.slice('#HttpOnly_'.length);
        } else if (dataLine.startsWith('#')) {
            continue;
        }

        const parts = dataLine.split('\t');
        if (parts.length < 7) {
            skipped += 1;
            continue;
        }

        const [domainRaw, includeSubdomainsRaw, pathRaw, secureRaw, expiryRaw, name, value] = parts;
        if (!name || !domainRaw) {
            skipped += 1;
            continue;
        }

        const includeSubdomains = (includeSubdomainsRaw || '').toUpperCase() === 'TRUE';
        let domain = domainRaw;
        if (includeSubdomains && !domain.startsWith('.')) domain = `.${domain}`;
        if (!includeSubdomains && domain.startsWith('.')) domain = domain.slice(1);

        const cookie = {
            name,
            value,
            domain,
            path: pathRaw || '/',
            secure: (secureRaw || '').toUpperCase() === 'TRUE',
            httpOnly,
        };

        const expires = parseInt(expiryRaw, 10);
        if (!isNaN(expires) && expires > 0) {
            cookie.expires = expires;
        }

        cookies.push(cookie);
    }

    return { cookies, skipped };
}

async function importCookiesFromFile(browser, cookiesFile, userDataDir) {
    if (!cookiesFile) return;

    if (!fs.existsSync(cookiesFile)) {
        console.error(`[!] Cookies file not found: ${cookiesFile}`);
        return;
    }

    let contents = '';
    try {
        contents = fs.readFileSync(cookiesFile, 'utf-8');
    } catch (e) {
        console.error(`[!] Failed to read COOKIES_TXT_FILE: ${e.message}`);
        return;
    }

    const { cookies, skipped } = parseCookiesTxt(contents);
    if (cookies.length === 0) {
        console.error('[!] No cookies found to import');
        return;
    }

    console.error(`[*] Importing ${cookies.length} cookies from ${cookiesFile}...`);
    if (skipped) {
        console.error(`[*] Skipped ${skipped} malformed cookie line(s)`);
    }
    if (!userDataDir) {
        console.error('[!] CHROME_USER_DATA_DIR not set; cookies will not persist beyond this session');
    }

    const page = await browser.newPage();
    const client = await page.target().createCDPSession();
    await client.send('Network.enable');

    const chunkSize = 200;
    let imported = 0;
    for (let i = 0; i < cookies.length; i += chunkSize) {
        const chunk = cookies.slice(i, i + chunkSize);
        try {
            await client.send('Network.setCookies', { cookies: chunk });
            imported += chunk.length;
        } catch (e) {
            console.error(`[!] Failed to import cookies ${i + 1}-${i + chunk.length}: ${e.message}`);
        }
    }

    await page.close();
    console.error(`[+] Imported ${imported}/${cookies.length} cookies`);
}

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
        const extensionsDir = getExtensionsDir();
        const userDataDir = getEnv('CHROME_USER_DATA_DIR');
        const cookiesFile = getEnv('COOKIES_TXT_FILE') || getEnv('COOKIES_FILE');

        if (userDataDir) {
            console.error(`[*] Using user data dir: ${userDataDir}`);
        }
        if (cookiesFile) {
            console.error(`[*] Using cookies file: ${cookiesFile}`);
        }

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

        // Note: PID file is written by run_hook() with hook-specific name
        // Snapshot.cleanup() kills all *.pid processes when done
        if (!fs.existsSync(OUTPUT_DIR)) {
            fs.mkdirSync(OUTPUT_DIR, { recursive: true });
        }

        // Launch Chromium using consolidated function
        // userDataDir is derived from ACTIVE_PERSONA by get_config() if not explicitly set
        const result = await launchChromium({
            binary,
            outputDir: OUTPUT_DIR,
            userDataDir,
            extensionPaths,
        });

        if (!result.success) {
            console.error(`ERROR: ${result.error}`);
            process.exit(1);
        }

        chromePid = result.pid;
        const cdpUrl = result.cdpUrl;

        // Connect puppeteer for extension verification
        console.error(`[*] Connecting puppeteer to CDP...`);
        const browser = await puppeteer.connect({
            browserWSEndpoint: cdpUrl,
            defaultViewport: null,
        });
        browserInstance = browser;

        // Import cookies into Chrome profile at crawl start
        await importCookiesFromFile(browser, cookiesFile, userDataDir);

        // Get actual extension IDs from chrome://extensions page
        if (extensionPaths.length > 0) {
            await new Promise(r => setTimeout(r, 2000));

            try {
                const extPage = await browser.newPage();
                await extPage.goto('chrome://extensions', { waitUntil: 'domcontentloaded', timeout: 10000 });
                await new Promise(r => setTimeout(r, 2000));

                // Parse extension info from the page
                const extensionsFromPage = await extPage.evaluate(() => {
                    const extensions = [];
                    // Extensions manager uses shadow DOM
                    const manager = document.querySelector('extensions-manager');
                    if (!manager || !manager.shadowRoot) return extensions;

                    const itemList = manager.shadowRoot.querySelector('extensions-item-list');
                    if (!itemList || !itemList.shadowRoot) return extensions;

                    const items = itemList.shadowRoot.querySelectorAll('extensions-item');
                    for (const item of items) {
                        const id = item.getAttribute('id');
                        const nameEl = item.shadowRoot?.querySelector('#name');
                        const name = nameEl?.textContent?.trim() || '';
                        if (id && name) {
                            extensions.push({ id, name });
                        }
                    }
                    return extensions;
                });

                console.error(`[*] Found ${extensionsFromPage.length} extension(s) on chrome://extensions`);
                for (const e of extensionsFromPage) {
                    console.error(`    - ${e.id}: "${e.name}"`);
                }

                // Match extensions by name (strict matching)
                for (const ext of installedExtensions) {
                    // Read the extension's manifest to get its display name
                    const manifestPath = path.join(ext.unpacked_path, 'manifest.json');
                    if (fs.existsSync(manifestPath)) {
                        const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
                        let manifestName = manifest.name || '';

                        // Resolve message placeholder (e.g., __MSG_extName__)
                        if (manifestName.startsWith('__MSG_') && manifestName.endsWith('__')) {
                            const msgKey = manifestName.slice(6, -2); // Extract key from __MSG_key__
                            const defaultLocale = manifest.default_locale || 'en';
                            const messagesPath = path.join(ext.unpacked_path, '_locales', defaultLocale, 'messages.json');
                            if (fs.existsSync(messagesPath)) {
                                try {
                                    const messages = JSON.parse(fs.readFileSync(messagesPath, 'utf-8'));
                                    if (messages[msgKey] && messages[msgKey].message) {
                                        manifestName = messages[msgKey].message;
                                    }
                                } catch (e) {
                                    console.error(`[!] Failed to read messages.json: ${e.message}`);
                                }
                            }
                        }

                        console.error(`[*] Looking for match: ext.name="${ext.name}" manifest.name="${manifestName}"`);

                        // Find matching extension from page by exact name match first
                        let match = extensionsFromPage.find(e => e.name === manifestName);

                        // If no exact match, try case-insensitive exact match
                        if (!match) {
                            match = extensionsFromPage.find(e =>
                                e.name.toLowerCase() === manifestName.toLowerCase()
                            );
                        }

                        if (match) {
                            ext.id = match.id;
                            console.error(`[+] Matched extension: ${ext.name} (${manifestName}) -> ${match.id}`);
                        } else {
                            console.error(`[!] No match found for: ${ext.name} (${manifestName})`);
                        }
                    }
                }

                await extPage.close();
            } catch (e) {
                console.error(`[!] Failed to get extensions from chrome://extensions: ${e.message}`);
            }

            // Fallback: check browser targets
            const targets = browser.targets();
            const builtinIds = [
                'nkeimhogjdpnpccoofpliimaahmaaome',
                'fignfifoniblkonapihmkfakmlgkbkcf',
                'ahfgeienlihckogmohjhadlkjgocpleb',
                'mhjfbmdgcfjbbpaeojofohoefgiehjai',
            ];
            const customExtTargets = targets.filter(t => {
                const url = t.url();
                if (!url.startsWith('chrome-extension://')) return false;
                const extId = url.split('://')[1].split('/')[0];
                return !builtinIds.includes(extId);
            });

            console.error(`[+] Found ${customExtTargets.length} custom extension target(s)`);

            for (const target of customExtTargets) {
                const url = target.url();
                const extId = url.split('://')[1].split('/')[0];
                console.error(`[+] Extension target: ${extId} (${target.type()})`);
            }

            if (customExtTargets.length === 0 && extensionPaths.length > 0) {
                console.error(`[!] Warning: No custom extensions detected. Extension loading may have failed.`);
                console.error(`[!] Make sure you are using Chromium, not Chrome (Chrome 137+ removed --load-extension support)`);
            }
        }

        // Write extensions metadata with actual IDs
        if (installedExtensions.length > 0) {
            fs.writeFileSync(
                path.join(OUTPUT_DIR, 'extensions.json'),
                JSON.stringify(installedExtensions, null, 2)
            );
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
