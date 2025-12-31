#!/usr/bin/env node
/**
 * I Still Don't Care About Cookies Extension Plugin
 *
 * Installs and configures the "I still don't care about cookies" Chrome extension
 * for automatic cookie consent banner dismissal during page archiving.
 *
 * Extension: https://chromewebstore.google.com/detail/edibdbjcniadpccecjdfdjjppcpchdlm
 *
 * Priority: 02 (early) - Must install before Chrome session starts at Crawl level
 * Hook: on_Crawl (runs once per crawl, not per snapshot)
 *
 * This extension automatically:
 * - Dismisses cookie consent popups
 * - Removes cookie banners
 * - Accepts necessary cookies to proceed with browsing
 * - Works on thousands of websites out of the box
 */

// Import extension utilities
const { installExtensionWithCache } = require('../chrome/chrome_utils.js');

// Extension metadata
const EXTENSION = {
    webstore_id: 'edibdbjcniadpccecjdfdjjppcpchdlm',
    name: 'istilldontcareaboutcookies',
};

/**
 * Main entry point - install extension before archiving
 *
 * Note: This extension works out of the box with no configuration needed.
 * It automatically detects and dismisses cookie banners on page load.
 */
async function main() {
    const extension = await installExtensionWithCache(EXTENSION);

    if (extension) {
        console.log('[+] Cookie banners will be automatically dismissed during archiving');
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
        console.log('[✓] I Still Don\'t Care About Cookies extension setup complete');
        process.exit(0);
    }).catch(err => {
        console.error('[❌] I Still Don\'t Care About Cookies extension setup failed:', err);
        process.exit(1);
    });
}
