#!/usr/bin/env node
/**
 * SingleFile Extension Plugin
 *
 * Installs and uses the SingleFile Chrome extension for archiving complete web pages.
 * Falls back to single-file-cli if the extension is not available.
 *
 * Extension: https://chromewebstore.google.com/detail/mpiodijhokgodhhofbcjdecpffjipkle
 *
 * Priority: 04 (early) - Must install before Chrome session starts at Crawl level
 * Hook: on_Crawl (runs once per crawl, not per snapshot)
 *
 * This extension automatically:
 * - Saves complete web pages as single HTML files
 * - Inlines all resources (CSS, JS, images, fonts)
 * - Preserves page fidelity better than wget/curl
 * - Works with SPAs and dynamically loaded content
 */

const path = require('path');
const fs = require('fs');
const { promisify } = require('util');
const { exec } = require('child_process');

const execAsync = promisify(exec);

// Import extension utilities
const extensionUtils = require('../chrome/chrome_utils.js');

// Extension metadata
const EXTENSION = {
    webstore_id: 'mpiodijhokgodhhofbcjdecpffjipkle',
    name: 'singlefile',
};

// Get extensions directory from environment or use default
const EXTENSIONS_DIR = process.env.CHROME_EXTENSIONS_DIR ||
    path.join(process.env.DATA_DIR || './data', 'personas', process.env.ACTIVE_PERSONA || 'Default', 'chrome_extensions');

const CHROME_DOWNLOADS_DIR = process.env.CHROME_DOWNLOADS_DIR ||
    path.join(process.env.DATA_DIR || './data', 'personas', process.env.ACTIVE_PERSONA || 'Default', 'chrome_downloads');

const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'singlefile.html';

/**
 * Install the SingleFile extension
 */
async function installSinglefileExtension() {
    console.log('[*] Installing SingleFile extension...');

    // Install the extension
    const extension = await extensionUtils.loadOrInstallExtension(EXTENSION, EXTENSIONS_DIR);

    if (!extension) {
        console.error('[❌] Failed to install SingleFile extension');
        return null;
    }

    console.log('[+] SingleFile extension installed');
    console.log('[+] Web pages will be saved as single HTML files');

    return extension;
}

/**
 * Wait for a specified amount of time
 */
function wait(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Save a page using the SingleFile extension
 *
 * @param {Object} page - Puppeteer page object
 * @param {Object} extension - Extension metadata with dispatchAction method
 * @param {Object} options - Additional options
 * @returns {Promise<string|null>} - Path to saved file or null on failure
 */
async function saveSinglefileWithExtension(page, extension, options = {}) {
    if (!extension || !extension.version) {
        throw new Error('SingleFile extension not found or not loaded');
    }

    const url = await page.url();

    // Check for unsupported URL schemes
    const URL_SCHEMES_IGNORED = ['about', 'chrome', 'chrome-extension', 'data', 'javascript', 'blob'];
    const scheme = url.split(':')[0];
    if (URL_SCHEMES_IGNORED.includes(scheme)) {
        console.log(`[⚠️] Skipping SingleFile for URL scheme: ${scheme}`);
        return null;
    }

    // Ensure downloads directory exists
    await fs.promises.mkdir(CHROME_DOWNLOADS_DIR, { recursive: true });

    // Get list of existing files to ignore
    const files_before = new Set(
        (await fs.promises.readdir(CHROME_DOWNLOADS_DIR))
            .filter(fn => fn.endsWith('.html'))
    );

    // Output directory is current directory (hook already runs in output dir)
    const out_path = path.join(OUTPUT_DIR, OUTPUT_FILE);

    console.log(`[🛠️] Saving SingleFile HTML using extension (${extension.id})...`);

    // Bring page to front (extension action button acts on foreground tab)
    await page.bringToFront();

    // Trigger the extension's action (toolbar button click)
    await extension.dispatchAction();

    // Wait for file to appear in downloads directory
    const check_delay = 3000; // 3 seconds
    const max_tries = 10;
    let files_new = [];

    for (let attempt = 0; attempt < max_tries; attempt++) {
        await wait(check_delay);

        const files_after = (await fs.promises.readdir(CHROME_DOWNLOADS_DIR))
            .filter(fn => fn.endsWith('.html'));

        files_new = files_after.filter(file => !files_before.has(file));

        if (files_new.length === 0) {
            continue;
        }

        // Find the matching file by checking if it contains the URL in the HTML header
        for (const file of files_new) {
            const dl_path = path.join(CHROME_DOWNLOADS_DIR, file);
            const dl_text = await fs.promises.readFile(dl_path, 'utf-8');
            const dl_header = dl_text.split('meta charset')[0];

            if (dl_header.includes(`url: ${url}`)) {
                console.log(`[✍️] Moving SingleFile download from ${file} to ${out_path}`);
                await fs.promises.rename(dl_path, out_path);
                return out_path;
            }
        }
    }

    console.warn(`[❌] Couldn't find matching SingleFile HTML in ${CHROME_DOWNLOADS_DIR} after waiting ${(check_delay * max_tries) / 1000}s`);
    console.warn(`[⚠️] New files found: ${files_new.join(', ')}`);
    return null;
}

/**
 * Save a page using single-file-cli (fallback method)
 *
 * @param {string} url - URL to archive
 * @param {Object} options - Additional options
 * @returns {Promise<string|null>} - Path to saved file or null on failure
 */
async function saveSinglefileWithCLI(url, options = {}) {
    console.log('[*] Falling back to single-file-cli...');

    // Find single-file binary
    let binary = null;
    try {
        const { stdout } = await execAsync('which single-file');
        binary = stdout.trim();
    } catch (err) {
        console.error('[❌] single-file-cli not found. Install with: npm install -g single-file-cli');
        return null;
    }

    // Output directory is current directory (hook already runs in output dir)
    const out_path = path.join(OUTPUT_DIR, OUTPUT_FILE);

    // Build command
    const cmd = [
        binary,
        '--browser-headless',
        url,
        out_path,
    ];

    // Add optional args
    if (options.userAgent) {
        cmd.splice(2, 0, '--browser-user-agent', options.userAgent);
    }
    if (options.cookiesFile && fs.existsSync(options.cookiesFile)) {
        cmd.splice(2, 0, '--browser-cookies-file', options.cookiesFile);
    }
    if (options.ignoreSSL) {
        cmd.splice(2, 0, '--browser-ignore-insecure-certs');
    }

    // Execute
    try {
        const timeout = options.timeout || 120000;
        await execAsync(cmd.join(' '), { timeout });

        if (fs.existsSync(out_path) && fs.statSync(out_path).size > 0) {
            console.log(`[+] SingleFile saved via CLI: ${out_path}`);
            return out_path;
        }

        console.error('[❌] SingleFile CLI completed but no output file found');
        return null;
    } catch (err) {
        console.error(`[❌] SingleFile CLI error: ${err.message}`);
        return null;
    }
}

/**
 * Main entry point - install extension before archiving
 */
async function main() {
    // Check if extension is already cached
    const cacheFile = path.join(EXTENSIONS_DIR, 'singlefile.extension.json');

    if (fs.existsSync(cacheFile)) {
        try {
            const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf-8'));
            const manifestPath = path.join(cached.unpacked_path, 'manifest.json');

            if (fs.existsSync(manifestPath)) {
                console.log('[*] SingleFile extension already installed (using cache)');
                return cached;
            }
        } catch (e) {
            // Cache file corrupted, re-install
            console.warn('[⚠️] Extension cache corrupted, re-installing...');
        }
    }

    // Install extension
    const extension = await installSinglefileExtension();

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
    installSinglefileExtension,
    saveSinglefileWithExtension,
    saveSinglefileWithCLI,
};

// Run if executed directly
if (require.main === module) {
    main().then(() => {
        console.log('[✓] SingleFile extension setup complete');
        process.exit(0);
    }).catch(err => {
        console.error('[❌] SingleFile extension setup failed:', err);
        process.exit(1);
    });
}
