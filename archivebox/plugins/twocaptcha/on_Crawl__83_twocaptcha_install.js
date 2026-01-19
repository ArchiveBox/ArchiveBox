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
 * Priority: 83 - Must install before Chrome session starts at Crawl level
 * Hook: on_Crawl (runs once per crawl, not per snapshot)
 *
 * Requirements:
 * - TWOCAPTCHA_API_KEY environment variable must be set
 * - Extension will automatically solve reCAPTCHA, hCaptcha, Cloudflare Turnstile, etc.
 */

// Import extension utilities
const { installExtensionWithCache } = require('../chrome/chrome_utils.js');

// Extension metadata
const EXTENSION = {
    webstore_id: 'ifibfemgeogfhoebkmokieepdoobkbpo',
    name: 'twocaptcha',
};

/**
 * Main entry point - install extension before archiving
 *
 * Note: 2captcha configuration is handled by on_Crawl__95_twocaptcha_config.js
 * during first-time browser setup to avoid repeated configuration on every snapshot.
 * The API key is injected via chrome.storage API once per browser session.
 */
async function main() {
    const extension = await installExtensionWithCache(EXTENSION);

    if (extension) {
        // Check if API key is configured
        const apiKey = process.env.TWOCAPTCHA_API_KEY || process.env.API_KEY_2CAPTCHA;
        if (!apiKey || apiKey === 'YOUR_API_KEY_HERE') {
            console.warn('[⚠️] 2captcha extension installed but TWOCAPTCHA_API_KEY not configured');
            console.warn('[⚠️] Set TWOCAPTCHA_API_KEY environment variable to enable automatic CAPTCHA solving');
        } else {
            console.log('[+] 2captcha extension installed and API key configured');
        }
    }

    return extension;
}

// Export functions for use by other plugins
module.exports = {
    EXTENSION,
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
