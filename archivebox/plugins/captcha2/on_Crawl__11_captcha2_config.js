#!/usr/bin/env node
/**
 * 2Captcha Extension Configuration
 *
 * Configures the 2captcha extension with API key after Crawl-level Chrome session starts.
 * Runs once per crawl to inject API key into extension storage.
 *
 * Priority: 11 (after chrome_launch at 20)
 * Hook: on_Crawl (runs once per crawl, not per snapshot)
 *
 * Requirements:
 * - API_KEY_2CAPTCHA environment variable must be set
 * - chrome plugin must have loaded extensions (extensions.json must exist)
 */

const path = require('path');
const fs = require('fs');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

// Get crawl's chrome directory from environment variable set by hooks.py
function getCrawlChromeSessionDir() {
    const crawlOutputDir = process.env.CRAWL_OUTPUT_DIR || '';
    if (!crawlOutputDir) {
        return null;
    }
    return path.join(crawlOutputDir, 'chrome');
}

const CHROME_SESSION_DIR = getCrawlChromeSessionDir() || '../chrome';
const CONFIG_MARKER = path.join(CHROME_SESSION_DIR, '.captcha2_configured');

// Get environment variable with default
function getEnv(name, defaultValue = '') {
    return (process.env[name] || defaultValue).trim();
}

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

async function configure2Captcha() {
    // Check if already configured in this session
    if (fs.existsSync(CONFIG_MARKER)) {
        console.error('[*] 2captcha already configured in this browser session');
        return { success: true, skipped: true };
    }

    // Check if API key is set
    const apiKey = getEnv('API_KEY_2CAPTCHA');
    if (!apiKey || apiKey === 'YOUR_API_KEY_HERE') {
        console.warn('[⚠️] 2captcha extension loaded but API_KEY_2CAPTCHA not configured');
        console.warn('[⚠️] Set API_KEY_2CAPTCHA environment variable to enable automatic CAPTCHA solving');
        return { success: false, error: 'API_KEY_2CAPTCHA not configured' };
    }

    // Load extensions metadata
    const extensionsFile = path.join(CHROME_SESSION_DIR, 'extensions.json');
    if (!fs.existsSync(extensionsFile)) {
        return { success: false, error: 'extensions.json not found - chrome plugin must run first' };
    }

    const extensions = JSON.parse(fs.readFileSync(extensionsFile, 'utf-8'));
    const captchaExt = extensions.find(ext => ext.name === 'captcha2');

    if (!captchaExt) {
        console.error('[*] 2captcha extension not installed, skipping configuration');
        return { success: true, skipped: true };
    }

    console.error('[*] Configuring 2captcha extension with API key...');

    try {
        // Connect to the existing Chrome session via CDP
        const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
        if (!fs.existsSync(cdpFile)) {
            return { success: false, error: 'CDP URL not found - chrome plugin must run first' };
        }

        const cdpUrl = fs.readFileSync(cdpFile, 'utf-8').trim();
        const browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

        try {
            // Method 1: Try to inject via extension background page
            if (captchaExt.target && captchaExt.target_ctx) {
                console.error('[*] Attempting to configure via extension background page...');

                // Reconnect to the browser to get fresh target context
                const targets = await browser.targets();
                const extTarget = targets.find(t =>
                    t.url().startsWith(`chrome-extension://${captchaExt.id}`)
                );

                if (extTarget) {
                    const extContext = await extTarget.worker() || await extTarget.page();

                    if (extContext) {
                        await extContext.evaluate((key) => {
                            // Try all common storage patterns
                            if (typeof chrome !== 'undefined' && chrome.storage) {
                                chrome.storage.local.set({
                                    apiKey: key,
                                    api_key: key,
                                    '2captcha_apikey': key,
                                    apikey: key,
                                    'solver-api-key': key,
                                });
                                chrome.storage.sync.set({
                                    apiKey: key,
                                    api_key: key,
                                    '2captcha_apikey': key,
                                    apikey: key,
                                    'solver-api-key': key,
                                });
                            }

                            // Also try localStorage as fallback
                            if (typeof localStorage !== 'undefined') {
                                localStorage.setItem('apiKey', key);
                                localStorage.setItem('2captcha_apikey', key);
                                localStorage.setItem('solver-api-key', key);
                            }
                        }, apiKey);

                        console.error('[+] 2captcha API key configured successfully via background page');

                        // Mark as configured
                        fs.writeFileSync(CONFIG_MARKER, new Date().toISOString());

                        return { success: true, method: 'background_page' };
                    }
                }
            }

            // Method 2: Try to configure via options page
            console.error('[*] Attempting to configure via options page...');
            const optionsUrl = `chrome-extension://${captchaExt.id}/options.html`;
            const configPage = await browser.newPage();

            try {
                await configPage.goto(optionsUrl, { waitUntil: 'networkidle0', timeout: 10000 });

                const configured = await configPage.evaluate((key) => {
                    // Try to find API key input field
                    const selectors = [
                        'input[name*="apikey" i]',
                        'input[id*="apikey" i]',
                        'input[name*="api-key" i]',
                        'input[id*="api-key" i]',
                        'input[name*="key" i]',
                        'input[placeholder*="api" i]',
                        'input[type="text"]',
                    ];

                    for (const selector of selectors) {
                        const input = document.querySelector(selector);
                        if (input) {
                            input.value = key;
                            input.dispatchEvent(new Event('input', { bubbles: true }));
                            input.dispatchEvent(new Event('change', { bubbles: true }));

                            // Try to find and click save button
                            const saveSelectors = [
                                'button[type="submit"]',
                                'input[type="submit"]',
                                'button:contains("Save")',
                                'button:contains("Apply")',
                            ];

                            for (const btnSel of saveSelectors) {
                                const btn = document.querySelector(btnSel);
                                if (btn) {
                                    btn.click();
                                    break;
                                }
                            }

                            // Also save to storage
                            if (typeof chrome !== 'undefined' && chrome.storage) {
                                chrome.storage.local.set({ apiKey: key, api_key: key, '2captcha_apikey': key });
                                chrome.storage.sync.set({ apiKey: key, api_key: key, '2captcha_apikey': key });
                            }

                            return true;
                        }
                    }

                    // Fallback: Just save to storage
                    if (typeof chrome !== 'undefined' && chrome.storage) {
                        chrome.storage.local.set({ apiKey: key, api_key: key, '2captcha_apikey': key });
                        chrome.storage.sync.set({ apiKey: key, api_key: key, '2captcha_apikey': key });
                        return true;
                    }

                    return false;
                }, apiKey);

                await configPage.close();

                if (configured) {
                    console.error('[+] 2captcha API key configured successfully via options page');

                    // Mark as configured
                    fs.writeFileSync(CONFIG_MARKER, new Date().toISOString());

                    return { success: true, method: 'options_page' };
                }
            } catch (e) {
                console.warn(`[⚠️] Failed to configure via options page: ${e.message}`);
                try {
                    await configPage.close();
                } catch (e2) {}
            }

            return { success: false, error: 'Could not configure via any method' };
        } finally {
            browser.disconnect();
        }
    } catch (e) {
        return { success: false, error: `${e.name}: ${e.message}` };
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__21_captcha2_config.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let error = '';

    try {
        const result = await configure2Captcha();

        if (result.skipped) {
            status = 'skipped';
        } else if (result.success) {
            status = 'succeeded';
        } else {
            status = 'failed';
            error = result.error || 'Configuration failed';
        }
    } catch (e) {
        error = `${e.name}: ${e.message}`;
        status = 'failed';
    }

    const endTs = new Date();
    const duration = (endTs - startTs) / 1000;

    if (error) {
        console.error(`ERROR: ${error}`);
    }

    // Config hooks don't emit JSONL - they're utility hooks for setup
    // Exit code indicates success/failure

    process.exit(status === 'succeeded' || status === 'skipped' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
