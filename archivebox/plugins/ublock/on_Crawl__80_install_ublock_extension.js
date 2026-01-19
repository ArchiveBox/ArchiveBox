#!/usr/bin/env node
/**
 * uBlock Origin Extension Plugin
 *
 * Installs and configures the uBlock Origin Chrome extension for ad blocking
 * and privacy protection during page archiving.
 *
 * Extension: https://chromewebstore.google.com/detail/cjpalhdlnbpafiamejdnhcphjbkeiagm
 *
 * Priority: 80 - Must install before Chrome session starts at Crawl level
 * Hook: on_Crawl (runs once per crawl, not per snapshot)
 *
 * This extension automatically:
 * - Blocks ads, trackers, and malware domains
 * - Reduces page load time and bandwidth usage
 * - Improves privacy during archiving
 * - Removes clutter from archived pages
 * - Uses efficient blocking with filter lists
 */

// Import extension utilities
const { installExtensionWithCache } = require('../chrome/chrome_utils.js');

// Extension metadata
const EXTENSION = {
    webstore_id: 'cjpalhdlnbpafiamejdnhcphjbkeiagm',
    name: 'ublock',
};

/**
 * Main entry point - install extension before archiving
 *
 * Note: uBlock Origin works automatically with default filter lists.
 * No configuration needed - blocks ads, trackers, and malware domains out of the box.
 */
async function main() {
    const extension = await installExtensionWithCache(EXTENSION);

    if (extension) {
        console.log('[+] Ads and trackers will be blocked during archiving');
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
        console.log('[✓] uBlock Origin extension setup complete');
        process.exit(0);
    }).catch(err => {
        console.error('[❌] uBlock Origin extension setup failed:', err);
        process.exit(1);
    });
}
