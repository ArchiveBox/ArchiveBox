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
const { exec } = require('child_process');
const { promisify } = require('util');
const { Readable } = require('stream');
const { finished } = require('stream/promises');

const execAsync = promisify(exec);

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

    // Unzip CRX file to unpacked_path
    await fs.promises.mkdir(extension.unpacked_path, { recursive: true });

    try {
        // Try system unzip command first
        await execAsync(`/usr/bin/unzip -o ${extension.crx_path} -d ${extension.unpacked_path}`);
    } catch (err1) {
        if (unzip) {
            // Fallback to unzipper library
            try {
                await unzip(extension.crx_path, extension.unpacked_path);
            } catch (err2) {
                console.error(`[❌] Failed to unzip ${extension.crx_path}:`, err1.message);
                return false;
            }
        } else {
            console.error(`[❌] Failed to unzip ${extension.crx_path}:`, err1.message);
            return false;
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
 * Generate Chrome launch arguments for loading extensions.
 *
 * @param {Array} extensions - Array of extension metadata objects
 * @returns {Array<string>} - Chrome CLI arguments for loading extensions
 */
function getExtensionLaunchArgs(extensions) {
    if (!extensions || extensions.length === 0) {
        return [];
    }

    // Filter out extensions without unpacked_path first
    const validExtensions = extensions.filter(ext => ext.unpacked_path);

    const unpacked_paths = validExtensions.map(ext => ext.unpacked_path);
    const webstore_ids = validExtensions.map(ext => ext.webstore_id || ext.id);

    return [
        `--load-extension=${unpacked_paths.join(',')}`,
        `--allowlisted-extension-id=${webstore_ids.join(',')}`,
        '--allow-legacy-extension-manifests',
        '--disable-extensions-auto-update',
    ];
}

// Export all functions
module.exports = {
    getExtensionId,
    loadExtensionManifest,
    installExtension,
    loadOrInstallExtension,
    isTargetExtension,
    loadExtensionFromTarget,
    installAllExtensions,
    loadAllExtensionsFromBrowser,
    getExtensionLaunchArgs,
};

// CLI usage
if (require.main === module) {
    const args = process.argv.slice(2);

    if (args.length === 0) {
        console.log('Usage: chrome_extension_utils.js <command> [args...]');
        console.log('');
        console.log('Commands:');
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
                    const args = getExtensionLaunchArgs(extensions);
                    console.log(JSON.stringify(args));
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
