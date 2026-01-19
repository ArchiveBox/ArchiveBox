#!/usr/bin/env node
/**
 * Detect and download static files using CDP during initial request.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate to capture the
 * Content-Type from the initial response. If it's a static file (PDF, image, etc.),
 * it downloads the content directly using CDP.
 *
 * Usage: on_Snapshot__26_staticfile.bg.js --url=<url> --snapshot-id=<uuid>
 * Output: Downloads static file
 */

const fs = require('fs');
const path = require('path');

// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const puppeteer = require('puppeteer-core');

// Import shared utilities from chrome_utils.js
const {
    getEnvBool,
    getEnvInt,
    parseArgs,
    connectToPage,
    waitForPageLoaded,
} = require('../chrome/chrome_utils.js');

const PLUGIN_NAME = 'staticfile';
const OUTPUT_DIR = '.';
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
    const timeout = getEnvInt('STATICFILE_TIMEOUT', 30) * 1000;

    // Connect to Chrome page using shared utility
    const connection = await connectToPage({
        chromeSessionDir: CHROME_SESSION_DIR,
        timeoutMs: timeout,
        puppeteer,
    });
    browser = connection.browser;
    page = connection.page;

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
        console.error('Usage: on_Snapshot__26_staticfile.bg.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    originalUrl = url;

    if (!getEnvBool('STATICFILE_ENABLED', true)) {
        console.error('Skipping (STATICFILE_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'STATICFILE_ENABLED=False'}));
        process.exit(0);
    }

    const timeout = getEnvInt('STATICFILE_TIMEOUT', 30) * 1000;

    // Register signal handlers for graceful shutdown
    process.on('SIGTERM', () => handleShutdown('SIGTERM'));
    process.on('SIGINT', () => handleShutdown('SIGINT'));

    try {
        // Set up static file listener BEFORE navigation
        await setupStaticFileListener();

        // Wait for chrome_navigate to complete (non-fatal)
        try {
            await waitForPageLoaded(CHROME_SESSION_DIR, timeout * 4, 500);
        } catch (e) {
            console.error(`WARN: ${e.message}`);
        }

        // Keep process alive until killed by cleanup
        // console.error('Static file detection complete, waiting for cleanup signal...');

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
