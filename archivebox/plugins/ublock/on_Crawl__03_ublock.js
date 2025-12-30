#!/usr/bin/env node
/**
 * uBlock Origin Extension Plugin
 *
 * Installs and configures the uBlock Origin Chrome extension for ad blocking
 * and privacy protection during page archiving.
 *
 * Extension: https://chromewebstore.google.com/detail/cjpalhdlnbpafiamejdnhcphjbkeiagm
 *
 * Priority: 03 (early) - Must install before Chrome session starts at Crawl level
 * Hook: on_Crawl (runs once per crawl, not per snapshot)
 *
 * This extension automatically:
 * - Blocks ads, trackers, and malware domains
 * - Reduces page load time and bandwidth usage
 * - Improves privacy during archiving
 * - Removes clutter from archived pages
 * - Uses efficient blocking with filter lists
 */

const path = require('path');
const fs = require('fs');

// Import extension utilities
const extensionUtils = require('../chrome/chrome_utils.js');

// Extension metadata
const EXTENSION = {
    webstore_id: 'cjpalhdlnbpafiamejdnhcphjbkeiagm',
    name: 'ublock',
};

// Get extensions directory from environment or use default
const EXTENSIONS_DIR = process.env.CHROME_EXTENSIONS_DIR ||
    path.join(process.env.DATA_DIR || './data', 'personas', process.env.ACTIVE_PERSONA || 'Default', 'chrome_extensions');

/**
 * Install the uBlock Origin extension
 */
async function installUblockExtension() {
    console.log('[*] Installing uBlock Origin extension...');

    // Install the extension
    const extension = await extensionUtils.loadOrInstallExtension(EXTENSION, EXTENSIONS_DIR);

    if (!extension) {
        console.error('[❌] Failed to install uBlock Origin extension');
        return null;
    }

    console.log('[+] uBlock Origin extension installed');
    console.log('[+] Ads and trackers will be blocked during archiving');

    return extension;
}

/**
 * Note: uBlock Origin works automatically with default filter lists.
 * No configuration needed - blocks ads, trackers, and malware domains out of the box.
 */

/**
 * Main entry point - install extension before archiving
 */
async function main() {
    // Check if extension is already cached
    const cacheFile = path.join(EXTENSIONS_DIR, 'ublock.extension.json');

    if (fs.existsSync(cacheFile)) {
        try {
            const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf-8'));
            const manifestPath = path.join(cached.unpacked_path, 'manifest.json');

            if (fs.existsSync(manifestPath)) {
                console.log('[*] uBlock Origin extension already installed (using cache)');
                return cached;
            }
        } catch (e) {
            // Cache file corrupted, re-install
            console.warn('[⚠️] Extension cache corrupted, re-installing...');
        }
    }

    // Install extension
    const extension = await installUblockExtension();

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
    installUblockExtension,
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
