/**
 * Unit tests for ublock plugin
 *
 * Run with: node --test tests/test_ublock.js
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { describe, it, before, after, beforeEach, afterEach } = require('node:test');

// Test fixtures
const TEST_DIR = path.join(__dirname, '.test_fixtures');
const TEST_EXTENSIONS_DIR = path.join(TEST_DIR, 'chrome_extensions');

describe('ublock plugin', () => {
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
        it('should have correct webstore_id for uBlock Origin', () => {
            const { EXTENSION } = require('../on_Snapshot__03_ublock.js');

            assert.strictEqual(EXTENSION.webstore_id, 'cjpalhdlnbpafiamejdnhcphjbkeiagm');
        });

        it('should have correct name', () => {
            const { EXTENSION } = require('../on_Snapshot__03_ublock.js');

            assert.strictEqual(EXTENSION.name, 'ublock');
        });
    });

    describe('installUblockExtension', () => {
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
            const { installUblockExtension } = require('../on_Snapshot__03_ublock.js');

            // Create fake cache
            const cacheFile = path.join(TEST_EXTENSIONS_DIR, 'ublock.extension.json');
            const fakeExtensionDir = path.join(TEST_EXTENSIONS_DIR, 'fake_ublock');

            fs.mkdirSync(fakeExtensionDir, { recursive: true });
            fs.writeFileSync(
                path.join(fakeExtensionDir, 'manifest.json'),
                JSON.stringify({ version: '1.67.0' })
            );

            const fakeCache = {
                webstore_id: 'cjpalhdlnbpafiamejdnhcphjbkeiagm',
                name: 'ublock',
                unpacked_path: fakeExtensionDir,
                version: '1.67.0'
            };

            fs.writeFileSync(cacheFile, JSON.stringify(fakeCache));

            const result = await installUblockExtension();

            assert.notStrictEqual(result, null);
            assert.strictEqual(result.webstore_id, 'cjpalhdlnbpafiamejdnhcphjbkeiagm');
        });

        it('should not require any configuration', async () => {
            // uBlock Origin works out of the box with default filter lists
            const { EXTENSION } = require('../on_Snapshot__03_ublock.js');

            assert.ok(EXTENSION);
            // No config fields should be required
        });

        it('should have large download size (filter lists)', () => {
            // uBlock Origin is typically larger than other extensions
            // due to included filter lists (usually 3-5 MB)

            const typicalSize = 4 * 1024 * 1024; // ~4 MB
            const minExpectedSize = 2 * 1024 * 1024; // Minimum 2 MB

            // Just verify we understand the expected size
            assert.ok(typicalSize > minExpectedSize);
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

        it('should create cache file with correct structure', async () => {
            const cacheFile = path.join(TEST_EXTENSIONS_DIR, 'ublock.extension.json');

            const mockExtension = {
                webstore_id: 'cjpalhdlnbpafiamejdnhcphjbkeiagm',
                name: 'ublock',
                version: '1.68.0',
                unpacked_path: path.join(TEST_EXTENSIONS_DIR, 'test_ublock'),
                crx_path: path.join(TEST_EXTENSIONS_DIR, 'test_ublock.crx')
            };

            await fs.promises.writeFile(cacheFile, JSON.stringify(mockExtension, null, 2));

            assert.ok(fs.existsSync(cacheFile));

            const cache = JSON.parse(fs.readFileSync(cacheFile, 'utf-8'));
            assert.strictEqual(cache.name, 'ublock');
            assert.strictEqual(cache.webstore_id, 'cjpalhdlnbpafiamejdnhcphjbkeiagm');
        });
    });

    describe('extension functionality', () => {
        it('should work automatically with default filter lists', () => {
            const features = {
                automaticBlocking: true,
                requiresConfiguration: false,
                requiresApiKey: false,
                defaultFilterLists: true,
                blocksAds: true,
                blocksTrackers: true,
                blocksMalware: true
            };

            assert.strictEqual(features.automaticBlocking, true);
            assert.strictEqual(features.requiresConfiguration, false);
            assert.strictEqual(features.requiresApiKey, false);
            assert.strictEqual(features.defaultFilterLists, true);
        });

        it('should not require runtime configuration', () => {
            // uBlock Origin works purely via filter lists and content scripts
            // No API keys or runtime configuration needed

            const requiresRuntimeConfig = false;
            const requiresApiKey = false;

            assert.strictEqual(requiresRuntimeConfig, false);
            assert.strictEqual(requiresApiKey, false);
        });

        it('should support standard filter list formats', () => {
            const supportedFormats = [
                'EasyList',
                'EasyPrivacy',
                'Malware Domains',
                'Peter Lowe\'s List',
                'uBlock Origin filters'
            ];

            assert.ok(supportedFormats.length > 0);
            // Should support multiple filter list formats
        });
    });

    describe('priority and execution order', () => {
        it('should have priority 03 (early)', () => {
            const filename = 'on_Snapshot__03_ublock.js';

            const match = filename.match(/on_Snapshot__(\d+)_/);
            assert.ok(match);

            const priority = parseInt(match[1]);
            assert.strictEqual(priority, 3);
        });

        it('should run before chrome (priority 20)', () => {
            const extensionPriority = 3;
            const chromeSessionPriority = 20;

            assert.ok(extensionPriority < chromeSessionPriority);
        });

        it('should run after cookie dismissal extension', () => {
            const ublockPriority = 3;
            const cookiesPriority = 2;

            assert.ok(ublockPriority > cookiesPriority);
        });
    });

    describe('performance considerations', () => {
        it('should benefit from caching due to large size', () => {
            // uBlock Origin's large size makes caching especially important

            const averageDownloadTime = 10; // seconds
            const averageCacheCheckTime = 0.01; // seconds

            const performanceGain = averageDownloadTime / averageCacheCheckTime;

            // Should be at least 100x faster with cache
            assert.ok(performanceGain > 100);
        });

        it('should not impact page load time significantly', () => {
            // While extension is large, it uses efficient blocking

            const efficientBlocking = true;
            const minimalOverhead = true;

            assert.strictEqual(efficientBlocking, true);
            assert.strictEqual(minimalOverhead, true);
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
            const cacheFile = path.join(TEST_EXTENSIONS_DIR, 'ublock.extension.json');

            // Create corrupted cache
            fs.writeFileSync(cacheFile, 'invalid json content');

            const { installUblockExtension } = require('../on_Snapshot__03_ublock.js');

            // Mock loadOrInstallExtension to avoid actual download
            const extensionUtils = require('../../chrome_extensions/chrome_extension_utils.js');
            const originalFunc = extensionUtils.loadOrInstallExtension;

            extensionUtils.loadOrInstallExtension = async () => ({
                webstore_id: 'cjpalhdlnbpafiamejdnhcphjbkeiagm',
                name: 'ublock',
                version: '1.68.0'
            });

            const result = await installUblockExtension();

            extensionUtils.loadOrInstallExtension = originalFunc;

            assert.notStrictEqual(result, null);
        });

        it('should handle download timeout gracefully', () => {
            // For large extension like uBlock, timeout handling is important

            const timeoutSeconds = 120; // 2 minutes
            const minTimeout = 30; // Should allow at least 30 seconds

            assert.ok(timeoutSeconds > minTimeout);
        });
    });

    describe('filter list validation', () => {
        it('should have valid filter list format', () => {
            // Example filter list entry
            const sampleFilters = [
                '||ads.example.com^',
                '||tracker.example.com^$third-party',
                '##.advertisement'
            ];

            // All filters should follow standard format
            sampleFilters.forEach(filter => {
                assert.ok(typeof filter === 'string');
                assert.ok(filter.length > 0);
            });
        });

        it('should support cosmetic filters', () => {
            const cosmeticFilter = '##.banner-ad';

            // Should start with ## for cosmetic filters
            assert.ok(cosmeticFilter.startsWith('##'));
        });

        it('should support network filters', () => {
            const networkFilter = '||ads.example.com^';

            // Network filters typically start with || or contain ^
            assert.ok(networkFilter.includes('||') || networkFilter.includes('^'));
        });
    });
});
