#!/usr/bin/env node
/**
 * Archive all network responses during page load.
 *
 * This hook sets up CDP listeners BEFORE chrome_navigate loads the page,
 * then waits for navigation to complete. The listeners capture all network
 * responses during the navigation.
 *
 * Usage: on_Snapshot__24_responses.js --url=<url> --snapshot-id=<uuid>
 * Output: Creates responses/ directory with index.jsonl
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const puppeteer = require('puppeteer-core');

// Import shared utilities from chrome_utils.js
const {
    getEnv,
    getEnvBool,
    getEnvInt,
    parseArgs,
    connectToPage,
    waitForPageLoaded,
} = require('../chrome/chrome_utils.js');

const PLUGIN_NAME = 'responses';
const OUTPUT_DIR = '.';
const CHROME_SESSION_DIR = '../chrome';

// Resource types to capture (by default, capture everything)
const DEFAULT_TYPES = ['script', 'stylesheet', 'font', 'image', 'media', 'xhr', 'websocket'];

function getExtensionFromMimeType(mimeType) {
    const mimeMap = {
        'text/html': 'html',
        'text/css': 'css',
        'text/javascript': 'js',
        'application/javascript': 'js',
        'application/x-javascript': 'js',
        'application/json': 'json',
        'application/xml': 'xml',
        'text/xml': 'xml',
        'image/png': 'png',
        'image/jpeg': 'jpg',
        'image/gif': 'gif',
        'image/svg+xml': 'svg',
        'image/webp': 'webp',
        'font/woff': 'woff',
        'font/woff2': 'woff2',
        'font/ttf': 'ttf',
        'font/otf': 'otf',
        'application/font-woff': 'woff',
        'application/font-woff2': 'woff2',
        'video/mp4': 'mp4',
        'video/webm': 'webm',
        'audio/mpeg': 'mp3',
        'audio/ogg': 'ogg',
    };

    const mimeBase = (mimeType || '').split(';')[0].trim().toLowerCase();
    return mimeMap[mimeBase] || '';
}

function getExtensionFromUrl(url) {
    try {
        const pathname = new URL(url).pathname;
        const match = pathname.match(/\.([a-z0-9]+)$/i);
        return match ? match[1].toLowerCase() : '';
    } catch (e) {
        return '';
    }
}

function sanitizeFilename(str, maxLen = 200) {
    return str
        .replace(/[^a-zA-Z0-9._-]/g, '_')
        .slice(0, maxLen);
}

async function createSymlink(target, linkPath) {
    try {
        const dir = path.dirname(linkPath);
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }

        if (fs.existsSync(linkPath)) {
            fs.unlinkSync(linkPath);
        }

        const relativePath = path.relative(dir, target);
        fs.symlinkSync(relativePath, linkPath);
    } catch (e) {
        // Ignore symlink errors
    }
}

async function setupListener() {
    const timeout = getEnvInt('RESPONSES_TIMEOUT', 30) * 1000;
    const typesStr = getEnv('RESPONSES_TYPES', DEFAULT_TYPES.join(','));
    const typesToSave = typesStr.split(',').map(t => t.trim().toLowerCase());

    // Create subdirectories
    const allDir = path.join(OUTPUT_DIR, 'all');
    if (!fs.existsSync(allDir)) {
        fs.mkdirSync(allDir, { recursive: true });
    }

    const indexPath = path.join(OUTPUT_DIR, 'index.jsonl');
    fs.writeFileSync(indexPath, '');

    // Connect to Chrome page using shared utility
    const { browser, page } = await connectToPage({
        chromeSessionDir: CHROME_SESSION_DIR,
        timeoutMs: timeout,
        puppeteer,
    });

    // Set up response listener
    page.on('response', async (response) => {
        try {
            const request = response.request();
            const url = response.url();
            const resourceType = request.resourceType().toLowerCase();
            const method = request.method();
            const status = response.status();

            // Skip redirects and errors
            if (status >= 300 && status < 400) return;
            if (status >= 400 && status < 600) return;

            // Check if we should save this resource type
            if (typesToSave.length && !typesToSave.includes(resourceType)) {
                return;
            }

            // Get response body
            let bodyBuffer = null;
            try {
                bodyBuffer = await response.buffer();
            } catch (e) {
                return;
            }

            if (!bodyBuffer || bodyBuffer.length === 0) {
                return;
            }

            // Determine file extension
            const mimeType = response.headers()['content-type'] || '';
            let extension = getExtensionFromMimeType(mimeType) || getExtensionFromUrl(url);

            // Create timestamp-based unique filename
            const timestamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '');
            const urlHash = sanitizeFilename(encodeURIComponent(url).slice(0, 64));
            const uniqueFilename = `${timestamp}__${method}__${urlHash}${extension ? '.' + extension : ''}`;
            const uniquePath = path.join(allDir, uniqueFilename);

            // Save to unique file
            fs.writeFileSync(uniquePath, bodyBuffer);

            // Create URL-organized symlink
            try {
                const urlObj = new URL(url);
                const hostname = urlObj.hostname;
                const pathname = urlObj.pathname || '/';
                const filename = path.basename(pathname) || 'index' + (extension ? '.' + extension : '');
                const dirPath = path.dirname(pathname);

                const symlinkDir = path.join(OUTPUT_DIR, resourceType, hostname, dirPath);
                const symlinkPath = path.join(symlinkDir, filename);
                await createSymlink(uniquePath, symlinkPath);
            } catch (e) {
                // URL parsing or symlink creation failed, skip
            }

            // Calculate SHA256
            const sha256 = crypto.createHash('sha256').update(bodyBuffer).digest('hex');
            const urlSha256 = crypto.createHash('sha256').update(url).digest('hex');

            // Write to index
            const indexEntry = {
                ts: timestamp,
                method,
                url: method === 'DATA' ? url.slice(0, 128) : url,
                urlSha256,
                status,
                resourceType,
                mimeType: mimeType.split(';')[0],
                responseSha256: sha256,
                path: './' + path.relative(OUTPUT_DIR, uniquePath),
                extension,
            };

            fs.appendFileSync(indexPath, JSON.stringify(indexEntry) + '\n');

        } catch (e) {
            // Ignore errors
        }
    });

    return { browser, page };
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__24_responses.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    if (!getEnvBool('RESPONSES_ENABLED', true)) {
        console.error('Skipping (RESPONSES_ENABLED=False)');
        console.log(JSON.stringify({type: 'ArchiveResult', status: 'skipped', output_str: 'RESPONSES_ENABLED=False'}));
        process.exit(0);
    }

    const timeout = getEnvInt('RESPONSES_TIMEOUT', 30) * 1000;

    try {
        // Set up listener BEFORE navigation
        await setupListener();

        // Wait for chrome_navigate to complete (BLOCKING)
        // Extra 1s delay for late responses
        await waitForPageLoaded(CHROME_SESSION_DIR, timeout * 4, 1000);

        // Output clean JSONL
        console.log(JSON.stringify({
            type: 'ArchiveResult',
            status: 'succeeded',
            output_str: 'responses/',
        }));

        process.exit(0);

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
