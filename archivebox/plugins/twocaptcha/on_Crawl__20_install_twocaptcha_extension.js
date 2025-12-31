#!/usr/bin/env node
/**
 * 2Captcha Extension Plugin
 *
 * Installs and configures the 2captcha Chrome extension for automatic
 * CAPTCHA solving during page archiving.
 *
 * Extension: https://chromewebstore.google.com/detail/ifibfemgeogfhoebkmokieepdoobkbpo
 * Documentation: https://2captcha.com/blog/how-to-use-2captcha-solver-extension-in-puppeteer
 *
 * Priority: 01 (early) - Must install before Chrome session starts at Crawl level
 * Hook: on_Crawl (runs once per crawl, not per snapshot)
 *
 * Requirements:
 * - API_KEY_2CAPTCHA environment variable must be set
 * - Extension will automatically solve reCAPTCHA, hCaptcha, Cloudflare Turnstile, etc.
 */

const path = require('path');
const fs = require('fs');

// Import extension utilities
const extensionUtils = require('../chrome/chrome_utils.js');

// Extension metadata
const EXTENSION = {
    webstore_id: 'ifibfemgeogfhoebkmokieepdoobkbpo',
    name: 'twocaptcha',
};

// Get extensions directory from environment or use default
const EXTENSIONS_DIR = process.env.CHROME_EXTENSIONS_DIR ||
    path.join(process.env.DATA_DIR || './data', 'personas', process.env.ACTIVE_PERSONA || 'Default', 'chrome_extensions');

/**
 * Install and configure the 2captcha extension
 */
async function installCaptchaExtension() {
    console.log('[*] Installing 2captcha extension...');

    // Install the extension
    const extension = await extensionUtils.loadOrInstallExtension(EXTENSION, EXTENSIONS_DIR);

    if (!extension) {
        console.error('[❌] Failed to install 2captcha extension');
        return null;
    }

    // Check if API key is configured
    const apiKey = process.env.API_KEY_2CAPTCHA;
    if (!apiKey || apiKey === 'YOUR_API_KEY_HERE') {
        console.warn('[⚠️] 2captcha extension installed but API_KEY_2CAPTCHA not configured');
        console.warn('[⚠️] Set API_KEY_2CAPTCHA environment variable to enable automatic CAPTCHA solving');
    } else {
        console.log('[+] 2captcha extension installed and API key configured');
    }

    return extension;
}

/**
 * Note: 2captcha configuration is now handled by chrome plugin
 * during first-time browser setup to avoid repeated configuration on every snapshot.
 * The API key is injected via chrome.storage API once per browser session.
 */

/**
 * Main entry point - install extension before archiving
 */
async function main() {
    // Check if extension is already cached
    const cacheFile = path.join(EXTENSIONS_DIR, 'twocaptcha.extension.json');

    if (fs.existsSync(cacheFile)) {
        try {
            const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf-8'));
            const manifestPath = path.join(cached.unpacked_path, 'manifest.json');

            if (fs.existsSync(manifestPath)) {
                console.log('[*] 2captcha extension already installed (using cache)');
                return cached;
            }
        } catch (e) {
            // Cache file corrupted, re-install
            console.warn('[⚠️] Extension cache corrupted, re-installing...');
        }
    }

    // Install extension
    const extension = await installCaptchaExtension();

    // Export extension metadata for chrome plugin to load
    if (extension) {
        // Write extension info to a cache file that chrome plugin can read
        await fs.promises.mkdir(EXTENSIONS_DIR, { recursive: true });
        await fs.promises.writeFile(
            cacheFile,
            JSON.stringify(extension, null, 2)
        );
        console.log(`[+] Extension metadata written to ${cacheFile}`);
    }

    return extension;
}

// Export functions for use by other plugins
module.exports = {
    EXTENSION,
    installCaptchaExtension,
};

// Run if executed directly
if (require.main === module) {
    main().then(() => {
        console.log('[✓] 2captcha extension setup complete');
        process.exit(0);
    }).catch(err => {
        console.error('[❌] 2captcha extension setup failed:', err);
        process.exit(1);
    });
}
