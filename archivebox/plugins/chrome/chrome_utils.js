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
 * Scans DATA_DIR/crawls/<crawl_id>/chrome/<name>.pid for stale processes.
 * @param {string} [dataDir] - Data directory (defaults to DATA_DIR env or '.')
 * @returns {number} - Number of zombies killed
 */
function killZombieChrome(dataDir = null) {
    dataDir = dataDir || getEnv('DATA_DIR', '.');
    const crawlsDir = path.join(dataDir, 'crawls');
    const now = Date.now();
    const fiveMinutesAgo = now - 300000;
    let killed = 0;

    console.error('[*] Checking for zombie Chrome processes...');

    if (!fs.existsSync(crawlsDir)) {
        console.error('[+] No crawls directory found');
        return 0;
    }

    try {
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
                    continue;
                }
            } catch (e) {
                continue;
            }

            // Crawl is stale, check for PIDs
            try {
                const pidFiles = fs.readdirSync(chromeDir).filter(f => f.endsWith('.pid'));

                for (const pidFileName of pidFiles) {
                    const pidFile = path.join(chromeDir, pidFileName);

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
                        console.error(`[!] Found zombie (PID ${pid}) from stale crawl ${crawl.name}`);

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
 * @param {string} [options.resolution='1440,2000'] - Window resolution
 * @param {boolean} [options.headless=true] - Run in headless mode
 * @param {boolean} [options.checkSsl=true] - Check SSL certificates
 * @param {string[]} [options.extensionPaths=[]] - Paths to unpacked extensions
 * @param {boolean} [options.killZombies=true] - Kill zombie processes first
 * @returns {Promise<Object>} - {success, cdpUrl, pid, port, process, error}
 */
async function launchChromium(options = {}) {
    const {
        binary = findChromium(),
        outputDir = 'chrome',
        resolution = getEnv('CHROME_RESOLUTION') || getEnv('RESOLUTION', '1440,2000'),
        headless = getEnvBool('CHROME_HEADLESS', true),
        checkSsl = getEnvBool('CHROME_CHECK_SSL_VALIDITY', getEnvBool('CHECK_SSL_VALIDITY', true)),
        extensionPaths = [],
        killZombies = true,
    } = options;

    if (!binary) {
        return { success: false, error: 'Chrome binary not found' };
    }

    // Kill zombies first
    if (killZombies) {
        killZombieChrome();
    }

    const { width, height } = parseResolution(resolution);

    // Create output directory
    if (!fs.existsSync(outputDir)) {
        fs.mkdirSync(outputDir, { recursive: true });
    }

    // Find a free port
    const debugPort = await findFreePort();
    console.error(`[*] Using debug port: ${debugPort}`);

    // Build Chrome arguments
    const chromiumArgs = [
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
        ...(headless ? ['--headless=new'] : []),
        ...(checkSsl ? [] : ['--ignore-certificate-errors']),
    ];

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
 * Kill a Chrome process by PID.
 * @param {number} pid - Process ID to kill
 * @param {string} [outputDir] - Directory containing PID files to clean up
 */
async function killChrome(pid, outputDir = null) {
    if (!pid) return;

    console.error(`[*] Killing Chrome process tree (PID ${pid})...`);

    // Try to kill process group first
    try {
        process.kill(-pid, 'SIGTERM');
    } catch (e) {
        try { process.kill(pid, 'SIGTERM'); } catch (e2) {}
    }

    // Wait for graceful shutdown
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Force kill
    try {
        process.kill(-pid, 'SIGKILL');
    } catch (e) {
        try { process.kill(pid, 'SIGKILL'); } catch (e2) {}
    }

    // Clean up PID files
    if (outputDir) {
        try { fs.unlinkSync(path.join(outputDir, 'chrome.pid')); } catch (e) {}
        try { fs.unlinkSync(path.join(outputDir, 'hook.pid')); } catch (e) {}
    }

    console.error('[*] Chrome process killed');
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
    // Chrome uses a SHA256 hash of the unpacked extension directory path
    const hash = crypto.createHash('sha256');
    hash.update(Buffer.from(unpacked_path, 'utf-8'));

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
    const EXTENSIONS_DIR = extensions_dir || process.env.CHROME_EXTENSIONS_DIR || './data/chrome_extensions';

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
    const target_is_extension = is_chrome_extension || target_is_bg;

    if (target_is_extension) {
        try {
            extension_id = target_url?.split('://')[1]?.split('/')[0] || null;

            if (target_ctx) {
                const manifest = await target_ctx.evaluate(() => chrome.runtime.getManifest());
                manifest_version = manifest?.manifest_version || null;
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
            return await target_ctx.evaluate((tabId) => {
                return new Promise((resolve) => {
                    chrome.action.onClicked.addListener((tab) => {
                        resolve({ success: true, tab });
                    });
                    chrome.action.openPopup();
                });
            }, tab?.id || null);
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
 * Find Chromium/Chrome binary path.
 * Prefers Chromium over Chrome because Chrome 137+ removed --load-extension support.
 *
 * @param {string} [dataDir] - Data directory to check for puppeteer installs
 * @returns {string|null} - Absolute path to browser binary or null if not found
 */
function findChromium(dataDir = null) {
    // Check CHROME_BINARY env var first
    const chromeBinary = (process.env.CHROME_BINARY || '').trim();
    if (chromeBinary && fs.existsSync(chromeBinary)) {
        // Ensure absolute path
        return path.resolve(chromeBinary);
    }

    // Helper to find Chromium in @puppeteer/browsers directory structure
    // Always returns absolute paths
    const findInPuppeteerDir = (baseDir) => {
        const absBaseDir = path.resolve(baseDir);
        if (!fs.existsSync(absBaseDir)) return null;
        try {
            const versions = fs.readdirSync(absBaseDir);
            for (const version of versions.sort().reverse()) {
                const versionDir = path.join(absBaseDir, version);
                // Check for macOS ARM structure
                const macArmBinary = path.join(versionDir, 'chrome-mac/Chromium.app/Contents/MacOS/Chromium');
                if (fs.existsSync(macArmBinary)) return macArmBinary;
                // Check for macOS x64 structure
                const macX64Binary = path.join(versionDir, 'chrome-mac-x64/Chromium.app/Contents/MacOS/Chromium');
                if (fs.existsSync(macX64Binary)) return macX64Binary;
                // Check for Linux structure
                const linuxBinary = path.join(versionDir, 'chrome-linux/chrome');
                if (fs.existsSync(linuxBinary)) return linuxBinary;
            }
        } catch (e) {
            // Continue
        }
        return null;
    };

    // Check @puppeteer/browsers install locations
    const puppeteerDirs = [
        // Local project install (from npx @puppeteer/browsers install)
        path.join(dataDir || process.env.DATA_DIR || '.', 'chromium'),
        path.join(process.cwd(), 'chromium'),
        // User cache locations
        path.join(process.env.HOME || '', '.cache/puppeteer/chromium'),
    ];

    for (const puppeteerDir of puppeteerDirs) {
        const binary = findInPuppeteerDir(puppeteerDir);
        if (binary) return binary;
    }

    // Check standard system locations
    const candidates = [
        // Linux Chromium
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        // macOS Chromium (Homebrew or manual install)
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        // Fallback to Chrome (extension loading may not work in Chrome 137+)
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    ];

    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) {
            // Warn if falling back to Chrome
            if (candidate.includes('google-chrome') || candidate.includes('Google Chrome')) {
                console.error('[!] Warning: Using Chrome instead of Chromium. Extension loading may not work in Chrome 137+');
            }
            return candidate;
        }
    }

    return null;
}

// Export all functions
module.exports = {
    // Environment helpers
    getEnv,
    getEnvBool,
    getEnvInt,
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
    // Chrome/Chromium binary finding
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
    // Deprecated - use enableExtensions option instead
    getExtensionLaunchArgs,
};

// CLI usage
if (require.main === module) {
    const args = process.argv.slice(2);

    if (args.length === 0) {
        console.log('Usage: chrome_utils.js <command> [args...]');
        console.log('');
        console.log('Commands:');
        console.log('  findChromium [data_dir]');
        console.log('  launchChromium [output_dir] [extension_paths_json]');
        console.log('  killChrome <pid> [output_dir]');
        console.log('  killZombieChrome [data_dir]');
        console.log('  getExtensionId <path>');
        console.log('  loadExtensionManifest <path>');
        console.log('  getExtensionLaunchArgs <extensions_json>');
        console.log('  loadOrInstallExtension <webstore_id> <name> [extensions_dir]');
        process.exit(1);
    }

    const [command, ...commandArgs] = args;

    (async () => {
        try {
            switch (command) {
                case 'findChromium': {
                    const [dataDir] = commandArgs;
                    const binary = findChromium(dataDir);
                    if (binary) {
                        console.log(binary);
                    } else {
                        console.error('Chromium binary not found');
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
