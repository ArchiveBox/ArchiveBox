#!/usr/bin/env node
/**
 * Launch a shared Chrome browser session for the entire crawl.
 *
 * This runs once per crawl and keeps Chrome alive for all snapshots to share.
 * Each snapshot creates its own tab via on_Snapshot__20_chrome_session.js.
 *
 * Usage: on_Crawl__10_chrome_session.js --crawl-id=<uuid> --source-url=<url>
 * Output: Creates chrome_session/ with:
 *   - cdp_url.txt: WebSocket URL for CDP connection
 *   - pid.txt: Chrome process ID (for cleanup)
 *
 * Environment variables:
 *     CHROME_BINARY: Path to Chrome/Chromium binary
 *     CHROME_RESOLUTION: Page resolution (default: 1440,2000)
 *     CHROME_HEADLESS: Run in headless mode (default: true)
 *     CHROME_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: true)
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

// Extractor metadata
const EXTRACTOR_NAME = 'chrome_session';
const OUTPUT_DIR = 'chrome_session';

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

// Find Chrome binary
function findChrome() {
    const chromeBinary = getEnv('CHROME_BINARY');
    if (chromeBinary && fs.existsSync(chromeBinary)) {
        return chromeBinary;
    }

    const candidates = [
        // Linux
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        // macOS
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
    ];

    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) {
            return candidate;
        }
    }

    return null;
}

// Parse resolution string
function parseResolution(resolution) {
    const [width, height] = resolution.split(',').map(x => parseInt(x.trim(), 10));
    return { width: width || 1440, height: height || 2000 };
}

// Find a free port
function findFreePort() {
    return new Promise((resolve, reject) => {
        const server = require('net').createServer();
        server.unref();
        server.on('error', reject);
        server.listen(0, () => {
            const port = server.address().port;
            server.close(() => resolve(port));
        });
    });
}

// Wait for Chrome's DevTools port to be ready
function waitForDebugPort(port, timeout = 30000) {
    const startTime = Date.now();

    return new Promise((resolve, reject) => {
        const tryConnect = () => {
            if (Date.now() - startTime > timeout) {
                reject(new Error(`Timeout waiting for Chrome debug port ${port}`));
                return;
            }

            const req = http.get(`http://127.0.0.1:${port}/json/version`, (res) => {
                let data = '';
                res.on('data', chunk => data += chunk);
                res.on('end', () => {
                    try {
                        const info = JSON.parse(data);
                        resolve(info);
                    } catch (e) {
                        setTimeout(tryConnect, 100);
                    }
                });
            });

            req.on('error', () => {
                setTimeout(tryConnect, 100);
            });

            req.setTimeout(1000, () => {
                req.destroy();
                setTimeout(tryConnect, 100);
            });
        };

        tryConnect();
    });
}

async function launchChrome(binary) {
    const resolution = getEnv('CHROME_RESOLUTION') || getEnv('RESOLUTION', '1440,2000');
    const checkSsl = getEnvBool('CHROME_CHECK_SSL_VALIDITY', getEnvBool('CHECK_SSL_VALIDITY', true));
    const headless = getEnvBool('CHROME_HEADLESS', true);

    const { width, height } = parseResolution(resolution);

    // Create output directory
    if (!fs.existsSync(OUTPUT_DIR)) {
        fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    }

    // Find a free port for Chrome DevTools
    const debugPort = await findFreePort();
    console.log(`[*] Using debug port: ${debugPort}`);

    // Load any installed extensions
    const extensionUtils = require('../chrome_extensions/chrome_extension_utils.js');
    const extensionsDir = getEnv('CHROME_EXTENSIONS_DIR') ||
        path.join(getEnv('DATA_DIR', '.'), 'personas', getEnv('ACTIVE_PERSONA', 'Default'), 'chrome_extensions');

    const installedExtensions = [];
    if (fs.existsSync(extensionsDir)) {
        const files = fs.readdirSync(extensionsDir);
        for (const file of files) {
            if (file.endsWith('.extension.json')) {
                try {
                    const extPath = path.join(extensionsDir, file);
                    const extData = JSON.parse(fs.readFileSync(extPath, 'utf-8'));
                    if (extData.unpacked_path && fs.existsSync(extData.unpacked_path)) {
                        installedExtensions.push(extData);
                        console.log(`[*] Loading extension: ${extData.name || file}`);
                    }
                } catch (e) {
                    // Skip invalid cache files
                    console.warn(`[!] Skipping invalid extension cache: ${file}`);
                }
            }
        }
    }

    // Get extension launch arguments
    const extensionArgs = extensionUtils.getExtensionLaunchArgs(installedExtensions);
    if (extensionArgs.length > 0) {
        console.log(`[+] Loaded ${installedExtensions.length} extension(s)`);
        // Write extensions metadata for config hooks to use
        fs.writeFileSync(
            path.join(OUTPUT_DIR, 'extensions.json'),
            JSON.stringify(installedExtensions, null, 2)
        );
    }

    // Build Chrome arguments
    const chromeArgs = [
        `--remote-debugging-port=${debugPort}`,
        '--remote-debugging-address=127.0.0.1',
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-sync',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-default-apps',
        '--disable-infobars',
        '--disable-blink-features=AutomationControlled',
        '--disable-component-update',
        '--disable-domain-reliability',
        '--disable-breakpad',
        '--disable-background-networking',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--disable-ipc-flooding-protection',
        '--password-store=basic',
        '--use-mock-keychain',
        '--font-render-hinting=none',
        '--force-color-profile=srgb',
        `--window-size=${width},${height}`,
        ...extensionArgs,  // Load extensions
        ...(headless ? ['--headless=new'] : []),
        ...(checkSsl ? [] : ['--ignore-certificate-errors']),
        'about:blank',  // Start with blank page
    ];

    // Launch Chrome as a child process (NOT detached - stays with crawl process)
    // Using stdio: 'ignore' so we don't block on output but Chrome stays as our child
    const chromeProcess = spawn(binary, chromeArgs, {
        stdio: ['ignore', 'ignore', 'ignore'],
    });

    const chromePid = chromeProcess.pid;
    console.log(`[*] Launched Chrome (PID: ${chromePid}), waiting for debug port...`);

    // Write PID immediately for cleanup
    fs.writeFileSync(path.join(OUTPUT_DIR, 'pid.txt'), String(chromePid));
    fs.writeFileSync(path.join(OUTPUT_DIR, 'port.txt'), String(debugPort));

    try {
        // Wait for Chrome to be ready
        const versionInfo = await waitForDebugPort(debugPort, 30000);
        console.log(`[+] Chrome ready: ${versionInfo.Browser}`);

        // Build WebSocket URL
        const wsUrl = versionInfo.webSocketDebuggerUrl;
        fs.writeFileSync(path.join(OUTPUT_DIR, 'cdp_url.txt'), wsUrl);

        return { success: true, cdpUrl: wsUrl, pid: chromePid, port: debugPort };

    } catch (e) {
        // Kill Chrome if setup failed
        try {
            process.kill(chromePid, 'SIGTERM');
        } catch (killErr) {
            // Ignore
        }
        return { success: false, error: `${e.name}: ${e.message}` };
    }
}

async function main() {
    const args = parseArgs();
    const crawlId = args.crawl_id;

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';
    let version = '';

    try {
        const binary = findChrome();
        if (!binary) {
            console.error('ERROR: Chrome/Chromium binary not found');
            console.error('DEPENDENCY_NEEDED=chrome');
            console.error('BIN_PROVIDERS=puppeteer,env,playwright,apt,brew');
            console.error('INSTALL_HINT=npx @puppeteer/browsers install chrome@stable');
            process.exit(1);
        }

        // Get Chrome version
        try {
            const { execSync } = require('child_process');
            version = execSync(`"${binary}" --version`, { encoding: 'utf8', timeout: 5000 }).trim().slice(0, 64);
        } catch (e) {
            version = '';
        }

        const result = await launchChrome(binary);

        if (result.success) {
            status = 'succeeded';
            output = OUTPUT_DIR;
            console.log(`[+] Chrome session started for crawl ${crawlId}`);
            console.log(`[+] CDP URL: ${result.cdpUrl}`);
            console.log(`[+] PID: ${result.pid}`);
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
    if (version) {
        console.log(`VERSION=${version}`);
    }
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
        crawl_id: crawlId,
        status,
        start_ts: startTs.toISOString(),
        end_ts: endTs.toISOString(),
        duration: Math.round(duration * 100) / 100,
        cmd_version: version,
        output,
        error: error || null,
    };
    console.log(`RESULT_JSON=${JSON.stringify(resultJson)}`);

    // Exit with success - Chrome stays running as our child process
    // It will be cleaned up when the crawl process terminates
    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
