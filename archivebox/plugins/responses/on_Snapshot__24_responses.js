#!/usr/bin/env node
/**
 * Archive all network responses during page load.
 *
 * Connects to Chrome session and captures ALL network responses (XHR, images, scripts, etc.)
 * Saves them in an organized directory structure with both timestamped unique files
 * and URL-organized symlinks.
 *
 * Usage: on_Snapshot__23_responses.js --url=<url> --snapshot-id=<uuid>
 * Output: Creates responses/ directory with:
 *   - all/<timestamp>__<METHOD>__<URL>.<ext>: Timestamped unique files
 *   - <type>/<domain>/<path>/: URL-organized symlinks by resource type
 *   - index.jsonl: Searchable index of all responses
 *
 * Environment variables:
 *     SAVE_RESPONSES: Enable response archiving (default: true)
 *     RESPONSES_TIMEOUT: Timeout in seconds (default: 120)
 *     RESPONSES_TYPES: Comma-separated resource types to save (default: all)
 *                      Options: script,stylesheet,font,image,media,xhr,websocket,document
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const puppeteer = require('puppeteer-core');

// Extractor metadata
const EXTRACTOR_NAME = 'responses';
const OUTPUT_DIR = '.';
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
        console.error(`Failed to create symlink: ${e.message}`);
    }
}

// Archive responses by intercepting network traffic
async function archiveResponses(originalUrl) {
    const timeout = (getEnvInt('RESPONSES_TIMEOUT') || getEnvInt('TIMEOUT', 120)) * 1000;
    const typesStr = getEnv('RESPONSES_TYPES', DEFAULT_TYPES.join(','));
    const typesToSave = typesStr.split(',').map(t => t.trim().toLowerCase());

    // Output directory is current directory (hook already runs in output dir)
    // Create subdirectories for organizing responses
    const allDir = path.join(OUTPUT_DIR, 'all');
    if (!fs.existsSync(allDir)) {
        fs.mkdirSync(allDir, { recursive: true });
    }

    // Create index file
    const indexPath = path.join(OUTPUT_DIR, 'index.jsonl');
    fs.writeFileSync(indexPath, '');  // Clear existing

    let browser = null;
    let savedCount = 0;
    const savedResponses = [];

    try {
        // Connect to existing Chrome session
        const cdpUrl = getCdpUrl();
        if (!cdpUrl) {
            return { success: false, error: 'No Chrome session found (chrome_session extractor must run first)' };
        }

        browser = await puppeteer.connect({
            browserWSEndpoint: cdpUrl,
        });

        // Get the page
        const pages = await browser.pages();
        const page = pages.find(p => p.url().startsWith('http')) || pages[0];

        if (!page) {
            return { success: false, error: 'No page found in Chrome session' };
        }

        // Enable request interception
        await page.setRequestInterception(false);  // Don't block requests

        // Listen for responses
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
                savedResponses.push(indexEntry);
                savedCount++;

            } catch (e) {
                // Log but don't fail the whole extraction
                console.error(`Error capturing response: ${e.message}`);
            }
        });

        // Wait a bit to ensure we capture responses
        // (chrome_session already loaded the page, just capture any remaining traffic)
        await new Promise(resolve => setTimeout(resolve, 2000));

        return {
            success: true,
            output: OUTPUT_DIR,
            savedCount,
            indexPath,
        };

    } catch (e) {
        return { success: false, error: `${e.name}: ${e.message}` };
    } finally {
        if (browser) {
            browser.disconnect();
        }
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__23_responses.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';
    let savedCount = 0;

    try {
        // Check if enabled
        if (!getEnvBool('SAVE_RESPONSES', true)) {
            console.log('Skipping responses (SAVE_RESPONSES=False)');
            status = 'skipped';
            const endTs = new Date();
            console.log(`START_TS=${startTs.toISOString()}`);
            console.log(`END_TS=${endTs.toISOString()}`);
            console.log(`STATUS=${status}`);
            console.log(`RESULT_JSON=${JSON.stringify({extractor: EXTRACTOR_NAME, status, url, snapshot_id: snapshotId})}`);
            process.exit(0);
        }

        const result = await archiveResponses(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            savedCount = result.savedCount || 0;
            console.log(`Saved ${savedCount} network responses to ${output}/`);
        } else {
            status = 'failed';
            error = result.error;
        }
    } catch (e) {
        error = `${e.name}: ${e.message}`;
        status = 'failed';
    }

    const endTs = new Date();
    const duration = (endTs - startTs) / 1000;

    // Print results
    console.log(`START_TS=${startTs.toISOString()}`);
    console.log(`END_TS=${endTs.toISOString()}`);
    console.log(`DURATION=${duration.toFixed(2)}`);
    if (output) {
        console.log(`OUTPUT=${output}`);
    }
    console.log(`STATUS=${status}`);

    if (error) {
        console.error(`ERROR=${error}`);
    }

    // Print JSON result
    const resultJson = {
        extractor: EXTRACTOR_NAME,
        url,
        snapshot_id: snapshotId,
        status,
        start_ts: startTs.toISOString(),
        end_ts: endTs.toISOString(),
        duration: Math.round(duration * 100) / 100,
        output,
        saved_count: savedCount,
        error: error || null,
    };
    console.log(`RESULT_JSON=${JSON.stringify(resultJson)}`);

    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
