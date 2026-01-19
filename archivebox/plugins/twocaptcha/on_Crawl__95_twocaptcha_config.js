#!/usr/bin/env node
/**
 * 2Captcha Extension Configuration
 *
 * Configures the 2captcha extension with API key and settings after Crawl-level Chrome session starts.
 * Runs once per crawl to inject configuration into extension storage.
 *
 * Priority: 95 (after chrome_launch at 90, before snapshots start)
 * Hook: on_Crawl (runs once per crawl, not per snapshot)
 *
 * Config Options (from config.json / environment):
 * - TWOCAPTCHA_API_KEY: API key for 2captcha service
 * - TWOCAPTCHA_ENABLED: Enable/disable the extension
 * - TWOCAPTCHA_RETRY_COUNT: Number of retries on error
 * - TWOCAPTCHA_RETRY_DELAY: Delay between retries (seconds)
 * - TWOCAPTCHA_AUTO_SUBMIT: Auto-submit forms after solving
 *
 * Requirements:
 * - TWOCAPTCHA_API_KEY environment variable must be set
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
const CONFIG_MARKER = path.join(CHROME_SESSION_DIR, '.twocaptcha_configured');

// Get environment variable with default
function getEnv(name, defaultValue = '') {
    return (process.env[name] || defaultValue).trim();
}

// Get boolean environment variable
function getEnvBool(name, defaultValue = false) {
    const val = getEnv(name, '').toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(val)) return true;
    if (['false', '0', 'no', 'off'].includes(val)) return false;
    return defaultValue;
}

// Get integer environment variable
function getEnvInt(name, defaultValue = 0) {
    const val = parseInt(getEnv(name, String(defaultValue)), 10);
    return isNaN(val) ? defaultValue : val;
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

/**
 * Get 2captcha configuration from environment variables.
 * Supports both TWOCAPTCHA_* and legacy API_KEY_2CAPTCHA naming.
 */
function getTwoCaptchaConfig() {
    const apiKey = getEnv('TWOCAPTCHA_API_KEY') || getEnv('API_KEY_2CAPTCHA') || getEnv('CAPTCHA2_API_KEY');
    const isEnabled = getEnvBool('TWOCAPTCHA_ENABLED', true);
    const retryCount = getEnvInt('TWOCAPTCHA_RETRY_COUNT', 3);
    const retryDelay = getEnvInt('TWOCAPTCHA_RETRY_DELAY', 5);
    const autoSubmit = getEnvBool('TWOCAPTCHA_AUTO_SUBMIT', false);

    // Build the full config object matching the extension's storage structure
    // Structure: chrome.storage.local.set({config: {...}})
    return {
        // API key - both variants for compatibility
        apiKey: apiKey,
        api_key: apiKey,

        // Plugin enabled state
        isPluginEnabled: isEnabled,

        // Retry settings
        repeatOnErrorTimes: retryCount,
        repeatOnErrorDelay: retryDelay,

        // Auto-submit setting
        autoSubmitForms: autoSubmit,
        submitFormsDelay: 0,

        // Enable all CAPTCHA types
        enabledForNormal: true,
        enabledForRecaptchaV2: true,
        enabledForInvisibleRecaptchaV2: true,
        enabledForRecaptchaV3: true,
        enabledForRecaptchaAudio: false,
        enabledForGeetest: true,
        enabledForGeetest_v4: true,
        enabledForKeycaptcha: true,
        enabledForArkoselabs: true,
        enabledForLemin: true,
        enabledForYandex: true,
        enabledForCapyPuzzle: true,
        enabledForTurnstile: true,
        enabledForAmazonWaf: true,
        enabledForMTCaptcha: true,

        // Auto-solve all CAPTCHA types
        autoSolveNormal: true,
        autoSolveRecaptchaV2: true,
        autoSolveInvisibleRecaptchaV2: true,
        autoSolveRecaptchaV3: true,
        autoSolveRecaptchaAudio: false,
        autoSolveGeetest: true,
        autoSolveGeetest_v4: true,
        autoSolveKeycaptcha: true,
        autoSolveArkoselabs: true,
        autoSolveLemin: true,
        autoSolveYandex: true,
        autoSolveCapyPuzzle: true,
        autoSolveTurnstile: true,
        autoSolveAmazonWaf: true,
        autoSolveMTCaptcha: true,

        // Other settings with sensible defaults
        recaptchaV2Type: 'token',
        recaptchaV3MinScore: 0.3,
        buttonPosition: 'inner',
        useProxy: false,
        proxy: '',
        proxytype: 'HTTP',
        blackListDomain: '',
        autoSubmitRules: [],
        normalSources: [],
    };
}

async function configure2Captcha() {
    // Check if already configured in this session
    if (fs.existsSync(CONFIG_MARKER)) {
        console.error('[*] 2captcha already configured in this browser session');
        return { success: true, skipped: true };
    }

    // Get configuration
    const config = getTwoCaptchaConfig();

    // Check if API key is set
    if (!config.apiKey || config.apiKey === 'YOUR_API_KEY_HERE') {
        console.warn('[!] 2captcha extension loaded but TWOCAPTCHA_API_KEY not configured');
        console.warn('[!] Set TWOCAPTCHA_API_KEY environment variable to enable automatic CAPTCHA solving');
        return { success: false, error: 'TWOCAPTCHA_API_KEY not configured' };
    }

    console.error('[*] Configuring 2captcha extension...');
    console.error(`[*]   API Key: ${config.apiKey.slice(0, 8)}...${config.apiKey.slice(-4)}`);
    console.error(`[*]   Enabled: ${config.isPluginEnabled}`);
    console.error(`[*]   Retry Count: ${config.repeatOnErrorTimes}`);
    console.error(`[*]   Retry Delay: ${config.repeatOnErrorDelay}s`);
    console.error(`[*]   Auto Submit: ${config.autoSubmitForms}`);
    console.error(`[*]   Auto Solve: all CAPTCHA types enabled`);

    try {
        // Connect to the existing Chrome session via CDP
        const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
        if (!fs.existsSync(cdpFile)) {
            return { success: false, error: 'CDP URL not found - chrome plugin must run first' };
        }

        const cdpUrl = fs.readFileSync(cdpFile, 'utf-8').trim();
        const browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

        try {
            // First, navigate to a page to trigger extension content scripts and wake up service worker
            console.error('[*] Waking up extension by visiting a page...');
            const triggerPage = await browser.newPage();
            try {
                await triggerPage.goto('https://www.google.com', { waitUntil: 'domcontentloaded', timeout: 10000 });
                await new Promise(r => setTimeout(r, 3000)); // Give extension time to initialize
            } catch (e) {
                console.warn(`[!] Trigger page failed: ${e.message}`);
            }
            try { await triggerPage.close(); } catch (e) {}

            // Get 2captcha extension info from extensions.json
            const extensionsFile = path.join(CHROME_SESSION_DIR, 'extensions.json');
            if (!fs.existsSync(extensionsFile)) {
                return { success: false, error: 'extensions.json not found - chrome plugin must run first' };
            }

            const extensions = JSON.parse(fs.readFileSync(extensionsFile, 'utf-8'));
            const captchaExt = extensions.find(ext => ext.name === 'twocaptcha');

            if (!captchaExt) {
                console.error('[*] 2captcha extension not installed, skipping configuration');
                return { success: true, skipped: true };
            }

            if (!captchaExt.id) {
                return { success: false, error: '2captcha extension ID not found in extensions.json' };
            }

            const extensionId = captchaExt.id;
            console.error(`[*] 2captcha Extension ID: ${extensionId}`);

            // Configure via options page
            console.error('[*] Configuring via options page...');
            const optionsUrl = `chrome-extension://${extensionId}/options/options.html`;

            let configPage = await browser.newPage();

            try {
                // Navigate to options page - catch error but continue since page may still load
                try {
                    await configPage.goto(optionsUrl, { waitUntil: 'networkidle0', timeout: 10000 });
                } catch (navError) {
                    // Navigation may throw ERR_BLOCKED_BY_CLIENT but page still loads
                    console.error(`[*] Navigation threw error (may still work): ${navError.message}`);
                }

                // Wait a moment for page to settle
                await new Promise(r => setTimeout(r, 3000));

                // Check all pages for the extension page (Chrome may open it in a different tab)
                const pages = await browser.pages();
                for (const page of pages) {
                    const url = page.url();
                    if (url.startsWith(`chrome-extension://${extensionId}`)) {
                        configPage = page;
                        break;
                    }
                }

                const currentUrl = configPage.url();
                console.error(`[*] Current URL: ${currentUrl}`);

                if (!currentUrl.startsWith(`chrome-extension://${extensionId}`)) {
                    return { success: false, error: `Failed to navigate to options page, got: ${currentUrl}` };
                }

                // Wait for Config object to be available
                console.error('[*] Waiting for Config object...');
                await configPage.waitForFunction(() => typeof Config !== 'undefined', { timeout: 10000 });

                // Use chrome.storage.local.set with the config wrapper
                const result = await configPage.evaluate((cfg) => {
                    return new Promise((resolve) => {
                        if (typeof chrome !== 'undefined' && chrome.storage) {
                            chrome.storage.local.set({ config: cfg }, () => {
                                if (chrome.runtime.lastError) {
                                    resolve({ success: false, error: chrome.runtime.lastError.message });
                                } else {
                                    resolve({ success: true, method: 'options_page' });
                                }
                            });
                        } else {
                            resolve({ success: false, error: 'chrome.storage not available' });
                        }
                    });
                }, config);

                if (result.success) {
                    console.error(`[+] 2captcha configured via ${result.method}`);

                    // Verify config was applied by reloading options page and checking form values
                    console.error('[*] Verifying config by reloading options page...');
                    try {
                        await configPage.reload({ waitUntil: 'networkidle0', timeout: 10000 });
                    } catch (e) {
                        console.error(`[*] Reload threw error (may still work): ${e.message}`);
                    }

                    await new Promise(r => setTimeout(r, 2000));

                    // Wait for Config object again
                    await configPage.waitForFunction(() => typeof Config !== 'undefined', { timeout: 10000 });

                    // Read back the config using Config.getAll()
                    const verifyConfig = await configPage.evaluate(async () => {
                        if (typeof Config !== 'undefined' && typeof Config.getAll === 'function') {
                            return await Config.getAll();
                        }
                        return null;
                    });

                    if (!verifyConfig) {
                        return { success: false, error: 'Could not verify config - Config.getAll() not available' };
                    }

                    // Check that API key was actually set
                    const actualApiKey = verifyConfig.apiKey || verifyConfig.api_key;
                    if (!actualApiKey || actualApiKey !== config.apiKey) {
                        console.error(`[!] Config verification FAILED - API key mismatch`);
                        console.error(`[!]   Expected: ${config.apiKey.slice(0, 8)}...${config.apiKey.slice(-4)}`);
                        console.error(`[!]   Got: ${actualApiKey ? actualApiKey.slice(0, 8) + '...' + actualApiKey.slice(-4) : 'null'}`);
                        return { success: false, error: 'Config verification failed - API key not set correctly' };
                    }

                    console.error('[+] Config verified successfully!');
                    console.error(`[+]   API Key: ${actualApiKey.slice(0, 8)}...${actualApiKey.slice(-4)}`);
                    console.error(`[+]   Plugin Enabled: ${verifyConfig.isPluginEnabled}`);
                    console.error(`[+]   Auto Solve Turnstile: ${verifyConfig.autoSolveTurnstile}`);

                    fs.writeFileSync(CONFIG_MARKER, JSON.stringify({
                        timestamp: new Date().toISOString(),
                        method: result.method,
                        extensionId: extensionId,
                        verified: true,
                        config: {
                            apiKeySet: !!config.apiKey,
                            isPluginEnabled: config.isPluginEnabled,
                            repeatOnErrorTimes: config.repeatOnErrorTimes,
                            repeatOnErrorDelay: config.repeatOnErrorDelay,
                            autoSubmitForms: config.autoSubmitForms,
                            autoSolveEnabled: true,
                        }
                    }, null, 2));
                    return { success: true, method: result.method, verified: true };
                }

                return { success: false, error: result.error || 'Config failed' };
            } finally {
                try { await configPage.close(); } catch (e) {}
            }
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
        console.error('Usage: on_Crawl__95_twocaptcha_config.js --url=<url> --snapshot-id=<uuid>');
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
