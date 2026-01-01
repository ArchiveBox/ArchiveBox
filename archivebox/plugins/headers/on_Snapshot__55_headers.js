#!/usr/bin/env node
/**
 * Extract HTTP response headers for a URL.
 *
 * If a Chrome session exists (from chrome plugin), reads the captured
 * response headers from chrome plugin/response_headers.json.
 * Otherwise falls back to making an HTTP HEAD request.
 *
 * Usage: on_Snapshot__55_headers.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes headers/headers.json
 *
 * Environment variables:
 *     TIMEOUT: Timeout in seconds (default: 30)
 *     USER_AGENT: User agent string (optional)
 *     CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: true)
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

const {
    getEnv,
    getEnvBool,
    getEnvInt,
    parseArgs,
} = require('../chrome/chrome_utils.js');

// Extractor metadata
const PLUGIN_NAME = 'headers';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'headers.json';
const CHROME_SESSION_DIR = '../chrome';
const CHROME_HEADERS_FILE = 'response_headers.json';

// Get headers from chrome plugin if available
function getHeadersFromChromeSession() {
    const headersFile = path.join(CHROME_SESSION_DIR, CHROME_HEADERS_FILE);
    if (fs.existsSync(headersFile)) {
        try {
            const data = JSON.parse(fs.readFileSync(headersFile, 'utf8'));
            return data;
        } catch (e) {
            return null;
        }
    }
    return null;
}

// Fetch headers via HTTP HEAD request (fallback)
function fetchHeaders(url) {
    return new Promise((resolve, reject) => {
        const timeout = getEnvInt('TIMEOUT', 30) * 1000;
        const userAgent = getEnv('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)');
        const checkSsl = getEnvBool('CHECK_SSL_VALIDITY', getEnvBool('CHECK_SSL_VALIDITY', true));

        const parsedUrl = new URL(url);
        const client = parsedUrl.protocol === 'https:' ? https : http;

        const options = {
            method: 'HEAD',
            hostname: parsedUrl.hostname,
            port: parsedUrl.port || (parsedUrl.protocol === 'https:' ? 443 : 80),
            path: parsedUrl.pathname + parsedUrl.search,
            headers: { 'User-Agent': userAgent },
            timeout,
            rejectUnauthorized: checkSsl,
        };

        const req = client.request(options, (res) => {
            resolve({
                url: url,
                status: res.statusCode,
                statusText: res.statusMessage,
                headers: res.headers,
            });
        });

        req.on('error', reject);
        req.on('timeout', () => {
            req.destroy();
            reject(new Error('Request timeout'));
        });

        req.end();
    });
}

async function extractHeaders(url) {
    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    // Try Chrome session first
    const chromeHeaders = getHeadersFromChromeSession();
    if (chromeHeaders && chromeHeaders.headers) {
        fs.writeFileSync(outputPath, JSON.stringify(chromeHeaders, null, 2), 'utf8');
        return { success: true, output: outputPath, method: 'chrome', status: chromeHeaders.status };
    }

    // Fallback to HTTP HEAD request
    try {
        const headers = await fetchHeaders(url);
        fs.writeFileSync(outputPath, JSON.stringify(headers, null, 2), 'utf8');
        return { success: true, output: outputPath, method: 'http', status: headers.status };
    } catch (e) {
        return { success: false, error: e.message };
    }
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__55_headers.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    try {
        const result = await extractHeaders(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            console.log(`Headers extracted (${result.method}): HTTP ${result.status}`);
        } else {
            status = 'failed';
            error = result.error;
        }
    } catch (e) {
        error = `${e.name}: ${e.message}`;
        status = 'failed';
    }

    const endTs = new Date();

    if (error) console.error(`ERROR: ${error}`);

    // Output clean JSONL (no RESULT_JSON= prefix)
    console.log(JSON.stringify({
        type: 'ArchiveResult',
        status,
        output_str: output || error || '',
    }));

    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
