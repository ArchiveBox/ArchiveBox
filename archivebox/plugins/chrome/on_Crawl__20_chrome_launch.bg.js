#!/usr/bin/env node
/**
 * Launch a shared Chrome browser session for the entire crawl.
 *
 * This runs once per crawl and keeps Chrome alive for all snapshots to share.
 * Each snapshot creates its own tab via on_Snapshot__20_chrome_tab.bg.js.
 *
 * Usage: on_Crawl__20_chrome_launch.bg.js --crawl-id=<uuid> --source-url=<url>
 * Output: Creates chrome/ directory under crawl output dir with:
 *   - cdp_url.txt: WebSocket URL for CDP connection
 *   - pid.txt: Chrome process ID (for cleanup)
 *   - port.txt: Debug port number
 *   - extensions.json: Loaded extensions metadata
 *
 * Environment variables:
 *     CHROME_BINARY: Path to Chrome/Chromium binary
 *     CHROME_RESOLUTION: Page resolution (default: 1440,2000)
 *     CHROME_HEADLESS: Run in headless mode (default: true)
 *     CHROME_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: true)
 *     CHROME_EXTENSIONS_DIR: Directory containing Chrome extensions
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

// Extractor metadata
const EXTRACTOR_NAME = 'chrome_launch';
const OUTPUT_DIR = 'chrome';

// Helper: Write PID file with mtime set to process start time
function writePidWithMtime(filePath, pid, startTimeSeconds) {
    fs.writeFileSync(filePath, String(pid));
    // Set both atime and mtime to process start time for validation
    const startTimeMs = startTimeSeconds * 1000;
    fs.utimesSync(filePath, new Date(startTimeMs), new Date(startTimeMs));
}

// Helper: Write command script for validation
function writeCmdScript(filePath, binary, args) {
    // Shell escape arguments containing spaces or special characters
    const escapedArgs = args.map(arg => {
        if (arg.includes(' ') || arg.includes('"') || arg.includes('$')) {
            return `"${arg.replace(/"/g, '\\"')}"`;
        }
        return arg;
    });
    const script = `#!/bin/bash\n${binary} ${escapedArgs.join(' ')}\n`;
    fs.writeFileSync(filePath, script);
    fs.chmodSync(filePath, 0o755);
}

// Helper: Get process start time (cross-platform)
function getProcessStartTime(pid) {
    try {
        const { execSync } = require('child_process');
        if (process.platform === 'darwin') {
            // macOS: ps -p PID -o lstart= gives start time
            const output = execSync(`ps -p ${pid} -o lstart=`, { encoding: 'utf8', timeout: 1000 });
            return Date.parse(output.trim()) / 1000;  // Convert to epoch seconds
        } else {
            // Linux: read /proc/PID/stat field 22 (starttime in clock ticks)
            const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
            const match = stat.match(/\) \w+ (\d+)/);
            if (match) {
                const startTicks = parseInt(match[1], 10);
                // Convert clock ticks to seconds (assuming 100 ticks/sec)
                const uptimeSeconds = parseFloat(fs.readFileSync('/proc/uptime', 'utf8').split(' ')[0]);
                const bootTime = Date.now() / 1000 - uptimeSeconds;
                return bootTime + (startTicks / 100);
            }
        }
    } catch (e) {
        // Can't get start time
        return null;
    }
    return null;
}

// Helper: Validate PID using mtime and command
function validatePid(pid, pidFile, cmdFile) {
    try {
        // Check process exists
        try {
            process.kill(pid, 0);  // Signal 0 = check existence
        } catch (e) {
            return false;  // Process doesn't exist
        }

        // Check mtime matches process start time (within 5 sec tolerance)
        const fileStat = fs.statSync(pidFile);
        const fileMtime = fileStat.mtimeMs / 1000;  // Convert to seconds
        const procStartTime = getProcessStartTime(pid);

        if (procStartTime === null) {
            // Can't validate - fall back to basic existence check
            return true;
        }

        if (Math.abs(fileMtime - procStartTime) > 5) {
            // PID was reused by different process
            return false;
        }

        // Validate command if available
        if (fs.existsSync(cmdFile)) {
            const cmd = fs.readFileSync(cmdFile, 'utf8');
            // Check for Chrome/Chromium and debug port
            if (!cmd.includes('chrome') && !cmd.includes('chromium')) {
                return false;
            }
            if (!cmd.includes('--remote-debugging-port')) {
                return false;
            }
        }

        return true;
    } catch (e) {
        return false;
    }
}

// Global state for cleanup
let chromePid = null;

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

// Cleanup handler for SIGTERM - kill Chrome and all child processes
async function cleanup() {
    if (!chromePid) {
        process.exit(0);
        return;
    }

    console.log(`[*] Killing Chrome process tree (PID ${chromePid})...`);

    try {
        // Try to kill the entire process group
        process.kill(-chromePid, 'SIGTERM');
    } catch (e) {
        // Fall back to killing just the process
        try {
            process.kill(chromePid, 'SIGTERM');
        } catch (e2) {
            // Already dead
        }
    }

    // Wait 2 seconds for graceful shutdown
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Force kill with SIGKILL
    try {
        process.kill(-chromePid, 'SIGKILL');
    } catch (e) {
        try {
            process.kill(chromePid, 'SIGKILL');
        } catch (e2) {
            // Already dead
        }
    }

    console.log('[*] Chrome process tree killed');

    // Delete PID files to prevent PID reuse issues
    try {
        fs.unlinkSync(path.join(OUTPUT_DIR, 'chrome.pid'));
    } catch (e) {}
    try {
        fs.unlinkSync(path.join(OUTPUT_DIR, 'hook.pid'));
    } catch (e) {}

    process.exit(0);
}

// Register signal handlers
process.on('SIGTERM', cleanup);
process.on('SIGINT', cleanup);

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

// Kill zombie Chrome processes from stale crawls
function killZombieChrome() {
    const dataDir = getEnv('DATA_DIR', '.');
    const crawlsDir = path.join(dataDir, 'crawls');
    const now = Date.now();
    const fiveMinutesAgo = now - 300000;
    let killed = 0;

    console.error('[*] Checking for zombie Chrome processes...');

    if (!fs.existsSync(crawlsDir)) {
        console.error('[+] No crawls directory found');
        return;
    }

    try {
        // Only scan data/crawls/*/chrome/*.pid - no recursion into archive dirs
        const crawls = fs.readdirSync(crawlsDir, { withFileTypes: true });

        for (const crawl of crawls) {
            if (!crawl.isDirectory()) continue;

            const crawlDir = path.join(crawlsDir, crawl.name);
            const chromeDir = path.join(crawlDir, 'chrome');

            if (!fs.existsSync(chromeDir)) continue;

            // Check if crawl was modified recently (still active)
            try {
                const crawlStats = fs.statSync(crawlDir);
                if (crawlStats.mtimeMs > fiveMinutesAgo) {
                    continue; // Crawl modified recently, likely still active
                }
            } catch (e) {
                continue;
            }

            // Crawl is stale (> 5 minutes since modification), check for PIDs
            try {
                const pidFiles = fs.readdirSync(chromeDir).filter(f => f.endsWith('.pid'));

                for (const pidFileName of pidFiles) {
                    const pidFile = path.join(chromeDir, pidFileName);

                    try {
                        const pid = parseInt(fs.readFileSync(pidFile, 'utf8').trim(), 10);
                        if (isNaN(pid) || pid <= 0) continue;

                        // Validate PID before killing
                        const cmdFile = path.join(chromeDir, 'cmd.sh');
                        if (!validatePid(pid, pidFile, cmdFile)) {
                            // PID reused or validation failed
                            console.error(`[!] PID ${pid} failed validation (reused or wrong process) - cleaning up`);
                            try { fs.unlinkSync(pidFile); } catch (e) {}
                            continue;
                        }

                        // Process alive, validated, and crawl is stale - zombie!
                        console.error(`[!] Found validated zombie (PID ${pid}) from stale crawl ${crawl.name}`);

                        try {
                            // Kill process group first
                            try {
                                process.kill(-pid, 'SIGKILL');
                            } catch (e) {
                                process.kill(pid, 'SIGKILL');
                            }

                            killed++;
                            console.error(`[+] Killed zombie (PID ${pid})`);

                            // Remove PID file
                            try { fs.unlinkSync(pidFile); } catch (e) {}

                        } catch (e) {
                            console.error(`[!] Failed to kill PID ${pid}: ${e.message}`);
                        }

                    } catch (e) {
                        // Skip invalid PID files
                    }
                }
            } catch (e) {
                // Skip if can't read chrome dir
            }
        }
    } catch (e) {
        console.error(`[!] Error scanning crawls: ${e.message}`);
    }

    if (killed > 0) {
        console.error(`[+] Killed ${killed} zombie process(es)`);
    } else {
        console.error('[+] No zombies found');
    }
}

async function launchChrome(binary) {
    // First, kill any zombie Chrome from crashed crawls
    killZombieChrome();

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
    console.error(`[*] Using debug port: ${debugPort}`);

    // Load any installed extensions
    const extensionUtils = require('./chrome_extension_utils.js');
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
                        console.error(`[*] Loading extension: ${extData.name || file}`);
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
        console.error(`[+] Loaded ${installedExtensions.length} extension(s)`);
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

    // Launch Chrome as a detached process group leader
    // This allows us to kill Chrome and all its child processes as a group
    const chromeProcess = spawn(binary, chromeArgs, {
        detached: true,
        stdio: ['ignore', 'ignore', 'ignore'],
    });
    chromeProcess.unref(); // Don't keep Node.js process running

    chromePid = chromeProcess.pid;
    const chromeStartTime = Date.now() / 1000;  // Unix epoch seconds
    console.error(`[*] Launched Chrome (PID: ${chromePid}), waiting for debug port...`);

    // Write Chrome PID with mtime set to start time for validation
    writePidWithMtime(path.join(OUTPUT_DIR, 'chrome.pid'), chromePid, chromeStartTime);

    // Write command script for validation
    writeCmdScript(path.join(OUTPUT_DIR, 'cmd.sh'), binary, chromeArgs);

    fs.writeFileSync(path.join(OUTPUT_DIR, 'port.txt'), String(debugPort));

    // Write hook's own PID with mtime for validation
    const hookStartTime = Date.now() / 1000;
    writePidWithMtime(path.join(OUTPUT_DIR, 'hook.pid'), process.pid, hookStartTime);

    try {
        // Wait for Chrome to be ready
        const versionInfo = await waitForDebugPort(debugPort, 30000);
        console.error(`[+] Chrome ready: ${versionInfo.Browser}`);

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
            console.error(`[+] Chrome session started for crawl ${crawlId}`);
            console.error(`[+] CDP URL: ${result.cdpUrl}`);
            console.error(`[+] PID: ${result.pid}`);
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

    if (error) {
        console.error(`ERROR: ${error}`);
        process.exit(1);
    }

    // Background hook - stay running to handle cleanup on SIGTERM
    console.log('[*] Chrome launch hook staying alive to handle cleanup...');

    // Keep process alive by setting an interval (won't actually do anything)
    // This allows us to receive SIGTERM when crawl ends
    setInterval(() => {}, 1000000);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
