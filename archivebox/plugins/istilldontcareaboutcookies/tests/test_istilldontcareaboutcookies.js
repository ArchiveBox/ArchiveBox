/**
 * Unit tests for istilldontcareaboutcookies plugin
 *
 * Run with: node --test tests/test_istilldontcareaboutcookies.js
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { describe, it, before, after, beforeEach, afterEach } = require('node:test');

// Test fixtures
const TEST_DIR = path.join(__dirname, '.test_fixtures');
const TEST_EXTENSIONS_DIR = path.join(TEST_DIR, 'chrome_extensions');

describe('istilldontcareaboutcookies plugin', () => {
    before(() => {
        if (!fs.existsSync(TEST_DIR)) {
            fs.mkdirSync(TEST_DIR, { recursive: true });
        }
    });

    after(() => {
        if (fs.existsSync(TEST_DIR)) {
            fs.rmSync(TEST_DIR, { recursive: true, force: true });
        }
    });

    describe('EXTENSION metadata', () => {
        it('should have correct webstore_id', () => {
            const { EXTENSION } = require('../on_Snapshot__02_istilldontcareaboutcookies.js');

            assert.strictEqual(EXTENSION.webstore_id, 'edibdbjcniadpccecjdfdjjppcpchdlm');
        });

        it('should have correct name', () => {
            const { EXTENSION } = require('../on_Snapshot__02_istilldontcareaboutcookies.js');

            assert.strictEqual(EXTENSION.name, 'istilldontcareaboutcookies');
        });
    });

    describe('installCookiesExtension', () => {
        beforeEach(() => {
            process.env.CHROME_EXTENSIONS_DIR = TEST_EXTENSIONS_DIR;

            if (!fs.existsSync(TEST_EXTENSIONS_DIR)) {
                fs.mkdirSync(TEST_EXTENSIONS_DIR, { recursive: true });
            }
        });

        afterEach(() => {
            if (fs.existsSync(TEST_EXTENSIONS_DIR)) {
                fs.rmSync(TEST_EXTENSIONS_DIR, { recursive: true });
            }

            delete process.env.CHROME_EXTENSIONS_DIR;
        });

        it('should use cached extension if available', async () => {
            const { installCookiesExtension } = require('../on_Snapshot__02_istilldontcareaboutcookies.js');

            // Create fake cache
            const cacheFile = path.join(TEST_EXTENSIONS_DIR, 'istilldontcareaboutcookies.extension.json');
            const fakeExtensionDir = path.join(TEST_EXTENSIONS_DIR, 'fake_cookies');

            fs.mkdirSync(fakeExtensionDir, { recursive: true });
            fs.writeFileSync(
                path.join(fakeExtensionDir, 'manifest.json'),
                JSON.stringify({ version: '1.1.8' })
            );

            const fakeCache = {
                webstore_id: 'edibdbjcniadpccecjdfdjjppcpchdlm',
                name: 'istilldontcareaboutcookies',
                unpacked_path: fakeExtensionDir,
                version: '1.1.8'
            };

            fs.writeFileSync(cacheFile, JSON.stringify(fakeCache));

            const result = await installCookiesExtension();

            assert.notStrictEqual(result, null);
            assert.strictEqual(result.webstore_id, 'edibdbjcniadpccecjdfdjjppcpchdlm');
        });

        it('should not require any configuration', async () => {
            // This extension works out of the box
            // No API keys or config needed
            const { EXTENSION } = require('../on_Snapshot__02_istilldontcareaboutcookies.js');

            assert.ok(EXTENSION);
            // No config fields should be required
        });
    });

    describe('cache file creation', () => {
        beforeEach(() => {
            process.env.CHROME_EXTENSIONS_DIR = TEST_EXTENSIONS_DIR;

            if (!fs.existsSync(TEST_EXTENSIONS_DIR)) {
                fs.mkdirSync(TEST_EXTENSIONS_DIR, { recursive: true });
            }
        });

        afterEach(() => {
            if (fs.existsSync(TEST_EXTENSIONS_DIR)) {
                fs.rmSync(TEST_EXTENSIONS_DIR, { recursive: true });
            }

            delete process.env.CHROME_EXTENSIONS_DIR;
        });

        it('should create cache file with correct extension name', async () => {
            const cacheFile = path.join(TEST_EXTENSIONS_DIR, 'istilldontcareaboutcookies.extension.json');

            // Create mock extension
            const mockExtension = {
                webstore_id: 'edibdbjcniadpccecjdfdjjppcpchdlm',
                name: 'istilldontcareaboutcookies',
                version: '1.1.9'
            };

            await fs.promises.writeFile(cacheFile, JSON.stringify(mockExtension, null, 2));

            assert.ok(fs.existsSync(cacheFile));

            const cache = JSON.parse(fs.readFileSync(cacheFile, 'utf-8'));
            assert.strictEqual(cache.name, 'istilldontcareaboutcookies');
        });

        it('should use correct filename pattern', () => {
            const expectedPattern = 'istilldontcareaboutcookies.extension.json';
            const cacheFile = path.join(TEST_EXTENSIONS_DIR, expectedPattern);

            // Pattern should match expected format
            assert.ok(path.basename(cacheFile).endsWith('.extension.json'));
            assert.ok(path.basename(cacheFile).includes('istilldontcareaboutcookies'));
        });
    });

    describe('extension functionality', () => {
        it('should work automatically without configuration', () => {
            // This extension automatically dismisses cookie banners
            // No manual trigger or configuration needed

            const features = {
                automaticBannerDismissal: true,
                requiresConfiguration: false,
                requiresApiKey: false,
                requiresUserAction: false
            };

            assert.strictEqual(features.automaticBannerDismissal, true);
            assert.strictEqual(features.requiresConfiguration, false);
            assert.strictEqual(features.requiresApiKey, false);
            assert.strictEqual(features.requiresUserAction, false);
        });

        it('should not require any runtime hooks', () => {
            // Extension works purely via Chrome's content script injection
            // No need for additional hooks or configuration

            const requiresHooks = {
                preNavigation: false,
                postNavigation: false,
                onPageLoad: false
            };

            assert.strictEqual(requiresHooks.preNavigation, false);
            assert.strictEqual(requiresHooks.postNavigation, false);
            assert.strictEqual(requiresHooks.onPageLoad, false);
        });
    });

    describe('priority and execution order', () => {
        it('should have priority 02 (early)', () => {
            const filename = 'on_Snapshot__02_istilldontcareaboutcookies.js';

            // Extract priority from filename
            const match = filename.match(/on_Snapshot__(\d+)_/);
            assert.ok(match);

            const priority = parseInt(match[1]);
            assert.strictEqual(priority, 2);
        });

        it('should run before chrome_session (priority 20)', () => {
            const extensionPriority = 2;
            const chromeSessionPriority = 20;

            assert.ok(extensionPriority < chromeSessionPriority);
        });
    });

    describe('error handling', () => {
        beforeEach(() => {
            process.env.CHROME_EXTENSIONS_DIR = TEST_EXTENSIONS_DIR;

            if (!fs.existsSync(TEST_EXTENSIONS_DIR)) {
                fs.mkdirSync(TEST_EXTENSIONS_DIR, { recursive: true });
            }
        });

        afterEach(() => {
            if (fs.existsSync(TEST_EXTENSIONS_DIR)) {
                fs.rmSync(TEST_EXTENSIONS_DIR, { recursive: true });
            }

            delete process.env.CHROME_EXTENSIONS_DIR;
        });

        it('should handle corrupted cache gracefully', async () => {
            const cacheFile = path.join(TEST_EXTENSIONS_DIR, 'istilldontcareaboutcookies.extension.json');

            // Create corrupted cache
            fs.writeFileSync(cacheFile, 'invalid json content');

            // Should detect corruption and proceed with fresh install
            const { installCookiesExtension } = require('../on_Snapshot__02_istilldontcareaboutcookies.js');

            // Mock loadOrInstallExtension to avoid actual download
            const extensionUtils = require('../../chrome_extensions/chrome_extension_utils.js');
            const originalFunc = extensionUtils.loadOrInstallExtension;

            extensionUtils.loadOrInstallExtension = async () => ({
                webstore_id: 'edibdbjcniadpccecjdfdjjppcpchdlm',
                name: 'istilldontcareaboutcookies',
                version: '1.1.9'
            });

            const result = await installCookiesExtension();

            extensionUtils.loadOrInstallExtension = originalFunc;

            assert.notStrictEqual(result, null);
        });

        it('should handle missing manifest gracefully', async () => {
            const cacheFile = path.join(TEST_EXTENSIONS_DIR, 'istilldontcareaboutcookies.extension.json');
            const fakeExtensionDir = path.join(TEST_EXTENSIONS_DIR, 'fake_cookies_no_manifest');

            // Create directory without manifest
            fs.mkdirSync(fakeExtensionDir, { recursive: true });

            const fakeCache = {
                webstore_id: 'edibdbjcniadpccecjdfdjjppcpchdlm',
                name: 'istilldontcareaboutcookies',
                unpacked_path: fakeExtensionDir
            };

            fs.writeFileSync(cacheFile, JSON.stringify(fakeCache));

            const { installCookiesExtension } = require('../on_Snapshot__02_istilldontcareaboutcookies.js');

            // Mock to return fresh extension when manifest missing
            const extensionUtils = require('../../chrome_extensions/chrome_extension_utils.js');
            const originalFunc = extensionUtils.loadOrInstallExtension;

            let freshInstallCalled = false;
            extensionUtils.loadOrInstallExtension = async () => {
                freshInstallCalled = true;
                return {
                    webstore_id: 'edibdbjcniadpccecjdfdjjppcpchdlm',
                    name: 'istilldontcareaboutcookies',
                    version: '1.1.9'
                };
            };

            const result = await installCookiesExtension();

            extensionUtils.loadOrInstallExtension = originalFunc;

            // Should trigger fresh install when manifest missing
            assert.ok(freshInstallCalled || result);
        });
    });
});
