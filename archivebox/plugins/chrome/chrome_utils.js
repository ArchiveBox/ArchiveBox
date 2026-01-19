#!/usr/bin/env node
/**
 * Chrome Extension Management Utilities
 *
 * Handles downloading, installing, and managing Chrome extensions for browser automation.
 * Ported from the TypeScript implementation in archivebox.ts
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const http = require('http');
const net = require('net');
const { exec, spawn } = require('child_process');
const { promisify } = require('util');
const { Readable } = require('stream');
const { finished } = require('stream/promises');

const execAsync = promisify(exec);

// ============================================================================
// Environment helpers
// ============================================================================

/**
 * Get environment variable with default value.
 * @param {string} name - Environment variable name
 * @param {string} [defaultValue=''] - Default value if not set
 * @returns {string} - Trimmed environment variable value
 */
function getEnv(name, defaultValue = '') {
    return (process.env[name] || defaultValue).trim();
}

/**
 * Get boolean environment variable.
 * @param {string} name - Environment variable name
 * @param {boolean} [defaultValue=false] - Default value if not set
 * @returns {boolean} - Boolean value
 */
function getEnvBool(name, defaultValue = false) {
    const val = getEnv(name, '').toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(val)) return true;
    if (['false', '0', 'no', 'off'].includes(val)) return false;
    return defaultValue;
}

/**
 * Get integer environment variable.
 * @param {string} name - Environment variable name
 * @param {number} [defaultValue=0] - Default value if not set
 * @returns {number} - Integer value
 */
function getEnvInt(name, defaultValue = 0) {
    const val = parseInt(getEnv(name, String(defaultValue)), 10);
    return isNaN(val) ? defaultValue : val;
}

/**
 * Get array environment variable (JSON array or comma-separated string).
 *
 * Parsing strategy:
 * - If value starts with '[', parse as JSON array
 * - Otherwise, parse as comma-separated values
 *
 * This prevents incorrect splitting of arguments that contain internal commas.
 * For arguments with commas, use JSON format:
 *   CHROME_ARGS='["--user-data-dir=/path/with,comma", "--window-size=1440,900"]'
 *
 * @param {string} name - Environment variable name
 * @param {string[]} [defaultValue=[]] - Default value if not set
 * @returns {string[]} - Array of strings
 */
function getEnvArray(name, defaultValue = []) {
    const val = getEnv(name, '');
    if (!val) return defaultValue;

    // If starts with '[', parse as JSON array
    if (val.startsWith('[')) {
        try {
            const parsed = JSON.parse(val);
            if (Array.isArray(parsed)) return parsed;
        } catch (e) {
            console.error(`[!] Failed to parse ${name} as JSON array: ${e.message}`);
            // Fall through to comma-separated parsing
        }
    }

    // Parse as comma-separated values
    return val.split(',').map(s => s.trim()).filter(Boolean);
}

/**
 * Parse resolution string into width/height.
 * @param {string} resolution - Resolution string like "1440,2000"
 * @returns {{width: number, height: number}} - Parsed dimensions
 */
function parseResolution(resolution) {
    const [width, height] = resolution.split(',').map(x => parseInt(x.trim(), 10));
    return { width: width || 1440, height: height || 2000 };
}

// ============================================================================
// PID file management
// ============================================================================

/**
 * Write PID file with specific mtime for process validation.
 * @param {string} filePath - Path to PID file
 * @param {number} pid - Process ID
 * @param {number} startTimeSeconds - Process start time in seconds
 */
function writePidWithMtime(filePath, pid, startTimeSeconds) {
    fs.writeFileSync(filePath, String(pid));
    const startTimeMs = startTimeSeconds * 1000;
    fs.utimesSync(filePath, new Date(startTimeMs), new Date(startTimeMs));
}

/**
 * Write a shell script that can re-run the Chrome command.
 * @param {string} filePath - Path to script file
 * @param {string} binary - Chrome binary path
 * @param {string[]} args - Chrome arguments
 */
function writeCmdScript(filePath, binary, args) {
    const escape = (arg) =>
        arg.includes(' ') || arg.includes('"') || arg.includes('$')
            ? `"${arg.replace(/"/g, '\\"')}"`
            : arg;
    fs.writeFileSync(
        filePath,
        `#!/bin/bash\n${binary} ${args.map(escape).join(' ')}\n`
    );
    fs.chmodSync(filePath, 0o755);
}

// ============================================================================
// Port management
// ============================================================================

/**
 * Find a free port on localhost.
 * @returns {Promise<number>} - Available port number
 */
function findFreePort() {
    return new Promise((resolve, reject) => {
        const server = net.createServer();
        server.unref();
        server.on('error', reject);
        server.listen(0, () => {
            const port = server.address().port;
            server.close(() => resolve(port));
        });
    });
}

/**
 * Wait for Chrome's DevTools port to be ready.
 * @param {number} port - Debug port number
 * @param {number} [timeout=30000] - Timeout in milliseconds
 * @returns {Promise<Object>} - Chrome version info
 */
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
                res.on('data', (chunk) => (data += chunk));
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

// ============================================================================
// Zombie process cleanup
// ============================================================================

/**
 * Kill zombie Chrome processes from stale crawls.
 * Recursively scans DATA_DIR for any .../chrome/...pid files from stale crawls.
 * Does not assume specific directory structure - works with nested paths.
 * @param {string} [dataDir] - Data directory (defaults to DATA_DIR env or '.')
 * @returns {number} - Number of zombies killed
 */
function killZombieChrome(dataDir = null) {
    dataDir = dataDir || getEnv('DATA_DIR', '.');
    const now = Date.now();
    const fiveMinutesAgo = now - 300000;
    let killed = 0;

    console.error('[*] Checking for zombie Chrome processes...');

    if (!fs.existsSync(dataDir)) {
        console.error('[+] No data directory found');
        return 0;
    }

    /**
     * Recursively find all chrome/.pid files in directory tree
     * @param {string} dir - Directory to search
     * @param {number} depth - Current recursion depth (limit to 10)
     * @returns {Array<{pidFile: string, crawlDir: string}>} - Array of PID file info
     */
    function findChromePidFiles(dir, depth = 0) {
        if (depth > 10) return [];  // Prevent infinite recursion

        const results = [];
        try {
            const entries = fs.readdirSync(dir, { withFileTypes: true });

            for (const entry of entries) {
                if (!entry.isDirectory()) continue;

                const fullPath = path.join(dir, entry.name);

                // Found a chrome directory - check for .pid files
                if (entry.name === 'chrome') {
                    try {
                        const pidFiles = fs.readdirSync(fullPath).filter(f => f.endsWith('.pid'));
                        const crawlDir = dir;  // Parent of chrome/ is the crawl dir

                        for (const pidFileName of pidFiles) {
                            results.push({
                                pidFile: path.join(fullPath, pidFileName),
                                crawlDir: crawlDir,
                            });
                        }
                    } catch (e) {
                        // Skip if can't read chrome dir
                    }
                } else {
                    // Recurse into subdirectory (skip hidden dirs and node_modules)
                    if (!entry.name.startsWith('.') && entry.name !== 'node_modules') {
                        results.push(...findChromePidFiles(fullPath, depth + 1));
                    }
                }
            }
        } catch (e) {
            // Skip if can't read directory
        }
        return results;
    }

    try {
        const chromePids = findChromePidFiles(dataDir);

        for (const {pidFile, crawlDir} of chromePids) {
            // Check if crawl was modified recently (still active)
            try {
                const crawlStats = fs.statSync(crawlDir);
                if (crawlStats.mtimeMs > fiveMinutesAgo) {
                    continue;  // Crawl is active, skip
                }
            } catch (e) {
                continue;
            }

            // Crawl is stale, check PID
            try {
                const pid = parseInt(fs.readFileSync(pidFile, 'utf8').trim(), 10);
                if (isNaN(pid) || pid <= 0) continue;

                // Check if process exists
                try {
                    process.kill(pid, 0);
                } catch (e) {
                    // Process dead, remove stale PID file
                    try { fs.unlinkSync(pidFile); } catch (e) {}
                    continue;
                }

                // Process alive and crawl is stale - zombie!
                console.error(`[!] Found zombie (PID ${pid}) from stale crawl ${path.basename(crawlDir)}`);

                try {
                    try { process.kill(-pid, 'SIGKILL'); } catch (e) { process.kill(pid, 'SIGKILL'); }
                    killed++;
                    console.error(`[+] Killed zombie (PID ${pid})`);
                    try { fs.unlinkSync(pidFile); } catch (e) {}
                } catch (e) {
                    console.error(`[!] Failed to kill PID ${pid}: ${e.message}`);
                }
            } catch (e) {
                // Skip invalid PID files
            }
        }
    } catch (e) {
        console.error(`[!] Error scanning for Chrome processes: ${e.message}`);
    }

    if (killed > 0) {
        console.error(`[+] Killed ${killed} zombie process(es)`);
    } else {
        console.error('[+] No zombies found');
    }

    // Clean up stale SingletonLock files from persona chrome_user_data directories
    const personasDir = path.join(dataDir, 'personas');
    if (fs.existsSync(personasDir)) {
        try {
            const personas = fs.readdirSync(personasDir, { withFileTypes: true });
            for (const persona of personas) {
                if (!persona.isDirectory()) continue;

                const userDataDir = path.join(personasDir, persona.name, 'chrome_user_data');
                const singletonLock = path.join(userDataDir, 'SingletonLock');

                if (fs.existsSync(singletonLock)) {
                    try {
                        fs.unlinkSync(singletonLock);
                        console.error(`[+] Removed stale SingletonLock: ${singletonLock}`);
                    } catch (e) {
                        // Ignore - may be in use by active Chrome
                    }
                }
            }
        } catch (e) {
            // Ignore errors scanning personas directory
        }
    }

    return killed;
}

// ============================================================================
// Chrome launching
// ============================================================================

/**
 * Launch Chromium with extensions and return connection info.
 *
 * @param {Object} options - Launch options
 * @param {string} [options.binary] - Chrome binary path (auto-detected if not provided)
 * @param {string} [options.outputDir='chrome'] - Directory for output files
 * @param {string} [options.userDataDir] - Chrome user data directory for persistent sessions
 * @param {string} [options.resolution='1440,2000'] - Window resolution
 * @param {boolean} [options.headless=true] - Run in headless mode
 * @param {boolean} [options.sandbox=true] - Enable Chrome sandbox
 * @param {boolean} [options.checkSsl=true] - Check SSL certificates
 * @param {string[]} [options.extensionPaths=[]] - Paths to unpacked extensions
 * @param {boolean} [options.killZombies=true] - Kill zombie processes first
 * @returns {Promise<Object>} - {success, cdpUrl, pid, port, process, error}
 */
async function launchChromium(options = {}) {
    const {
        binary = findChromium(),
        outputDir = 'chrome',
        userDataDir = getEnv('CHROME_USER_DATA_DIR'),
        resolution = getEnv('CHROME_RESOLUTION') || getEnv('RESOLUTION', '1440,2000'),
        headless = getEnvBool('CHROME_HEADLESS', true),
        sandbox = getEnvBool('CHROME_SANDBOX', true),
        checkSsl = getEnvBool('CHROME_CHECK_SSL_VALIDITY', getEnvBool('CHECK_SSL_VALIDITY', true)),
        extensionPaths = [],
        killZombies = true,
    } = options;

    if (!binary) {
        return { success: false, error: 'Chrome binary not found' };
    }

    const downloadsDir = getEnv('CHROME_DOWNLOADS_DIR');

    // Kill zombies first
    if (killZombies) {
        killZombieChrome();
    }

    const { width, height } = parseResolution(resolution);

    // Create output directory
    if (!fs.existsSync(outputDir)) {
        fs.mkdirSync(outputDir, { recursive: true });
    }

    // Create user data directory if specified and doesn't exist
    if (userDataDir) {
        if (!fs.existsSync(userDataDir)) {
            fs.mkdirSync(userDataDir, { recursive: true });
            console.error(`[*] Created user data directory: ${userDataDir}`);
        }
        // Clean up any stale SingletonLock file from previous crashed sessions
        const singletonLock = path.join(userDataDir, 'SingletonLock');
        if (fs.existsSync(singletonLock)) {
            try {
                fs.unlinkSync(singletonLock);
                console.error(`[*] Removed stale SingletonLock: ${singletonLock}`);
            } catch (e) {
                console.error(`[!] Failed to remove SingletonLock: ${e.message}`);
            }
        }
        if (downloadsDir) {
            try {
                const defaultProfileDir = path.join(userDataDir, 'Default');
                const prefsPath = path.join(defaultProfileDir, 'Preferences');
                fs.mkdirSync(defaultProfileDir, { recursive: true });
                let prefs = {};
                if (fs.existsSync(prefsPath)) {
                    try {
                        prefs = JSON.parse(fs.readFileSync(prefsPath, 'utf-8'));
                    } catch (e) {
                        prefs = {};
                    }
                }
                prefs.download = prefs.download || {};
                prefs.download.default_directory = downloadsDir;
                prefs.download.prompt_for_download = false;
                fs.writeFileSync(prefsPath, JSON.stringify(prefs));
                console.error(`[*] Set Chrome download directory: ${downloadsDir}`);
            } catch (e) {
                console.error(`[!] Failed to set Chrome download directory: ${e.message}`);
            }
        }
    }

    // Find a free port
    const debugPort = await findFreePort();
    console.error(`[*] Using debug port: ${debugPort}`);

    // Get base Chrome args from config (static flags from CHROME_ARGS env var)
    // These come from config.json defaults, merged by get_config() in Python
    const baseArgs = getEnvArray('CHROME_ARGS', []);

    // Get extra user-provided args
    const extraArgs = getEnvArray('CHROME_ARGS_EXTRA', []);

    // Build dynamic Chrome arguments (these must be computed at runtime)
    const dynamicArgs = [
        // Remote debugging setup
        `--remote-debugging-port=${debugPort}`,
        '--remote-debugging-address=127.0.0.1',

        // Sandbox settings (disable in Docker)
        ...(sandbox ? [] : ['--no-sandbox', '--disable-setuid-sandbox']),

        // Docker-specific workarounds
        '--disable-dev-shm-usage',
        '--disable-gpu',

        // Window size
        `--window-size=${width},${height}`,

        // User data directory (for persistent sessions with persona)
        ...(userDataDir ? [`--user-data-dir=${userDataDir}`] : []),

        // Headless mode
        ...(headless ? ['--headless=new'] : []),

        // SSL certificate checking
        ...(checkSsl ? [] : ['--ignore-certificate-errors']),
    ];

    // Combine all args: base (from config) + dynamic (runtime) + extra (user overrides)
    // Dynamic args come after base so they can override if needed
    const chromiumArgs = [...baseArgs, ...dynamicArgs, ...extraArgs];

    // Ensure keychain prompts are disabled on macOS
    if (!chromiumArgs.includes('--use-mock-keychain')) {
        chromiumArgs.push('--use-mock-keychain');
    }

    // Add extension loading flags
    if (extensionPaths.length > 0) {
        const extPathsArg = extensionPaths.join(',');
        chromiumArgs.push(`--load-extension=${extPathsArg}`);
        chromiumArgs.push('--enable-unsafe-extension-debugging');
        chromiumArgs.push('--disable-features=DisableLoadExtensionCommandLineSwitch,ExtensionManifestV2Unsupported,ExtensionManifestV2Disabled');
        console.error(`[*] Loading ${extensionPaths.length} extension(s) via --load-extension`);
    }

    chromiumArgs.push('about:blank');

    // Write command script for debugging
    writeCmdScript(path.join(outputDir, 'cmd.sh'), binary, chromiumArgs);

    try {
        console.error(`[*] Spawning Chromium (headless=${headless})...`);
        const chromiumProcess = spawn(binary, chromiumArgs, {
            stdio: ['ignore', 'pipe', 'pipe'],
            detached: true,
        });

        const chromePid = chromiumProcess.pid;
        const chromeStartTime = Date.now() / 1000;

        if (chromePid) {
            console.error(`[*] Chromium spawned (PID: ${chromePid})`);
            writePidWithMtime(path.join(outputDir, 'chrome.pid'), chromePid, chromeStartTime);
        }

        // Pipe Chrome output to stderr
        chromiumProcess.stdout.on('data', (data) => {
            process.stderr.write(`[chromium:stdout] ${data}`);
        });
        chromiumProcess.stderr.on('data', (data) => {
            process.stderr.write(`[chromium:stderr] ${data}`);
        });

        // Wait for debug port
        console.error(`[*] Waiting for debug port ${debugPort}...`);
        const versionInfo = await waitForDebugPort(debugPort, 30000);
        const wsUrl = versionInfo.webSocketDebuggerUrl;
        console.error(`[+] Chromium ready: ${wsUrl}`);

        fs.writeFileSync(path.join(outputDir, 'cdp_url.txt'), wsUrl);
        fs.writeFileSync(path.join(outputDir, 'port.txt'), String(debugPort));

        return {
            success: true,
            cdpUrl: wsUrl,
            pid: chromePid,
            port: debugPort,
            process: chromiumProcess,
        };
    } catch (e) {
        return { success: false, error: `${e.name}: ${e.message}` };
    }
}

/**
 * Check if a process is still running.
 * @param {number} pid - Process ID to check
 * @returns {boolean} - True if process exists
 */
function isProcessAlive(pid) {
    try {
        process.kill(pid, 0);  // Signal 0 checks existence without killing
        return true;
    } catch (e) {
        return false;
    }
}

/**
 * Find all Chrome child processes for a given debug port.
 * @param {number} port - Debug port number
 * @returns {Array<number>} - Array of PIDs
 */
function findChromeProcessesByPort(port) {
    const { execSync } = require('child_process');
    const pids = [];

    try {
        // Find all Chrome processes using this debug port
        const output = execSync(
            `ps aux | grep -i "chrome.*--remote-debugging-port=${port}" | grep -v grep | awk '{print $2}'`,
            { encoding: 'utf8', timeout: 5000 }
        );

        for (const line of output.split('\n')) {
            const pid = parseInt(line.trim(), 10);
            if (!isNaN(pid) && pid > 0) {
                pids.push(pid);
            }
        }
    } catch (e) {
        // Command failed or no processes found
    }

    return pids;
}

/**
 * Kill a Chrome process by PID.
 * Always sends SIGTERM before SIGKILL, then verifies death.
 *
 * @param {number} pid - Process ID to kill
 * @param {string} [outputDir] - Directory containing PID files to clean up
 */
async function killChrome(pid, outputDir = null) {
    if (!pid) return;

    console.error(`[*] Killing Chrome process tree (PID ${pid})...`);

    // Get debug port for finding child processes
    let debugPort = null;
    if (outputDir) {
        try {
            const portFile = path.join(outputDir, 'port.txt');
            if (fs.existsSync(portFile)) {
                debugPort = parseInt(fs.readFileSync(portFile, 'utf8').trim(), 10);
            }
        } catch (e) {}
    }

    // Step 1: SIGTERM to process group (graceful shutdown)
    console.error(`[*] Sending SIGTERM to process group -${pid}...`);
    try {
        process.kill(-pid, 'SIGTERM');
    } catch (e) {
        try {
            console.error(`[*] Process group kill failed, trying single process...`);
            process.kill(pid, 'SIGTERM');
        } catch (e2) {
            console.error(`[!] SIGTERM failed: ${e2.message}`);
        }
    }

    // Step 2: Wait for graceful shutdown
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Step 3: Check if still alive
    if (!isProcessAlive(pid)) {
        console.error('[+] Chrome process terminated gracefully');
    } else {
        // Step 4: Force kill ENTIRE process group with SIGKILL
        console.error(`[*] Process still alive, sending SIGKILL to process group -${pid}...`);
        try {
            process.kill(-pid, 'SIGKILL');  // Kill entire process group
        } catch (e) {
            console.error(`[!] Process group SIGKILL failed, trying single process: ${e.message}`);
            try {
                process.kill(pid, 'SIGKILL');
            } catch (e2) {
                console.error(`[!] SIGKILL failed: ${e2.message}`);
            }
        }

        // Step 5: Wait briefly and verify death
        await new Promise(resolve => setTimeout(resolve, 1000));

        if (isProcessAlive(pid)) {
            console.error(`[!] WARNING: Process ${pid} is unkillable (likely in UNE state)`);
            console.error(`[!] This typically happens when Chrome crashes in kernel syscall`);
            console.error(`[!] Process will remain as zombie until system reboot`);
            console.error(`[!] macOS IOSurface crash creates unkillable processes in UNE state`);

            // Try one more time to kill the entire process group
            if (debugPort) {
                const relatedPids = findChromeProcessesByPort(debugPort);
                if (relatedPids.length > 1) {
                    console.error(`[*] Found ${relatedPids.length} Chrome processes still running on port ${debugPort}`);
                    console.error(`[*] Attempting final process group SIGKILL...`);

                    // Try to kill each unique process group we find
                    const processGroups = new Set();
                    for (const relatedPid of relatedPids) {
                        if (relatedPid !== pid) {
                            processGroups.add(relatedPid);
                        }
                    }

                    for (const groupPid of processGroups) {
                        try {
                            process.kill(-groupPid, 'SIGKILL');
                        } catch (e) {}
                    }
                }
            }
        } else {
            console.error('[+] Chrome process group killed successfully');
        }
    }

    // Step 8: Clean up PID files
    // Note: hook-specific .pid files are cleaned up by run_hook() and Snapshot.cleanup()
    if (outputDir) {
        try { fs.unlinkSync(path.join(outputDir, 'chrome.pid')); } catch (e) {}
    }

    console.error('[*] Chrome cleanup completed');
}

/**
 * Install Chromium using @puppeteer/browsers programmatic API.
 * Uses puppeteer's default cache location, returns the binary path.
 *
 * @param {Object} options - Install options
 * @returns {Promise<Object>} - {success, binary, version, error}
 */
async function installChromium(options = {}) {
    // Check if CHROME_BINARY is already set and valid
    const configuredBinary = getEnv('CHROME_BINARY');
    if (configuredBinary && fs.existsSync(configuredBinary)) {
        console.error(`[+] Using configured CHROME_BINARY: ${configuredBinary}`);
        return { success: true, binary: configuredBinary, version: null };
    }

    // Try to load @puppeteer/browsers from NODE_MODULES_DIR or system
    let puppeteerBrowsers;
    try {
        if (process.env.NODE_MODULES_DIR) {
            module.paths.unshift(process.env.NODE_MODULES_DIR);
        }
        puppeteerBrowsers = require('@puppeteer/browsers');
    } catch (e) {
        console.error(`[!] @puppeteer/browsers not found. Install it first with installPuppeteerCore.`);
        return { success: false, error: '@puppeteer/browsers not installed' };
    }

    console.error(`[*] Installing Chromium via @puppeteer/browsers...`);

    try {
        const result = await puppeteerBrowsers.install({
            browser: 'chromium',
            buildId: 'latest',
        });

        const binary = result.executablePath;
        const version = result.buildId;

        if (!binary || !fs.existsSync(binary)) {
            console.error(`[!] Chromium binary not found at: ${binary}`);
            return { success: false, error: `Chromium binary not found at: ${binary}` };
        }

        console.error(`[+] Chromium installed: ${binary}`);
        return { success: true, binary, version };
    } catch (e) {
        console.error(`[!] Failed to install Chromium: ${e.message}`);
        return { success: false, error: e.message };
    }
}

/**
 * Install puppeteer-core npm package.
 *
 * @param {Object} options - Install options
 * @param {string} [options.npmPrefix] - npm prefix directory (default: DATA_DIR/lib/<arch>/npm or ./node_modules parent)
 * @param {number} [options.timeout=60000] - Timeout in milliseconds
 * @returns {Promise<Object>} - {success, path, error}
 */
async function installPuppeteerCore(options = {}) {
    const arch = `${process.arch}-${process.platform}`;
    const defaultPrefix = path.join(getEnv('LIB_DIR', getEnv('DATA_DIR', '.')), 'npm');
    const {
        npmPrefix = defaultPrefix,
        timeout = 60000,
    } = options;

    const nodeModulesDir = path.join(npmPrefix, 'node_modules');
    const puppeteerPath = path.join(nodeModulesDir, 'puppeteer-core');

    // Check if already installed
    if (fs.existsSync(puppeteerPath)) {
        console.error(`[+] puppeteer-core already installed: ${puppeteerPath}`);
        return { success: true, path: puppeteerPath };
    }

    console.error(`[*] Installing puppeteer-core to ${npmPrefix}...`);

    // Create directory
    if (!fs.existsSync(npmPrefix)) {
        fs.mkdirSync(npmPrefix, { recursive: true });
    }

    try {
        const { execSync } = require('child_process');
        execSync(
            `npm install --prefix "${npmPrefix}" puppeteer-core`,
            { encoding: 'utf8', timeout, stdio: ['pipe', 'pipe', 'pipe'] }
        );
        console.error(`[+] puppeteer-core installed successfully`);
        return { success: true, path: puppeteerPath };
    } catch (e) {
        console.error(`[!] Failed to install puppeteer-core: ${e.message}`);
        return { success: false, error: e.message };
    }
}

// Try to import unzipper, fallback to system unzip if not available
let unzip = null;
try {
    const unzipper = require('unzipper');
    unzip = async (sourcePath, destPath) => {
        const stream = fs.createReadStream(sourcePath).pipe(unzipper.Extract({ path: destPath }));
        return stream.promise();
    };
} catch (err) {
    // Will use system unzip command as fallback
}

/**
 * Compute the extension ID from the unpacked path.
 * Chrome uses a SHA256 hash of the unpacked extension directory path to compute a dynamic id.
 *
 * @param {string} unpacked_path - Path to the unpacked extension directory
 * @returns {string} - 32-character extension ID
 */
function getExtensionId(unpacked_path) {
    let resolved_path = unpacked_path;
    try {
        resolved_path = fs.realpathSync(unpacked_path);
    } catch (err) {
        // Use the provided path if realpath fails
        resolved_path = unpacked_path;
    }
    // Chrome uses a SHA256 hash of the unpacked extension directory path
    const hash = crypto.createHash('sha256');
    hash.update(Buffer.from(resolved_path, 'utf-8'));

    // Convert first 32 hex chars to characters in the range 'a'-'p'
    const detected_extension_id = Array.from(hash.digest('hex'))
        .slice(0, 32)
        .map(i => String.fromCharCode(parseInt(i, 16) + 'a'.charCodeAt(0)))
        .join('');

    return detected_extension_id;
}

/**
 * Download and install a Chrome extension from the Chrome Web Store.
 *
 * @param {Object} extension - Extension metadata object
 * @param {string} extension.webstore_id - Chrome Web Store extension ID
 * @param {string} extension.name - Human-readable extension name
 * @param {string} extension.crx_url - URL to download the CRX file
 * @param {string} extension.crx_path - Local path to save the CRX file
 * @param {string} extension.unpacked_path - Path to extract the extension
 * @returns {Promise<boolean>} - True if installation succeeded
 */
async function installExtension(extension) {
    const manifest_path = path.join(extension.unpacked_path, 'manifest.json');

    // Download CRX file if not already downloaded
    if (!fs.existsSync(manifest_path) && !fs.existsSync(extension.crx_path)) {
        console.log(`[🛠️] Downloading missing extension ${extension.name} ${extension.webstore_id} -> ${extension.crx_path}`);

        try {
            // Ensure parent directory exists
            const crxDir = path.dirname(extension.crx_path);
            if (!fs.existsSync(crxDir)) {
                fs.mkdirSync(crxDir, { recursive: true });
            }

            // Download CRX file from Chrome Web Store
            const response = await fetch(extension.crx_url);

            if (!response.ok) {
                console.warn(`[⚠️] Failed to download extension ${extension.name}: HTTP ${response.status}`);
                return false;
            }

            if (response.body) {
                const crx_file = fs.createWriteStream(extension.crx_path);
                const crx_stream = Readable.fromWeb(response.body);
                await finished(crx_stream.pipe(crx_file));
            } else {
                console.warn(`[⚠️] Failed to download extension ${extension.name}: No response body`);
                return false;
            }
        } catch (err) {
            console.error(`[❌] Failed to download extension ${extension.name}:`, err);
            return false;
        }
    }

    // Unzip CRX file to unpacked_path (CRX files have extra header bytes but unzip handles it)
    await fs.promises.mkdir(extension.unpacked_path, { recursive: true });

    try {
        // Use -q to suppress warnings about extra bytes in CRX header
        await execAsync(`/usr/bin/unzip -q -o "${extension.crx_path}" -d "${extension.unpacked_path}"`);
    } catch (err1) {
        // unzip may return non-zero even on success due to CRX header warning, check if manifest exists
        if (!fs.existsSync(manifest_path)) {
            if (unzip) {
                // Fallback to unzipper library
                try {
                    await unzip(extension.crx_path, extension.unpacked_path);
                } catch (err2) {
                    console.error(`[❌] Failed to unzip ${extension.crx_path}:`, err2.message);
                    return false;
                }
            } else {
                console.error(`[❌] Failed to unzip ${extension.crx_path}:`, err1.message);
                return false;
            }
        }
    }

    if (!fs.existsSync(manifest_path)) {
        console.error(`[❌] Failed to install ${extension.crx_path}: could not find manifest.json in unpacked_path`);
        return false;
    }

    return true;
}

/**
 * Load or install a Chrome extension, computing all metadata.
 *
 * @param {Object} ext - Partial extension metadata (at minimum: webstore_id or unpacked_path)
 * @param {string} [ext.webstore_id] - Chrome Web Store extension ID
 * @param {string} [ext.name] - Human-readable extension name
 * @param {string} [ext.unpacked_path] - Path to unpacked extension
 * @param {string} [extensions_dir] - Directory to store extensions
 * @returns {Promise<Object>} - Complete extension metadata object
 */
async function loadOrInstallExtension(ext, extensions_dir = null) {
    if (!(ext.webstore_id || ext.unpacked_path)) {
        throw new Error('Extension must have either {webstore_id} or {unpacked_path}');
    }

    // Determine extensions directory
    // Use provided dir, or fall back to getExtensionsDir() which handles env vars and defaults
    const EXTENSIONS_DIR = extensions_dir || getExtensionsDir();

    // Set statically computable extension metadata
    ext.webstore_id = ext.webstore_id || ext.id;
    ext.name = ext.name || ext.webstore_id;
    ext.webstore_url = ext.webstore_url || `https://chromewebstore.google.com/detail/${ext.webstore_id}`;
    ext.crx_url = ext.crx_url || `https://clients2.google.com/service/update2/crx?response=redirect&prodversion=1230&acceptformat=crx3&x=id%3D${ext.webstore_id}%26uc`;
    ext.crx_path = ext.crx_path || path.join(EXTENSIONS_DIR, `${ext.webstore_id}__${ext.name}.crx`);
    ext.unpacked_path = ext.unpacked_path || path.join(EXTENSIONS_DIR, `${ext.webstore_id}__${ext.name}`);

    const manifest_path = path.join(ext.unpacked_path, 'manifest.json');
    ext.read_manifest = () => JSON.parse(fs.readFileSync(manifest_path, 'utf-8'));
    ext.read_version = () => fs.existsSync(manifest_path) && ext.read_manifest()?.version || null;

    // If extension is not installed, download and unpack it
    if (!ext.read_version()) {
        await installExtension(ext);
    }

    // Autodetect ID from filesystem path (unpacked extensions don't have stable IDs)
    ext.id = getExtensionId(ext.unpacked_path);
    ext.version = ext.read_version();

    if (!ext.version) {
        console.warn(`[❌] Unable to detect ID and version of installed extension ${ext.unpacked_path}`);
    } else {
        console.log(`[➕] Installed extension ${ext.name} (${ext.version})... ${ext.unpacked_path}`);
    }

    return ext;
}

/**
 * Check if a Puppeteer target is an extension background page/service worker.
 *
 * @param {Object} target - Puppeteer target object
 * @returns {Promise<Object>} - Object with target_is_bg, extension_id, manifest_version, etc.
 */
async function isTargetExtension(target) {
    let target_type;
    let target_ctx;
    let target_url;

    try {
        target_type = target.type();
        target_ctx = (await target.worker()) || (await target.page()) || null;
        target_url = target.url() || target_ctx?.url() || null;
    } catch (err) {
        if (String(err).includes('No target with given id found')) {
            // Target closed during check, ignore harmless race condition
            target_type = 'closed';
            target_ctx = null;
            target_url = 'about:closed';
        } else {
            throw err;
        }
    }

    // Check if this is an extension background page or service worker
    const is_chrome_extension = target_url?.startsWith('chrome-extension://');
    const is_background_page = target_type === 'background_page';
    const is_service_worker = target_type === 'service_worker';
    const target_is_bg = is_chrome_extension && (is_background_page || is_service_worker);

    let extension_id = null;
    let manifest_version = null;
    let manifest = null;
    let manifest_name = null;
    const target_is_extension = is_chrome_extension || target_is_bg;

    if (target_is_extension) {
        try {
            extension_id = target_url?.split('://')[1]?.split('/')[0] || null;

            if (target_ctx) {
                manifest = await target_ctx.evaluate(() => chrome.runtime.getManifest());
                manifest_version = manifest?.manifest_version || null;
                manifest_name = manifest?.name || null;
            }
        } catch (err) {
            // Failed to get extension metadata
        }
    }

    return {
        target_is_extension,
        target_is_bg,
        target_type,
        target_ctx,
        target_url,
        extension_id,
        manifest_version,
        manifest,
        manifest_name,
    };
}

/**
 * Load extension metadata and connection handlers from a browser target.
 *
 * @param {Array} extensions - Array of extension metadata objects to update
 * @param {Object} target - Puppeteer target object
 * @returns {Promise<Object|null>} - Updated extension object or null if not an extension
 */
async function loadExtensionFromTarget(extensions, target) {
    const {
        target_is_bg,
        target_is_extension,
        target_type,
        target_ctx,
        target_url,
        extension_id,
        manifest_version,
    } = await isTargetExtension(target);

    if (!(target_is_bg && extension_id && target_ctx)) {
        return null;
    }

    // Find matching extension in our list
    const extension = extensions.find(ext => ext.id === extension_id);
    if (!extension) {
        console.warn(`[⚠️] Found loaded extension ${extension_id} that's not in CHROME_EXTENSIONS list`);
        return null;
    }

    // Load manifest from the extension context
    let manifest = null;
    try {
        manifest = await target_ctx.evaluate(() => chrome.runtime.getManifest());
    } catch (err) {
        console.error(`[❌] Failed to read manifest for extension ${extension_id}:`, err);
        return null;
    }

    // Create dispatch methods for communicating with the extension
    const new_extension = {
        ...extension,
        target,
        target_type,
        target_url,
        manifest,
        manifest_version,

        // Trigger extension toolbar button click
        dispatchAction: async (tab) => {
            return await target_ctx.evaluate(async (tab) => {
                tab = tab || (await new Promise((resolve) =>
                    chrome.tabs.query({ currentWindow: true, active: true }, ([tab]) => resolve(tab))
                ));

                // Manifest V3: chrome.action
                if (chrome.action?.onClicked?.dispatch) {
                    return await chrome.action.onClicked.dispatch(tab);
                }

                // Manifest V2: chrome.browserAction
                if (chrome.browserAction?.onClicked?.dispatch) {
                    return await chrome.browserAction.onClicked.dispatch(tab);
                }

                throw new Error('Extension action dispatch not available');
            }, tab || null);
        },

        // Send message to extension
        dispatchMessage: async (message, options = {}) => {
            return await target_ctx.evaluate((msg, opts) => {
                return new Promise((resolve) => {
                    chrome.runtime.sendMessage(msg, opts, (response) => {
                        resolve(response);
                    });
                });
            }, message, options);
        },

        // Trigger extension command (keyboard shortcut)
        dispatchCommand: async (command) => {
            return await target_ctx.evaluate((cmd) => {
                return new Promise((resolve) => {
                    chrome.commands.onCommand.addListener((receivedCommand) => {
                        if (receivedCommand === cmd) {
                            resolve({ success: true, command: receivedCommand });
                        }
                    });
                    // Note: Actually triggering commands programmatically is not directly supported
                    // This would need to be done via CDP or keyboard simulation
                });
            }, command);
        },
    };

    // Update the extension in the array
    Object.assign(extension, new_extension);

    console.log(`[🔌] Connected to extension ${extension.name} (${extension.version})`);

    return new_extension;
}

/**
 * Install all extensions in the list if not already installed.
 *
 * @param {Array} extensions - Array of extension metadata objects
 * @param {string} [extensions_dir] - Directory to store extensions
 * @returns {Promise<Array>} - Array of installed extension objects
 */
async function installAllExtensions(extensions, extensions_dir = null) {
    console.log(`[⚙️] Installing ${extensions.length} chrome extensions...`);

    for (const extension of extensions) {
        await loadOrInstallExtension(extension, extensions_dir);
    }

    return extensions;
}

/**
 * Load and connect to all extensions from a running browser.
 *
 * @param {Object} browser - Puppeteer browser instance
 * @param {Array} extensions - Array of extension metadata objects
 * @returns {Promise<Array>} - Array of loaded extension objects with connection handlers
 */
async function loadAllExtensionsFromBrowser(browser, extensions) {
    console.log(`[⚙️] Loading ${extensions.length} chrome extensions from browser...`);

    // Find loaded extensions at runtime by examining browser targets
    for (const target of browser.targets()) {
        await loadExtensionFromTarget(extensions, target);
    }

    return extensions;
}

/**
 * Load extension manifest.json file
 *
 * @param {string} unpacked_path - Path to unpacked extension directory
 * @returns {object|null} - Parsed manifest object or null if not found/invalid
 */
function loadExtensionManifest(unpacked_path) {
    const manifest_path = path.join(unpacked_path, 'manifest.json');

    if (!fs.existsSync(manifest_path)) {
        return null;
    }

    try {
        const manifest_content = fs.readFileSync(manifest_path, 'utf-8');
        return JSON.parse(manifest_content);
    } catch (error) {
        // Invalid JSON or read error
        return null;
    }
}

/**
 * @deprecated Use puppeteer's enableExtensions option instead.
 *
 * Generate Chrome launch arguments for loading extensions.
 * NOTE: This is deprecated. Use puppeteer.launch({ pipe: true, enableExtensions: [paths] }) instead.
 *
 * @param {Array} extensions - Array of extension metadata objects
 * @returns {Array<string>} - Chrome CLI arguments for loading extensions
 */
function getExtensionLaunchArgs(extensions) {
    console.warn('[DEPRECATED] getExtensionLaunchArgs is deprecated. Use puppeteer enableExtensions option instead.');
    if (!extensions || extensions.length === 0) {
        return [];
    }

    // Filter out extensions without unpacked_path first
    const validExtensions = extensions.filter(ext => ext.unpacked_path);

    const unpacked_paths = validExtensions.map(ext => ext.unpacked_path);
    // Use computed id (from path hash) for allowlisting, as that's what Chrome uses for unpacked extensions
    // Fall back to webstore_id if computed id not available
    const extension_ids = validExtensions.map(ext => ext.id || getExtensionId(ext.unpacked_path));

    return [
        `--load-extension=${unpacked_paths.join(',')}`,
        `--allowlisted-extension-id=${extension_ids.join(',')}`,
        '--allow-legacy-extension-manifests',
        '--disable-extensions-auto-update',
    ];
}

/**
 * Get extension paths for use with puppeteer's enableExtensions option.
 * Following puppeteer best practices: https://pptr.dev/guides/chrome-extensions
 *
 * @param {Array} extensions - Array of extension metadata objects
 * @returns {Array<string>} - Array of extension unpacked paths
 */
function getExtensionPaths(extensions) {
    if (!extensions || extensions.length === 0) {
        return [];
    }
    return extensions
        .filter(ext => ext.unpacked_path)
        .map(ext => ext.unpacked_path);
}

/**
 * Wait for an extension target to be available in the browser.
 * Following puppeteer best practices for accessing extension contexts.
 *
 * For Manifest V3 extensions (service workers):
 *   const worker = await waitForExtensionTarget(browser, extensionId);
 *   // worker is a WebWorker context
 *
 * For Manifest V2 extensions (background pages):
 *   const page = await waitForExtensionTarget(browser, extensionId);
 *   // page is a Page context
 *
 * @param {Object} browser - Puppeteer browser instance
 * @param {string} extensionId - Extension ID to wait for (computed from path hash)
 * @param {number} [timeout=30000] - Timeout in milliseconds
 * @returns {Promise<Object>} - Worker or Page context for the extension
 */
async function waitForExtensionTarget(browser, extensionId, timeout = 30000) {
    // Try to find service worker first (Manifest V3)
    try {
        const workerTarget = await browser.waitForTarget(
            target => target.type() === 'service_worker' &&
                target.url().includes(`chrome-extension://${extensionId}`),
            { timeout }
        );
        const worker = await workerTarget.worker();
        if (worker) return worker;
    } catch (err) {
        // No service worker found, try background page
    }

    // Try background page (Manifest V2)
    try {
        const backgroundTarget = await browser.waitForTarget(
            target => target.type() === 'background_page' &&
                target.url().includes(`chrome-extension://${extensionId}`),
            { timeout }
        );
        const page = await backgroundTarget.page();
        if (page) return page;
    } catch (err) {
        // No background page found
    }

    // Try any extension page as fallback
    const extTarget = await browser.waitForTarget(
        target => target.url().startsWith(`chrome-extension://${extensionId}`),
        { timeout }
    );

    // Return worker or page depending on target type
    if (extTarget.type() === 'service_worker') {
        return await extTarget.worker();
    }
    return await extTarget.page();
}

/**
 * Get all loaded extension targets from a browser.
 *
 * @param {Object} browser - Puppeteer browser instance
 * @returns {Array<Object>} - Array of extension target info objects
 */
function getExtensionTargets(browser) {
    return browser.targets()
        .filter(target =>
            target.url().startsWith('chrome-extension://') ||
            target.type() === 'service_worker' ||
            target.type() === 'background_page'
        )
        .map(target => ({
            type: target.type(),
            url: target.url(),
            extensionId: target.url().includes('chrome-extension://')
                ? target.url().split('chrome-extension://')[1]?.split('/')[0]
                : null,
        }));
}

/**
 * Find Chromium binary path.
 * Checks CHROME_BINARY env var first, then falls back to system locations.
 *
 * @returns {string|null} - Absolute path to browser binary or null if not found
 */
function findChromium() {
    const { execSync } = require('child_process');

    // Helper to validate a binary by running --version
    const validateBinary = (binaryPath) => {
        if (!binaryPath || !fs.existsSync(binaryPath)) return false;
        try {
            execSync(`"${binaryPath}" --version`, { encoding: 'utf8', timeout: 5000, stdio: 'pipe' });
            return true;
        } catch (e) {
            return false;
        }
    };

    // 1. Check CHROME_BINARY env var first
    const chromeBinary = getEnv('CHROME_BINARY');
    if (chromeBinary) {
        const absPath = path.resolve(chromeBinary);
        if (absPath.includes('Google Chrome') || absPath.includes('google-chrome')) {
            console.error('[!] Warning: CHROME_BINARY points to Chrome. Chromium is required for extension support.');
        } else if (validateBinary(absPath)) {
            return absPath;
        }
        console.error(`[!] Warning: CHROME_BINARY="${chromeBinary}" is not valid`);
    }

    // 2. Warn that no CHROME_BINARY is configured, searching fallbacks
    if (!chromeBinary) {
        console.error('[!] Warning: CHROME_BINARY not set, searching system locations...');
    }

    // Helper to find Chromium in @puppeteer/browsers directory structure
    const findInPuppeteerDir = (baseDir) => {
        if (!fs.existsSync(baseDir)) return null;
        try {
            const versions = fs.readdirSync(baseDir);
            for (const version of versions.sort().reverse()) {
                const versionDir = path.join(baseDir, version);
                const candidates = [
                    path.join(versionDir, 'chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium'),
                    path.join(versionDir, 'chrome-mac/Chromium.app/Contents/MacOS/Chromium'),
                    path.join(versionDir, 'chrome-mac-x64/Chromium.app/Contents/MacOS/Chromium'),
                    path.join(versionDir, 'chrome-linux64/chrome'),
                    path.join(versionDir, 'chrome-linux/chrome'),
                ];
                for (const c of candidates) {
                    if (fs.existsSync(c)) return c;
                }
            }
        } catch (e) {}
        return null;
    };

    // 3. Search fallback locations (Chromium only)
    const fallbackLocations = [
        // System Chromium
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        // Puppeteer cache
        path.join(process.env.HOME || '', '.cache/puppeteer/chromium'),
        path.join(process.env.HOME || '', '.cache/puppeteer'),
    ];

    for (const loc of fallbackLocations) {
        // Check if it's a puppeteer cache dir
        if (loc.includes('.cache/puppeteer')) {
            const binary = findInPuppeteerDir(loc);
            if (binary && validateBinary(binary)) {
                return binary;
            }
        } else if (validateBinary(loc)) {
            return loc;
        }
    }

    return null;
}

// ============================================================================
// Shared Extension Installer Utilities
// ============================================================================

/**
 * Get the extensions directory path.
 * Centralized path calculation used by extension installers and chrome launch.
 *
 * Path is derived from environment variables in this priority:
 * 1. CHROME_EXTENSIONS_DIR (explicit override)
 * 2. DATA_DIR/personas/ACTIVE_PERSONA/chrome_extensions (default)
 *
 * @returns {string} - Absolute path to extensions directory
 */
function getExtensionsDir() {
    const dataDir = getEnv('DATA_DIR', '.');
    const persona = getEnv('ACTIVE_PERSONA', 'Default');
    return getEnv('CHROME_EXTENSIONS_DIR') ||
        path.join(dataDir, 'personas', persona, 'chrome_extensions');
}

/**
 * Get machine type string for platform-specific paths.
 * Matches Python's archivebox.config.paths.get_machine_type()
 *
 * @returns {string} - Machine type (e.g., 'x86_64-linux', 'arm64-darwin')
 */
function getMachineType() {
    if (process.env.MACHINE_TYPE) {
        return process.env.MACHINE_TYPE;
    }

    let machine = process.arch;
    const system = process.platform;

    // Normalize machine type to match Python's convention
    if (machine === 'arm64' || machine === 'aarch64') {
        machine = 'arm64';
    } else if (machine === 'x64' || machine === 'x86_64' || machine === 'amd64') {
        machine = 'x86_64';
    } else if (machine === 'ia32' || machine === 'x86') {
        machine = 'x86';
    }

    return `${machine}-${system}`;
}

/**
 * Get LIB_DIR path for platform-specific binaries.
 * Returns DATA_DIR/lib/MACHINE_TYPE/
 *
 * @returns {string} - Absolute path to lib directory
 */
function getLibDir() {
    if (process.env.LIB_DIR) {
        return path.resolve(process.env.LIB_DIR);
    }
    const dataDir = getEnv('DATA_DIR', './data');
    const machineType = getMachineType();
    return path.resolve(path.join(dataDir, 'lib', machineType));
}

/**
 * Get NODE_MODULES_DIR path for npm packages.
 * Returns LIB_DIR/npm/node_modules/
 *
 * @returns {string} - Absolute path to node_modules directory
 */
function getNodeModulesDir() {
    if (process.env.NODE_MODULES_DIR) {
        return path.resolve(process.env.NODE_MODULES_DIR);
    }
    return path.resolve(path.join(getLibDir(), 'npm', 'node_modules'));
}

/**
 * Get all test environment paths as a JSON object.
 * This is the single source of truth for path calculations - Python calls this
 * to avoid duplicating path logic.
 *
 * @returns {Object} - Object with all test environment paths
 */
function getTestEnv() {
    const dataDir = getEnv('DATA_DIR', './data');
    const machineType = getMachineType();
    const libDir = getLibDir();
    const nodeModulesDir = getNodeModulesDir();

    return {
        DATA_DIR: dataDir,
        MACHINE_TYPE: machineType,
        LIB_DIR: libDir,
        NODE_MODULES_DIR: nodeModulesDir,
        NODE_PATH: nodeModulesDir,  // Node.js uses NODE_PATH for module resolution
        NPM_BIN_DIR: path.join(libDir, 'npm', '.bin'),
        CHROME_EXTENSIONS_DIR: getExtensionsDir(),
    };
}

/**
 * Install a Chrome extension with caching support.
 *
 * This is the main entry point for extension installer hooks. It handles:
 * - Checking for cached extension metadata
 * - Installing the extension if not cached
 * - Writing cache file for future runs
 *
 * @param {Object} extension - Extension metadata object
 * @param {string} extension.webstore_id - Chrome Web Store extension ID
 * @param {string} extension.name - Human-readable extension name (used for cache file)
 * @param {Object} [options] - Options
 * @param {string} [options.extensionsDir] - Override extensions directory
 * @param {boolean} [options.quiet=false] - Suppress info logging
 * @returns {Promise<Object|null>} - Installed extension metadata or null on failure
 */
async function installExtensionWithCache(extension, options = {}) {
    const {
        extensionsDir = getExtensionsDir(),
        quiet = false,
    } = options;

    const cacheFile = path.join(extensionsDir, `${extension.name}.extension.json`);

    // Check if extension is already cached and valid
    if (fs.existsSync(cacheFile)) {
        try {
            const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf-8'));
            const manifestPath = path.join(cached.unpacked_path, 'manifest.json');

            if (fs.existsSync(manifestPath)) {
                if (!quiet) {
                    console.log(`[*] ${extension.name} extension already installed (using cache)`);
                }
                return cached;
            }
        } catch (e) {
            // Cache file corrupted, re-install
            console.warn(`[⚠️] Extension cache corrupted for ${extension.name}, re-installing...`);
        }
    }

    // Install extension
    if (!quiet) {
        console.log(`[*] Installing ${extension.name} extension...`);
    }

    const installedExt = await loadOrInstallExtension(extension, extensionsDir);

    if (!installedExt?.version) {
        console.error(`[❌] Failed to install ${extension.name} extension`);
        return null;
    }

    // Write cache file
    try {
        await fs.promises.mkdir(extensionsDir, { recursive: true });
        await fs.promises.writeFile(cacheFile, JSON.stringify(installedExt, null, 2));
        if (!quiet) {
            console.log(`[+] Extension metadata written to ${cacheFile}`);
        }
    } catch (e) {
        console.warn(`[⚠️] Failed to write cache file: ${e.message}`);
    }

    if (!quiet) {
        console.log(`[+] ${extension.name} extension installed`);
    }

    return installedExt;
}

// ============================================================================
// Snapshot Hook Utilities (for CDP-based plugins like ssl, responses, dns)
// ============================================================================

/**
 * Parse command line arguments into an object.
 * Handles --key=value and --flag formats.
 *
 * @returns {Object} - Parsed arguments object
 */
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

/**
 * Wait for Chrome session files to be ready.
 * Polls for cdp_url.txt and target_id.txt in the chrome session directory.
 *
 * @param {string} chromeSessionDir - Path to chrome session directory (e.g., '../chrome')
 * @param {number} [timeoutMs=60000] - Timeout in milliseconds
 * @returns {Promise<boolean>} - True if files are ready, false if timeout
 */
async function waitForChromeSession(chromeSessionDir, timeoutMs = 60000) {
    const cdpFile = path.join(chromeSessionDir, 'cdp_url.txt');
    const targetIdFile = path.join(chromeSessionDir, 'target_id.txt');
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        if (fs.existsSync(cdpFile) && fs.existsSync(targetIdFile)) {
            return true;
        }
        await new Promise(resolve => setTimeout(resolve, 100));
    }

    return false;
}

/**
 * Read CDP WebSocket URL from chrome session directory.
 *
 * @param {string} chromeSessionDir - Path to chrome session directory
 * @returns {string|null} - CDP URL or null if not found
 */
function readCdpUrl(chromeSessionDir) {
    const cdpFile = path.join(chromeSessionDir, 'cdp_url.txt');
    if (fs.existsSync(cdpFile)) {
        return fs.readFileSync(cdpFile, 'utf8').trim();
    }
    return null;
}

/**
 * Read target ID from chrome session directory.
 *
 * @param {string} chromeSessionDir - Path to chrome session directory
 * @returns {string|null} - Target ID or null if not found
 */
function readTargetId(chromeSessionDir) {
    const targetIdFile = path.join(chromeSessionDir, 'target_id.txt');
    if (fs.existsSync(targetIdFile)) {
        return fs.readFileSync(targetIdFile, 'utf8').trim();
    }
    return null;
}

/**
 * Connect to Chrome browser and find the target page.
 * This is a high-level utility that handles all the connection logic:
 * 1. Wait for chrome session files
 * 2. Connect to browser via CDP
 * 3. Find the target page by ID
 *
 * @param {Object} options - Connection options
 * @param {string} [options.chromeSessionDir='../chrome'] - Path to chrome session directory
 * @param {number} [options.timeoutMs=60000] - Timeout for waiting
 * @param {Object} [options.puppeteer] - Puppeteer module (must be passed in)
 * @returns {Promise<Object>} - { browser, page, targetId, cdpUrl }
 * @throws {Error} - If connection fails or page not found
 */
async function connectToPage(options = {}) {
    const {
        chromeSessionDir = '../chrome',
        timeoutMs = 60000,
        puppeteer,
    } = options;

    if (!puppeteer) {
        throw new Error('puppeteer module must be passed to connectToPage()');
    }

    // Wait for chrome session to be ready
    const sessionReady = await waitForChromeSession(chromeSessionDir, timeoutMs);
    if (!sessionReady) {
        throw new Error(`Chrome session not ready after ${timeoutMs/1000}s (chrome plugin must run first)`);
    }

    // Read session files
    const cdpUrl = readCdpUrl(chromeSessionDir);
    if (!cdpUrl) {
        throw new Error('No Chrome session found (cdp_url.txt missing)');
    }

    const targetId = readTargetId(chromeSessionDir);

    // Connect to browser
    const browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

    // Find the target page
    const pages = await browser.pages();
    let page = null;

    if (targetId) {
        page = pages.find(p => {
            const target = p.target();
            return target && target._targetId === targetId;
        });
    }

    // Fallback to last page if target not found
    if (!page) {
        page = pages[pages.length - 1];
    }

    if (!page) {
        throw new Error('No page found in browser');
    }

    return { browser, page, targetId, cdpUrl };
}

/**
 * Wait for page navigation to complete.
 * Polls for page_loaded.txt marker file written by chrome_navigate.
 *
 * @param {string} chromeSessionDir - Path to chrome session directory
 * @param {number} [timeoutMs=120000] - Timeout in milliseconds
 * @param {number} [postLoadDelayMs=0] - Additional delay after page load marker
 * @returns {Promise<void>}
 * @throws {Error} - If timeout waiting for navigation
 */
async function waitForPageLoaded(chromeSessionDir, timeoutMs = 120000, postLoadDelayMs = 0) {
    const pageLoadedMarker = path.join(chromeSessionDir, 'page_loaded.txt');
    const pollInterval = 100;
    let waitTime = 0;

    while (!fs.existsSync(pageLoadedMarker) && waitTime < timeoutMs) {
        await new Promise(resolve => setTimeout(resolve, pollInterval));
        waitTime += pollInterval;
    }

    if (!fs.existsSync(pageLoadedMarker)) {
        throw new Error('Timeout waiting for navigation (chrome_navigate did not complete)');
    }

    // Optional post-load delay for late responses
    if (postLoadDelayMs > 0) {
        await new Promise(resolve => setTimeout(resolve, postLoadDelayMs));
    }
}

// Export all functions
module.exports = {
    // Environment helpers
    getEnv,
    getEnvBool,
    getEnvInt,
    getEnvArray,
    parseResolution,
    // PID file management
    writePidWithMtime,
    writeCmdScript,
    // Port management
    findFreePort,
    waitForDebugPort,
    // Zombie cleanup
    killZombieChrome,
    // Chrome launching
    launchChromium,
    killChrome,
    // Chromium install
    installChromium,
    installPuppeteerCore,
    // Chromium binary finding
    findChromium,
    // Extension utilities
    getExtensionId,
    loadExtensionManifest,
    installExtension,
    loadOrInstallExtension,
    isTargetExtension,
    loadExtensionFromTarget,
    installAllExtensions,
    loadAllExtensionsFromBrowser,
    // New puppeteer best-practices helpers
    getExtensionPaths,
    waitForExtensionTarget,
    getExtensionTargets,
    // Shared path utilities (single source of truth for Python/JS)
    getMachineType,
    getLibDir,
    getNodeModulesDir,
    getExtensionsDir,
    getTestEnv,
    // Shared extension installer utilities
    installExtensionWithCache,
    // Deprecated - use enableExtensions option instead
    getExtensionLaunchArgs,
    // Snapshot hook utilities (for CDP-based plugins)
    parseArgs,
    waitForChromeSession,
    readCdpUrl,
    readTargetId,
    connectToPage,
    waitForPageLoaded,
};

// CLI usage
if (require.main === module) {
    const args = process.argv.slice(2);

    if (args.length === 0) {
        console.log('Usage: chrome_utils.js <command> [args...]');
        console.log('');
        console.log('Commands:');
        console.log('  findChromium              Find Chromium binary');
        console.log('  installChromium           Install Chromium via @puppeteer/browsers');
        console.log('  installPuppeteerCore      Install puppeteer-core npm package');
        console.log('  launchChromium            Launch Chrome with CDP debugging');
        console.log('  killChrome <pid>          Kill Chrome process by PID');
        console.log('  killZombieChrome          Clean up zombie Chrome processes');
        console.log('');
        console.log('  getMachineType            Get machine type (e.g., x86_64-linux)');
        console.log('  getLibDir                 Get LIB_DIR path');
        console.log('  getNodeModulesDir         Get NODE_MODULES_DIR path');
        console.log('  getExtensionsDir          Get Chrome extensions directory');
        console.log('  getTestEnv                Get all paths as JSON (for tests)');
        console.log('');
        console.log('  getExtensionId <path>     Get extension ID from unpacked path');
        console.log('  loadExtensionManifest     Load extension manifest.json');
        console.log('  loadOrInstallExtension    Load or install an extension');
        console.log('  installExtensionWithCache Install extension with caching');
        console.log('');
        console.log('Environment variables:');
        console.log('  DATA_DIR                  Base data directory');
        console.log('  LIB_DIR                   Library directory (computed if not set)');
        console.log('  MACHINE_TYPE              Machine type override');
        console.log('  NODE_MODULES_DIR          Node modules directory');
        console.log('  CHROME_BINARY             Chrome binary path');
        console.log('  CHROME_EXTENSIONS_DIR     Extensions directory');
        process.exit(1);
    }

    const [command, ...commandArgs] = args;

    (async () => {
        try {
            switch (command) {
                case 'findChromium': {
                    const binary = findChromium();
                    if (binary) {
                        console.log(binary);
                    } else {
                        console.error('Chromium binary not found');
                        process.exit(1);
                    }
                    break;
                }

                case 'installChromium': {
                    const result = await installChromium();
                    if (result.success) {
                        console.log(JSON.stringify({
                            binary: result.binary,
                            version: result.version,
                        }));
                    } else {
                        console.error(result.error);
                        process.exit(1);
                    }
                    break;
                }

                case 'installPuppeteerCore': {
                    const [npmPrefix] = commandArgs;
                    const result = await installPuppeteerCore({ npmPrefix: npmPrefix || undefined });
                    if (result.success) {
                        console.log(JSON.stringify({ path: result.path }));
                    } else {
                        console.error(result.error);
                        process.exit(1);
                    }
                    break;
                }

                case 'launchChromium': {
                    const [outputDir, extensionPathsJson] = commandArgs;
                    const extensionPaths = extensionPathsJson ? JSON.parse(extensionPathsJson) : [];
                    const result = await launchChromium({
                        outputDir: outputDir || 'chrome',
                        extensionPaths,
                    });
                    if (result.success) {
                        console.log(JSON.stringify({
                            cdpUrl: result.cdpUrl,
                            pid: result.pid,
                            port: result.port,
                        }));
                    } else {
                        console.error(result.error);
                        process.exit(1);
                    }
                    break;
                }

                case 'killChrome': {
                    const [pidStr, outputDir] = commandArgs;
                    const pid = parseInt(pidStr, 10);
                    if (isNaN(pid)) {
                        console.error('Invalid PID');
                        process.exit(1);
                    }
                    await killChrome(pid, outputDir);
                    break;
                }

                case 'killZombieChrome': {
                    const [dataDir] = commandArgs;
                    const killed = killZombieChrome(dataDir);
                    console.log(killed);
                    break;
                }

                case 'getExtensionId': {
                    const [unpacked_path] = commandArgs;
                    const id = getExtensionId(unpacked_path);
                    console.log(id);
                    break;
                }

                case 'loadExtensionManifest': {
                    const [unpacked_path] = commandArgs;
                    const manifest = loadExtensionManifest(unpacked_path);
                    console.log(JSON.stringify(manifest));
                    break;
                }

                case 'getExtensionLaunchArgs': {
                    const [extensions_json] = commandArgs;
                    const extensions = JSON.parse(extensions_json);
                    const launchArgs = getExtensionLaunchArgs(extensions);
                    console.log(JSON.stringify(launchArgs));
                    break;
                }

                case 'loadOrInstallExtension': {
                    const [webstore_id, name, extensions_dir] = commandArgs;
                    const ext = await loadOrInstallExtension({ webstore_id, name }, extensions_dir);
                    console.log(JSON.stringify(ext, null, 2));
                    break;
                }

                case 'getMachineType': {
                    console.log(getMachineType());
                    break;
                }

                case 'getLibDir': {
                    console.log(getLibDir());
                    break;
                }

                case 'getNodeModulesDir': {
                    console.log(getNodeModulesDir());
                    break;
                }

                case 'getExtensionsDir': {
                    console.log(getExtensionsDir());
                    break;
                }

                case 'getTestEnv': {
                    console.log(JSON.stringify(getTestEnv(), null, 2));
                    break;
                }

                case 'installExtensionWithCache': {
                    const [webstore_id, name] = commandArgs;
                    if (!webstore_id || !name) {
                        console.error('Usage: installExtensionWithCache <webstore_id> <name>');
                        process.exit(1);
                    }
                    const ext = await installExtensionWithCache({ webstore_id, name });
                    if (ext) {
                        console.log(JSON.stringify(ext, null, 2));
                    } else {
                        process.exit(1);
                    }
                    break;
                }

                default:
                    console.error(`Unknown command: ${command}`);
                    process.exit(1);
            }
        } catch (error) {
            console.error(`Error: ${error.message}`);
            process.exit(1);
        }
    })();
}
