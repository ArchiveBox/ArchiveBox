#!/usr/bin/env node
/**
 * Download 3D/CAD asset files from a page using Chrome + Puppeteer.
 *
 * This plugin uses the existing Chrome session (with logged-in user state)
 * to download 3D/CAD files, which is necessary for sites that require
 * authentication or captcha solving (e.g., Thingiverse, Thangs).
 *
 * Usage: on_Snapshot__65_caddl.bg.js --url=<url> --snapshot-id=<uuid>
 * Output: Downloads 3D/CAD files to $PWD/caddl/
 *
 * Environment variables:
 *     CADDL_ENABLED: Enable CAD/3D asset extraction (default: True)
 *     CADDL_TIMEOUT: Timeout in seconds (x-fallback: TIMEOUT)
 *     CADDL_MAX_SIZE: Maximum file size (default: 750m)
 *     CADDL_EXTENSIONS: JSON array of file extensions to download
 */

function getEnv(name, defaultValue = '') {
    return (process.env[name] || defaultValue).trim();
}

function getEnvBool(name, defaultValue = false) {
    const val = getEnv(name, '').toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(val)) return true;
    if (['false', '0', 'no', 'off'].includes(val)) return false;
    return defaultValue;
}

function getEnvInt(name, defaultValue = 0) {
    const val = parseInt(getEnv(name, String(defaultValue)), 10);
    return isNaN(val) ? defaultValue : val;
}

function getEnvArray(name, defaultValue = []) {
    const val = getEnv(name, '');
    if (!val) return defaultValue;
    try {
        const result = JSON.parse(val);
        return Array.isArray(result) ? result.map(String) : defaultValue;
    } catch {
        return defaultValue;
    }
}

// Check if caddl is enabled BEFORE requiring puppeteer
if (!getEnvBool('CADDL_ENABLED', true)) {
    console.error('Skipping caddl (CADDL_ENABLED=False)');
    process.exit(0);
}

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const PLUGIN_NAME = 'caddl';
const CHROME_SESSION_DIR = '../chrome';
const OUTPUT_DIR = '.';

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

function getCdpUrl() {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    if (fs.existsSync(cdpFile)) {
        return fs.readFileSync(cdpFile, 'utf8').trim();
    }
    return null;
}

function getPageId() {
    const targetIdFile = path.join(CHROME_SESSION_DIR, 'target_id.txt');
    if (fs.existsSync(targetIdFile)) {
        return fs.readFileSync(targetIdFile, 'utf8').trim();
    }
    return null;
}

async function waitForChromeTabLoaded(timeoutMs = 60000) {
    const navigationFile = path.join(CHROME_SESSION_DIR, 'navigation.json');
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        if (fs.existsSync(navigationFile)) {
            return true;
        }
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    return false;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function parseSizeLimit(sizeStr) {
    if (!sizeStr) return 750 * 1024 * 1024; // Default 750MB

    sizeStr = sizeStr.toLowerCase().trim();
    const multipliers = { k: 1024, m: 1024**2, g: 1024**3 };

    const lastChar = sizeStr[sizeStr.length - 1];
    if (multipliers[lastChar]) {
        const num = parseFloat(sizeStr.slice(0, -1));
        return isNaN(num) ? 750 * 1024 * 1024 : Math.floor(num * multipliers[lastChar]);
    }

    const num = parseInt(sizeStr, 10);
    return isNaN(num) ? 750 * 1024 * 1024 : num;
}

function sanitizeFilename(filename) {
    // Remove path components and sanitize
    filename = path.basename(filename);
    filename = filename.replace(/[^\w\-_.]/g, '_');

    // Reject dangerous filenames
    if (!filename || filename === '.' || filename === '..') {
        return 'asset.bin';
    }

    return filename;
}

async function findCadUrls(page, extensions) {
    /**
     * Find all URLs on the page that point to 3D/CAD files.
     * Returns array of absolute URLs.
     */
    const urls = await page.evaluate((exts) => {
        const found = new Set();
        const extensionsLower = exts.map(e => e.toLowerCase());

        // Find in href and src attributes
        const links = document.querySelectorAll('a[href], link[href], [src]');
        links.forEach(el => {
            const url = el.href || el.src;
            if (!url) return;

            const urlLower = url.toLowerCase();
            if (extensionsLower.some(ext => urlLower.endsWith(ext))) {
                found.add(url);
            }
        });

        // Find in text content
        const bodyText = document.body.innerText || '';
        const urlPattern = /https?:\/\/[^\s<>"']+/gi;
        const matches = bodyText.match(urlPattern) || [];
        matches.forEach(url => {
            const urlLower = url.toLowerCase();
            if (extensionsLower.some(ext => urlLower.endsWith(ext))) {
                found.add(url);
            }
        });

        return Array.from(found);
    }, extensions);

    return urls;
}

async function downloadFile(page, url, outputDir, maxSize) {
    /**
     * Download a file using the Chrome session.
     * Returns: { success: bool, outputPath: string|null, error: string }
     */
    try {
        // Get filename from URL
        const urlObj = new URL(url);
        let filename = path.basename(urlObj.pathname);
        filename = sanitizeFilename(filename);

        let outputPath = path.join(outputDir, filename);

        // Avoid overwriting existing files
        let counter = 1;
        while (fs.existsSync(outputPath)) {
            const ext = path.extname(filename);
            const base = path.basename(filename, ext);
            outputPath = path.join(outputDir, `${base}_${counter}${ext}`);
            counter++;
        }

        // Use CDP to download the file
        const client = await page.target().createCDPSession();

        // Set download behavior
        await client.send('Page.setDownloadBehavior', {
            behavior: 'allow',
            downloadPath: path.resolve(outputDir)
        });

        // Navigate to the URL in a new page to trigger download
        // This uses the authenticated session
        const browser = page.browser();
        const downloadPage = await browser.newPage();

        try {
            // Set a response handler to check file size
            let responseReceived = false;
            let sizeExceeded = false;
            let sizeExceededError = null;

            downloadPage.on('response', response => {
                if (response.url() === url) {
                    responseReceived = true;
                    const headers = response.headers();
                    const contentLength = headers['content-length'];
                    if (contentLength && parseInt(contentLength, 10) > maxSize) {
                        sizeExceeded = true;
                        sizeExceededError = `File exceeds max size limit (${contentLength} > ${maxSize})`;
                        // Close the page to abort the download
                        downloadPage.close().catch(() => {});
                    }
                }
            });

            // Navigate to URL to trigger download
            await downloadPage.goto(url, {
                waitUntil: 'networkidle0',
                timeout: 60000
            });

            // Check if size was exceeded
            if (sizeExceeded) {
                return { success: false, outputPath: null, error: sizeExceededError };
            }

            // Wait a bit for download to start
            await sleep(2000);

            await downloadPage.close();

            // Check if file was downloaded
            if (fs.existsSync(outputPath)) {
                const stats = fs.statSync(outputPath);
                if (stats.size > maxSize) {
                    fs.unlinkSync(outputPath);
                    return { success: false, outputPath: null, error: 'File exceeds max size limit' };
                }
                return { success: true, outputPath, error: '' };
            } else {
                // File might have been downloaded with a different name by Chrome
                // Try to find it in the output directory
                const files = fs.readdirSync(outputDir);
                const recentFiles = files
                    .filter(f => {
                        const fpath = path.join(outputDir, f);
                        const stats = fs.statSync(fpath);
                        return stats.isFile() && (Date.now() - stats.mtimeMs < 5000);
                    })
                    .sort((a, b) => {
                        const aStats = fs.statSync(path.join(outputDir, a));
                        const bStats = fs.statSync(path.join(outputDir, b));
                        return bStats.mtimeMs - aStats.mtimeMs;
                    });

                if (recentFiles.length > 0) {
                    const downloadedFile = path.join(outputDir, recentFiles[0]);
                    const stats = fs.statSync(downloadedFile);
                    if (stats.size > maxSize) {
                        fs.unlinkSync(downloadedFile);
                        return { success: false, outputPath: null, error: 'File exceeds max size limit' };
                    }
                    // Rename to expected filename
                    fs.renameSync(downloadedFile, outputPath);
                    return { success: true, outputPath, error: '' };
                }

                return { success: false, outputPath: null, error: 'Download failed - file not found' };
            }
        } finally {
            if (!downloadPage.isClosed()) {
                await downloadPage.close();
            }
        }

    } catch (e) {
        return { success: false, outputPath: null, error: `${e.name}: ${e.message}` };
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__65_caddl.bg.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const timeout = (getEnvInt('CADDL_TIMEOUT') || getEnvInt('TIMEOUT', 300)) * 1000;
    const maxSizeStr = getEnv('CADDL_MAX_SIZE', '750m');
    const maxSize = parseSizeLimit(maxSizeStr);
    const extensions = getEnvArray('CADDL_EXTENSIONS', [
        '.blend', '.stl', '.obj', '.step', '.stp',
        '.gltf', '.glb', '.fbx', '.vrm', '.usdz',
        '.dae', '.3ds', '.ply', '.off', '.x3d'
    ]);

    const cdpUrl = getCdpUrl();
    if (!cdpUrl) {
        console.error('ERROR: Chrome CDP URL not found (chrome plugin must run first)');
        process.exit(1);
    }

    // Wait for page to be loaded
    const pageLoaded = await waitForChromeTabLoaded(60000);
    if (!pageLoaded) {
        console.error('ERROR: Page not loaded after 60s (chrome_navigate must complete first)');
        process.exit(1);
    }

    // Create output directory
    const outputDir = path.resolve(OUTPUT_DIR);
    if (!fs.existsSync(outputDir)) {
        fs.mkdirSync(outputDir, { recursive: true });
    }

    let browser = null;
    try {
        browser = await puppeteer.connect({
            browserWSEndpoint: cdpUrl,
            timeout: timeout
        });

        const pages = await browser.pages();
        if (pages.length === 0) {
            throw new Error('No pages found in browser');
        }

        // Find the right page by target ID
        const targetId = getPageId();
        let page = null;
        if (targetId) {
            page = pages.find(p => {
                const target = p.target();
                return target && target._targetId === targetId;
            });
        }
        if (!page) {
            page = pages[pages.length - 1];
        }

        console.error(`Finding CAD/3D assets on ${url}`);

        // Find CAD URLs on the page
        const cadUrls = await findCadUrls(page, extensions);

        if (cadUrls.length === 0) {
            console.error('No CAD/3D assets found on page');
            browser.disconnect();
            console.log(JSON.stringify({
                type: 'ArchiveResult',
                status: 'succeeded',
                output_str: ''
            }));
            process.exit(0);
        }

        console.error(`Found ${cadUrls.length} CAD/3D asset(s): ${cadUrls.join(', ')}`);

        // Download each file
        const downloaded = [];
        const errors = [];

        for (const cadUrl of cadUrls) {
            console.error(`Downloading ${cadUrl}...`);
            const result = await downloadFile(page, cadUrl, outputDir, maxSize);

            if (result.success && result.outputPath) {
                downloaded.push(result.outputPath);
                console.error(`✓ Downloaded to ${result.outputPath}`);
            } else if (result.error) {
                errors.push(`${cadUrl}: ${result.error}`);
                console.error(`✗ Failed: ${result.error}`);
            }
        }

        browser.disconnect();

        // Emit results
        if (downloaded.length > 0) {
            for (const outputPath of downloaded) {
                console.log(JSON.stringify({
                    type: 'ArchiveResult',
                    status: 'succeeded',
                    output_str: outputPath
                }));
            }
            console.error(`Success: Downloaded ${downloaded.length} file(s)`);
            process.exit(0);
        } else if (errors.length > 0) {
            console.error(`ERROR: All downloads failed: ${errors.slice(0, 3).join('; ')}`);
            process.exit(1);
        } else {
            console.log(JSON.stringify({
                type: 'ArchiveResult',
                status: 'succeeded',
                output_str: ''
            }));
            process.exit(0);
        }

    } catch (e) {
        if (browser) browser.disconnect();
        console.error(`ERROR: ${e.name}: ${e.message}`);
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
