#!/usr/bin/env node
/**
 * SingleFile Extension Plugin
 *
 * Installs and uses the SingleFile Chrome extension for archiving complete web pages.
 * Falls back to single-file-cli if the extension is not available.
 *
 * Extension: https://chromewebstore.google.com/detail/mpiodijhokgodhhofbcjdecpffjipkle
 *
 * Priority: 82 - Must install before Chrome session starts at Crawl level
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
    console.error(`[singlefile] Triggering extension for: ${url}`);

    // Check for unsupported URL schemes
    const URL_SCHEMES_IGNORED = ['about', 'chrome', 'chrome-extension', 'data', 'javascript', 'blob'];
    const scheme = url.split(':')[0];
    if (URL_SCHEMES_IGNORED.includes(scheme)) {
        console.log(`[⚠️] Skipping SingleFile for URL scheme: ${scheme}`);
        return null;
    }

    const downloadsDir = options.downloadsDir || CHROME_DOWNLOADS_DIR;
    console.error(`[singlefile] Watching downloads dir: ${downloadsDir}`);

    // Ensure downloads directory exists
    await fs.promises.mkdir(downloadsDir, { recursive: true });

    // Get list of existing files to ignore
    const files_before = new Set(
        (await fs.promises.readdir(downloadsDir))
            .filter(fn => fn.toLowerCase().endsWith('.html') || fn.toLowerCase().endsWith('.htm'))
    );

    // Output directory is current directory (hook already runs in output dir)
    const out_path = path.join(OUTPUT_DIR, OUTPUT_FILE);

    console.error(`[singlefile] Saving via extension (${extension.id})...`);

    // Bring page to front (extension action button acts on foreground tab)
    await page.bringToFront();

    // Trigger the extension's action (toolbar button click)
    console.error('[singlefile] Dispatching extension action...');
    try {
        const actionTimeoutMs = options.actionTimeoutMs || 5000;
        const actionPromise = extension.dispatchAction();
        const actionResult = await Promise.race([
            actionPromise,
            wait(actionTimeoutMs).then(() => 'timeout'),
        ]);
        if (actionResult === 'timeout') {
            console.error(`[singlefile] Extension action did not resolve within ${actionTimeoutMs}ms, continuing...`);
        }
    } catch (err) {
        console.error(`[singlefile] Extension action error: ${err.message || err}`);
    }

    // Wait for file to appear in downloads directory
    const check_delay = 3000; // 3 seconds
    const max_tries = 10;
    let files_new = [];

    console.error(`[singlefile] Waiting up to ${(check_delay * max_tries) / 1000}s for download...`);
    for (let attempt = 0; attempt < max_tries; attempt++) {
        await wait(check_delay);

        const files_after = (await fs.promises.readdir(downloadsDir))
            .filter(fn => fn.toLowerCase().endsWith('.html') || fn.toLowerCase().endsWith('.htm'));

        files_new = files_after.filter(file => !files_before.has(file));

        if (files_new.length === 0) {
            console.error(`[singlefile] No new downloads yet (${attempt + 1}/${max_tries})`);
            continue;
        }

        console.error(`[singlefile] New download(s) detected: ${files_new.join(', ')}`);

        // Prefer files that match the URL or have SingleFile markers
        const url_variants = new Set([url]);
        if (url.endsWith('/')) {
            url_variants.add(url.slice(0, -1));
        } else {
            url_variants.add(`${url}/`);
        }

        const scored = [];
        for (const file of files_new) {
            const dl_path = path.join(downloadsDir, file);
            let header = '';
            try {
                const dl_text = await fs.promises.readFile(dl_path, 'utf-8');
                header = dl_text.slice(0, 200000);
                const stat = await fs.promises.stat(dl_path);
                console.error(`[singlefile] Download ${file} size=${stat.size} bytes`);
            } catch (err) {
                // Skip unreadable files
                continue;
            }

            const header_lower = header.toLowerCase();
            const has_url = Array.from(url_variants).some(v => header.includes(v));
            const has_singlefile_marker = header_lower.includes('singlefile') || header_lower.includes('single-file');
            const score = (has_url ? 2 : 0) + (has_singlefile_marker ? 1 : 0);
            scored.push({ file, dl_path, score });
        }

        scored.sort((a, b) => b.score - a.score);

        if (scored.length > 0) {
            const best = scored[0];
            if (best.score > 0 || files_new.length === 1) {
                console.error(`[singlefile] Moving download from ${best.file} -> ${out_path}`);
                await fs.promises.rename(best.dl_path, out_path);
                const out_stat = await fs.promises.stat(out_path);
                console.error(`[singlefile] Moved file size=${out_stat.size} bytes`);
                return out_path;
            }
        }

        if (files_new.length > 0) {
            // Fallback: move the newest file if no clear match found
            let newest = null;
            let newest_mtime = -1;
            for (const file of files_new) {
                const dl_path = path.join(downloadsDir, file);
                try {
                    const stat = await fs.promises.stat(dl_path);
                    if (stat.mtimeMs > newest_mtime) {
                        newest_mtime = stat.mtimeMs;
                        newest = { file, dl_path };
                    }
                } catch (err) {}
            }
            if (newest) {
                console.error(`[singlefile] Moving newest download from ${newest.file} -> ${out_path}`);
                await fs.promises.rename(newest.dl_path, out_path);
                const out_stat = await fs.promises.stat(out_path);
                console.error(`[singlefile] Moved file size=${out_stat.size} bytes`);
                return out_path;
            }
        }
    }

    console.error(`[singlefile] Failed to find SingleFile HTML in ${downloadsDir} after ${(check_delay * max_tries) / 1000}s`);
    console.error(`[singlefile] New files seen: ${files_new.join(', ')}`);
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
