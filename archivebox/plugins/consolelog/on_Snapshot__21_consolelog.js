#!/usr/bin/env node
/**
 * Capture console output from a page.
 *
 * Captures all console messages during page load:
 * - log, warn, error, info, debug
 * - Includes stack traces for errors
 * - Timestamps for each message
 *
 * Usage: on_Snapshot__14_consolelog.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes consolelog/console.jsonl (one message per line)
 *
 * Environment variables:
 *     SAVE_CONSOLELOG: Enable console log capture (default: true)
 *     CONSOLELOG_TIMEOUT: Capture duration in seconds (default: 5)
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

// Extractor metadata
const EXTRACTOR_NAME = 'consolelog';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'console.jsonl';
const CHROME_SESSION_DIR = '../chrome_session';

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

// Serialize console message arguments
async function serializeArgs(args) {
    const serialized = [];
    for (const arg of args) {
        try {
            const json = await arg.jsonValue();
            serialized.push(json);
        } catch (e) {
            // If jsonValue() fails, try to get text representation
            try {
                serialized.push(String(arg));
            } catch (e2) {
                serialized.push('[Unserializable]');
            }
        }
    }
    return serialized;
}

// Capture console logs
async function captureConsoleLogs(url) {
    const captureTimeout = (getEnvInt('CONSOLELOG_TIMEOUT') || 5) * 1000;

    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);

    // Clear existing file
    fs.writeFileSync(outputPath, '');

    let browser = null;
    const consoleLogs = [];

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

        // Listen for console messages
        page.on('console', async (msg) => {
            try {
                const type = msg.type();
                const text = msg.text();
                const location = msg.location();
                const args = await serializeArgs(msg.args());

                const logEntry = {
                    timestamp: new Date().toISOString(),
                    type,
                    text,
                    args,
                    location: {
                        url: location.url || '',
                        lineNumber: location.lineNumber,
                        columnNumber: location.columnNumber,
                    },
                };

                // Write immediately to file
                fs.appendFileSync(outputPath, JSON.stringify(logEntry) + '\n');
                consoleLogs.push(logEntry);
            } catch (e) {
                // Error processing console message, skip it
                console.error(`Error processing console message: ${e.message}`);
            }
        });

        // Listen for page errors
        page.on('pageerror', (error) => {
            try {
                const logEntry = {
                    timestamp: new Date().toISOString(),
                    type: 'error',
                    text: error.message,
                    stack: error.stack || '',
                    location: {},
                };

                fs.appendFileSync(outputPath, JSON.stringify(logEntry) + '\n');
                consoleLogs.push(logEntry);
            } catch (e) {
                console.error(`Error processing page error: ${e.message}`);
            }
        });

        // Listen for request failures
        page.on('requestfailed', (request) => {
            try {
                const failure = request.failure();
                const logEntry = {
                    timestamp: new Date().toISOString(),
                    type: 'request_failed',
                    text: `Request failed: ${request.url()}`,
                    error: failure ? failure.errorText : 'Unknown error',
                    url: request.url(),
                    location: {},
                };

                fs.appendFileSync(outputPath, JSON.stringify(logEntry) + '\n');
                consoleLogs.push(logEntry);
            } catch (e) {
                console.error(`Error processing request failure: ${e.message}`);
            }
        });

        // Wait to capture logs
        await new Promise(resolve => setTimeout(resolve, captureTimeout));

        // Group logs by type
        const logStats = consoleLogs.reduce((acc, log) => {
            acc[log.type] = (acc[log.type] || 0) + 1;
            return acc;
        }, {});

        return {
            success: true,
            output: outputPath,
            logCount: consoleLogs.length,
            logStats,
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
        console.error('Usage: on_Snapshot__14_consolelog.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';
    let logCount = 0;

    try {
        // Check if enabled
        if (!getEnvBool('SAVE_CONSOLELOG', true)) {
            console.log('Skipping console log (SAVE_CONSOLELOG=False)');
            status = 'skipped';
            const endTs = new Date();
            console.log(`START_TS=${startTs.toISOString()}`);
            console.log(`END_TS=${endTs.toISOString()}`);
            console.log(`STATUS=${status}`);
            console.log(`RESULT_JSON=${JSON.stringify({extractor: EXTRACTOR_NAME, status, url, snapshot_id: snapshotId})}`);
            process.exit(0);
        }

        const result = await captureConsoleLogs(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            logCount = result.logCount || 0;
            const statsStr = Object.entries(result.logStats || {})
                .map(([type, count]) => `${count} ${type}`)
                .join(', ');
            console.log(`Captured ${logCount} console messages: ${statsStr}`);
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
        log_count: logCount,
        error: error || null,
    };
    console.log(`RESULT_JSON=${JSON.stringify(resultJson)}`);

    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
