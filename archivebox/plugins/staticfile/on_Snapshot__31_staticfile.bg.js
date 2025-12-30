#!/usr/bin/env node
/**
 * Detect and download static files using CDP during initial request.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate to capture the
 * Content-Type from the initial response. If it's a static file (PDF, image, etc.),
 * it downloads the content directly using CDP.
 *
 * Usage: on_Snapshot__26_chrome_staticfile.bg.js --url=<url> --snapshot-id=<uuid>
 * Output: Downloads static file + writes hook.pid
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

const PLUGIN_NAME = 'staticfile';
const OUTPUT_DIR = '.';
const PID_FILE = 'hook.pid';
const CHROME_SESSION_DIR = '../chrome';

// Content-Types that indicate static files
const STATIC_CONTENT_TYPES = new Set([
    // Documents
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/rtf',
    'application/epub+zip',
    // Images
    'image/png',
    'image/jpeg',
    'image/gif',
    'image/webp',
    'image/svg+xml',
    'image/x-icon',
    'image/bmp',
    'image/tiff',
    'image/avif',
    'image/heic',
    'image/heif',
    // Audio
    'audio/mpeg',
    'audio/mp3',
    'audio/wav',
    'audio/flac',
    'audio/aac',
    'audio/ogg',
    'audio/webm',
    'audio/m4a',
    'audio/opus',
    // Video
    'video/mp4',
    'video/webm',
    'video/x-matroska',
    'video/avi',
    'video/quicktime',
    'video/x-ms-wmv',
    'video/x-flv',
    // Archives
    'application/zip',
    'application/x-tar',
    'application/gzip',
    'application/x-bzip2',
    'application/x-xz',
    'application/x-7z-compressed',
    'application/x-rar-compressed',
    'application/vnd.rar',
    // Data
    'application/json',
    'application/xml',
    'text/csv',
    'text/xml',
    'application/x-yaml',
    // Executables/Binaries
    'application/octet-stream',
    'application/x-executable',
    'application/x-msdos-program',
    'application/x-apple-diskimage',
    'application/vnd.debian.binary-package',
    'application/x-rpm',
    // Other
    'application/x-bittorrent',
    'application/wasm',
]);

const STATIC_CONTENT_TYPE_PREFIXES = [
    'image/',
    'audio/',
    'video/',
    'application/zip',
    'application/x-',
];

// Global state
let originalUrl = '';
let detectedContentType = null;
let isStaticFile = false;
let downloadedFilePath = null;
let downloadError = null;
let page = null;
let browser = null;

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

async function waitForChromeTabOpen(timeoutMs = 60000) {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    const targetIdFile = path.join(CHROME_SESSION_DIR, 'target_id.txt');
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        if (fs.existsSync(cdpFile) && fs.existsSync(targetIdFile)) {
            return true;
        }
        // Wait 100ms before checking again
        await new Promise(resolve => setTimeout(resolve, 100));
    }

    return false;
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

function isStaticContentType(contentType) {
    if (!contentType) return false;

    const ct = contentType.split(';')[0].trim().toLowerCase();

    // Check exact match
    if (STATIC_CONTENT_TYPES.has(ct)) return true;

    // Check prefixes
    for (const prefix of STATIC_CONTENT_TYPE_PREFIXES) {
        if (ct.startsWith(prefix)) return true;
    }

    return false;
}

function sanitizeFilename(str, maxLen = 200) {
    return str
        .replace(/[^a-zA-Z0-9._-]/g, '_')
        .slice(0, maxLen);
}

function getFilenameFromUrl(url) {
    try {
        const pathname = new URL(url).pathname;
        const filename = path.basename(pathname) || 'downloaded_file';
        return sanitizeFilename(filename);
    } catch (e) {
        return 'downloaded_file';
    }
}

async function setupStaticFileListener() {
    // Wait for chrome tab to be open (up to 60s)
    const tabOpen = await waitForChromeTabOpen(60000);
    if (!tabOpen) {
        throw new Error('Chrome tab not open after 60s (chrome plugin must run first)');
    }

    const cdpUrl = getCdpUrl();
    if (!cdpUrl) {
        throw new Error('No Chrome session found');
    }

    browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

    // Find our page
    const pages = await browser.pages();
    const targetId = getPageId();

    if (targetId) {
        page = pages.find(p => {
            const target = p.target();
            return target && target._targetId === targetId;
        });
    }
    if (!page) {
        page = pages[pages.length - 1];
    }

    if (!page) {
        throw new Error('No page found');
    }

    // Track the first response to check Content-Type
    let firstResponseHandled = false;

    page.on('response', async (response) => {
        if (firstResponseHandled) return;

        try {
            const url = response.url();
            const headers = response.headers();
            const contentType = headers['content-type'] || '';
            const status = response.status();

            // Only process the main document response
            if (url !== originalUrl) return;
            if (status < 200 || status >= 300) return;

            firstResponseHandled = true;
            detectedContentType = contentType.split(';')[0].trim();

            console.error(`Detected Content-Type: ${detectedContentType}`);

            // Check if it's a static file
            if (!isStaticContentType(detectedContentType)) {
                console.error('Not a static file, skipping download');
                return;
            }

            isStaticFile = true;
            console.error('Static file detected, downloading...');

            // Download the file
            const maxSize = getEnvInt('STATICFILE_MAX_SIZE', 1024 * 1024 * 1024); // 1GB default
            const buffer = await response.buffer();

            if (buffer.length > maxSize) {
                downloadError = `File too large: ${buffer.length} bytes > ${maxSize} max`;
                return;
            }

            // Determine filename
            let filename = getFilenameFromUrl(url);

            // Check content-disposition header for better filename
            const contentDisp = headers['content-disposition'] || '';
            if (contentDisp.includes('filename=')) {
                const match = contentDisp.match(/filename[*]?=["']?([^"';\n]+)/);
                if (match) {
                    filename = sanitizeFilename(match[1].trim());
                }
            }

            const outputPath = path.join(OUTPUT_DIR, filename);
            fs.writeFileSync(outputPath, buffer);

            downloadedFilePath = filename;
            console.error(`Static file downloaded (${buffer.length} bytes): ${filename}`);

        } catch (e) {
            downloadError = `${e.name}: ${e.message}`;
            console.error(`Error downloading static file: ${downloadError}`);
        }
    });

    return { browser, page };
}

async function waitForNavigation() {
    // Wait for chrome_navigate to complete
    const navDir = '../chrome';
    const pageLoadedMarker = path.join(navDir, 'page_loaded.txt');
    const maxWait = 120000; // 2 minutes
    const pollInterval = 100;
    let waitTime = 0;

    while (!fs.existsSync(pageLoadedMarker) && waitTime < maxWait) {
        await new Promise(resolve => setTimeout(resolve, pollInterval));
        waitTime += pollInterval;
    }

    if (!fs.existsSync(pageLoadedMarker)) {
        throw new Error('Timeout waiting for navigation (chrome_navigate did not complete)');
    }

    // Wait a bit longer to ensure response handler completes
    await new Promise(resolve => setTimeout(resolve, 500));
}

function handleShutdown(signal) {
    console.error(`\nReceived ${signal}, emitting final results...`);

    let result;

    if (!detectedContentType) {
        // No Content-Type detected (shouldn't happen, but handle it)
        result = {
            type: 'ArchiveResult',
            status: 'skipped',
            output_str: 'No Content-Type detected',
            plugin: PLUGIN_NAME,
        };
    } else if (!isStaticFile) {
        // Not a static file (normal case for HTML pages)
        result = {
            type: 'ArchiveResult',
            status: 'skipped',
            output_str: `Not a static file (Content-Type: ${detectedContentType})`,
            plugin: PLUGIN_NAME,
            content_type: detectedContentType,
        };
    } else if (downloadError) {
        // Static file but download failed
        result = {
            type: 'ArchiveResult',
            status: 'failed',
            output_str: downloadError,
            plugin: PLUGIN_NAME,
            content_type: detectedContentType,
        };
    } else if (downloadedFilePath) {
        // Static file downloaded successfully
        result = {
            type: 'ArchiveResult',
            status: 'succeeded',
            output_str: downloadedFilePath,
            plugin: PLUGIN_NAME,
            content_type: detectedContentType,
        };
    } else {
        // Static file detected but no download happened (unexpected)
        result = {
            type: 'ArchiveResult',
            status: 'failed',
            output_str: 'Static file detected but download did not complete',
            plugin: PLUGIN_NAME,
            content_type: detectedContentType,
        };
    }

    console.log(JSON.stringify(result));
    process.exit(0);
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__26_chrome_staticfile.bg.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    originalUrl = url;

    if (!getEnvBool('STATICFILE_ENABLED', true)) {
        console.error('Skipping (STATICFILE_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'STATICFILE_ENABLED=False'}));
        process.exit(0);
    }

    // Register signal handlers for graceful shutdown
    process.on('SIGTERM', () => handleShutdown('SIGTERM'));
    process.on('SIGINT', () => handleShutdown('SIGINT'));

    try {
        // Set up static file listener BEFORE navigation
        await setupStaticFileListener();

        // Write PID file
        fs.writeFileSync(path.join(OUTPUT_DIR, PID_FILE), String(process.pid));

        // Wait for chrome_navigate to complete (BLOCKING)
        await waitForNavigation();

        // Keep process alive until killed by cleanup
        console.error('Static file detection complete, waiting for cleanup signal...');

        // Keep the process alive indefinitely
        await new Promise(() => {}); // Never resolves

    } catch (e) {
        const error = `${e.name}: ${e.message}`;
        console.error(`ERROR: ${error}`);

        console.log(JSON.stringify({
            type: 'ArchiveResult',
            status: 'failed',
            output_str: error,
        }));
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
