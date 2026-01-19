#!/usr/bin/env node
/**
 * I Still Don't Care About Cookies Extension Plugin
 *
 * Installs and configures the "I still don't care about cookies" Chrome extension
 * for automatic cookie consent banner dismissal during page archiving.
 *
 * Extension: https://chromewebstore.google.com/detail/edibdbjcniadpccecjdfdjjppcpchdlm
 *
 * Priority: 81 - Must install before Chrome session starts at Crawl level
 * Hook: on_Crawl (runs once per crawl, not per snapshot)
 *
 * This extension automatically:
 * - Dismisses cookie consent popups
 * - Removes cookie banners
 * - Accepts necessary cookies to proceed with browsing
 * - Works on thousands of websites out of the box
 */

const path = require('path');
const fs = require('fs');

// Import extension utilities
const extensionUtils = require('../chrome/chrome_utils.js');

// Extension metadata
const EXTENSION = {
    webstore_id: 'edibdbjcniadpccecjdfdjjppcpchdlm',
    name: 'istilldontcareaboutcookies',
};

// Get extensions directory from environment or use default
const EXTENSIONS_DIR = process.env.CHROME_EXTENSIONS_DIR ||
    path.join(process.env.DATA_DIR || './data', 'personas', process.env.ACTIVE_PERSONA || 'Default', 'chrome_extensions');

/**
 * Install the I Still Don't Care About Cookies extension
 */
async function installCookiesExtension() {
    console.log('[*] Installing I Still Don\'t Care About Cookies extension...');

    // Install the extension
    const extension = await extensionUtils.loadOrInstallExtension(EXTENSION, EXTENSIONS_DIR);

    if (!extension) {
        console.error('[❌] Failed to install I Still Don\'t Care About Cookies extension');
        return null;
    }

    console.log('[+] I Still Don\'t Care About Cookies extension installed');
    console.log('[+] Cookie banners will be automatically dismissed during archiving');

    return extension;
}

/**
 * Note: This extension works out of the box with no configuration needed.
 * It automatically detects and dismisses cookie banners on page load.
 */

/**
 * Main entry point - install extension before archiving
 */
async function main() {
    // Check if extension is already cached
    const cacheFile = path.join(EXTENSIONS_DIR, 'istilldontcareaboutcookies.extension.json');

    if (fs.existsSync(cacheFile)) {
        try {
            const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf-8'));
            const manifestPath = path.join(cached.unpacked_path, 'manifest.json');

            if (fs.existsSync(manifestPath)) {
                console.log('[*] I Still Don\'t Care About Cookies extension already installed (using cache)');
                return cached;
            }
        } catch (e) {
            // Cache file corrupted, re-install
            console.warn('[⚠️] Extension cache corrupted, re-installing...');
        }
    }

    // Install extension
    const extension = await installCookiesExtension();

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
    installCookiesExtension,
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
