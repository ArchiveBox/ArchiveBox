#!/usr/bin/env node
/**
 * Archive all network responses during page load (DAEMON MODE).
 *
 * This hook daemonizes and stays alive to capture network responses throughout
 * the snapshot lifecycle. It's killed by chrome_cleanup at the end.
 *
 * Usage: on_Snapshot__24_responses.js --url=<url> --snapshot-id=<uuid>
 * Output: Creates responses/ directory with index.jsonl + listener.pid
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const puppeteer = require('puppeteer-core');

// Extractor metadata
const EXTRACTOR_NAME = 'responses';
const OUTPUT_DIR = '.';
const PID_FILE = 'listener.pid';
const CHROME_SESSION_DIR = '../chrome_session';

// Resource types to capture (by default, capture everything)
const DEFAULT_TYPES = ['script', 'stylesheet', 'font', 'image', 'media', 'xhr', 'websocket'];

// Parse command line arguments
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

// Get environment variable with default
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

// Get CDP URL from chrome_session
function getCdpUrl() {
    const cdpFile = path.join(CHROME_SESSION_DIR, 'cdp_url.txt');
    if (fs.existsSync(cdpFile)) {
        return fs.readFileSync(cdpFile, 'utf8').trim();
    }
    return null;
}

function getPageId() {
    const pageIdFile = path.join(CHROME_SESSION_DIR, 'page_id.txt');
    if (fs.existsSync(pageIdFile)) {
        return fs.readFileSync(pageIdFile, 'utf8').trim();
    }
    return null;
}

// Get file extension from MIME type
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

// Get extension from URL path
function getExtensionFromUrl(url) {
    try {
        const pathname = new URL(url).pathname;
        const match = pathname.match(/\.([a-z0-9]+)$/i);
        return match ? match[1].toLowerCase() : '';
    } catch (e) {
        return '';
    }
}

// Sanitize filename
function sanitizeFilename(str, maxLen = 200) {
    return str
        .replace(/[^a-zA-Z0-9._-]/g, '_')
        .slice(0, maxLen);
}

// Create symlink (handle errors gracefully)
async function createSymlink(target, linkPath) {
    try {
        // Create parent directory
        const dir = path.dirname(linkPath);
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }

        // Remove existing symlink/file if present
        if (fs.existsSync(linkPath)) {
            fs.unlinkSync(linkPath);
        }

        // Create relative symlink
        const relativePath = path.relative(dir, target);
        fs.symlinkSync(relativePath, linkPath);
    } catch (e) {
        // Ignore symlink errors (file conflicts, permissions, etc.)
    }
}

// Set up response listener
async function setupListener() {
    const typesStr = getEnv('RESPONSES_TYPES', DEFAULT_TYPES.join(','));
    const typesToSave = typesStr.split(',').map(t => t.trim().toLowerCase());

    // Create subdirectories for organizing responses
    const allDir = path.join(OUTPUT_DIR, 'all');
    if (!fs.existsSync(allDir)) {
        fs.mkdirSync(allDir, { recursive: true });
    }

    // Create index file
    const indexPath = path.join(OUTPUT_DIR, 'index.jsonl');
    fs.writeFileSync(indexPath, '');  // Clear existing

    const cdpUrl = getCdpUrl();
    if (!cdpUrl) {
        throw new Error('No Chrome session found');
    }

    const browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

    // Find our page
    const pages = await browser.pages();
    const pageId = getPageId();
    let page = null;

    if (pageId) {
        page = pages.find(p => {
            const target = p.target();
            return target && target._targetId === pageId;
        });
    }
    if (!page) {
        page = pages[pages.length - 1];
    }

    if (!page) {
        throw new Error('No page found');
    }

    // Set up response listener to capture network traffic
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
                // Some responses can't be captured (already consumed, etc.)
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

                // Create symlink: responses/<type>/<hostname>/<path>/<filename>
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
                url: method === 'DATA' ? url.slice(0, 128) : url,  // Truncate data: URLs
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

    // Don't disconnect - keep browser connection alive
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

    if (!getEnvBool('SAVE_RESPONSES', true)) {
        console.log('Skipping (SAVE_RESPONSES=False)');
        const result = {
            extractor: EXTRACTOR_NAME,
            status: 'skipped',
            url,
            snapshot_id: snapshotId,
        };
        console.log(`RESULT_JSON=${JSON.stringify(result)}`);
        process.exit(0);
    }

    const startTs = new Date();

    try {
        // Set up listener
        await setupListener();

        // Write PID file so chrome_cleanup can kill us
        fs.writeFileSync(path.join(OUTPUT_DIR, PID_FILE), String(process.pid));

        // Report success immediately (we're staying alive in background)
        const endTs = new Date();
        const duration = (endTs - startTs) / 1000;

        console.log(`START_TS=${startTs.toISOString()}`);
        console.log(`END_TS=${endTs.toISOString()}`);
        console.log(`DURATION=${duration.toFixed(2)}`);
        console.log(`OUTPUT=responses/`);
        console.log(`STATUS=succeeded`);

        const result = {
            extractor: EXTRACTOR_NAME,
            url,
            snapshot_id: snapshotId,
            status: 'succeeded',
            start_ts: startTs.toISOString(),
            end_ts: endTs.toISOString(),
            duration: Math.round(duration * 100) / 100,
            output: 'responses/',
        };
        console.log(`RESULT_JSON=${JSON.stringify(result)}`);

        // Daemonize: detach from parent and keep running
        // This process will be killed by chrome_cleanup
        if (process.stdin.isTTY) {
            process.stdin.pause();
        }
        process.stdin.unref();
        process.stdout.end();
        process.stderr.end();

        // Keep the process alive indefinitely
        // Will be killed by chrome_cleanup via the PID file
        setInterval(() => {}, 1000);

    } catch (e) {
        const error = `${e.name}: ${e.message}`;
        console.error(`ERROR=${error}`);

        const endTs = new Date();
        const result = {
            extractor: EXTRACTOR_NAME,
            url,
            snapshot_id: snapshotId,
            status: 'failed',
            start_ts: startTs.toISOString(),
            end_ts: endTs.toISOString(),
            error,
        };
        console.log(`RESULT_JSON=${JSON.stringify(result)}`);
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
