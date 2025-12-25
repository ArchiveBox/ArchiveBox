/**
 * Unit tests for chrome_extension_utils.js
 *
 * Run with: npm test
 * Or: node --test tests/test_chrome_extension_utils.js
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { describe, it, before, after, beforeEach, afterEach } = require('node:test');

// Import module under test
const extensionUtils = require('../chrome_extension_utils.js');

// Test fixtures
const TEST_DIR = path.join(__dirname, '.test_fixtures');
const TEST_EXTENSIONS_DIR = path.join(TEST_DIR, 'chrome_extensions');

describe('chrome_extension_utils', () => {
    before(() => {
        // Create test directory
        if (!fs.existsSync(TEST_DIR)) {
            fs.mkdirSync(TEST_DIR, { recursive: true });
        }
    });

    after(() => {
        // Cleanup test directory
        if (fs.existsSync(TEST_DIR)) {
            fs.rmSync(TEST_DIR, { recursive: true, force: true });
        }
    });

    describe('getExtensionId', () => {
        it('should compute extension ID from path', () => {
            const testPath = '/path/to/extension';
            const extensionId = extensionUtils.getExtensionId(testPath);

            assert.strictEqual(typeof extensionId, 'string');
            assert.strictEqual(extensionId.length, 32);
            // Should only contain lowercase letters a-p
            assert.match(extensionId, /^[a-p]+$/);
        });

        it('should compute ID even for non-existent paths', () => {
            const testPath = '/nonexistent/path';
            const extensionId = extensionUtils.getExtensionId(testPath);

            // Should still compute an ID from the path string
            assert.strictEqual(typeof extensionId, 'string');
            assert.strictEqual(extensionId.length, 32);
            assert.match(extensionId, /^[a-p]+$/);
        });

        it('should return consistent ID for same path', () => {
            const testPath = '/path/to/extension';
            const id1 = extensionUtils.getExtensionId(testPath);
            const id2 = extensionUtils.getExtensionId(testPath);

            assert.strictEqual(id1, id2);
        });

        it('should return different IDs for different paths', () => {
            const path1 = '/path/to/extension1';
            const path2 = '/path/to/extension2';
            const id1 = extensionUtils.getExtensionId(path1);
            const id2 = extensionUtils.getExtensionId(path2);

            assert.notStrictEqual(id1, id2);
        });
    });

    describe('loadExtensionManifest', () => {
        beforeEach(() => {
            // Create test extension directory with manifest
            const testExtDir = path.join(TEST_DIR, 'test_extension');
            fs.mkdirSync(testExtDir, { recursive: true });

            const manifest = {
                manifest_version: 3,
                name: "Test Extension",
                version: "1.0.0"
            };

            fs.writeFileSync(
                path.join(testExtDir, 'manifest.json'),
                JSON.stringify(manifest)
            );
        });

        afterEach(() => {
            // Cleanup test extension
            const testExtDir = path.join(TEST_DIR, 'test_extension');
            if (fs.existsSync(testExtDir)) {
                fs.rmSync(testExtDir, { recursive: true });
            }
        });

        it('should load valid manifest.json', () => {
            const testExtDir = path.join(TEST_DIR, 'test_extension');
            const manifest = extensionUtils.loadExtensionManifest(testExtDir);

            assert.notStrictEqual(manifest, null);
            assert.strictEqual(manifest.manifest_version, 3);
            assert.strictEqual(manifest.name, "Test Extension");
            assert.strictEqual(manifest.version, "1.0.0");
        });

        it('should return null for missing manifest', () => {
            const nonExistentDir = path.join(TEST_DIR, 'nonexistent');
            const manifest = extensionUtils.loadExtensionManifest(nonExistentDir);

            assert.strictEqual(manifest, null);
        });

        it('should handle invalid JSON gracefully', () => {
            const testExtDir = path.join(TEST_DIR, 'invalid_extension');
            fs.mkdirSync(testExtDir, { recursive: true });

            // Write invalid JSON
            fs.writeFileSync(
                path.join(testExtDir, 'manifest.json'),
                'invalid json content'
            );

            const manifest = extensionUtils.loadExtensionManifest(testExtDir);

            assert.strictEqual(manifest, null);

            // Cleanup
            fs.rmSync(testExtDir, { recursive: true });
        });
    });

    describe('getExtensionLaunchArgs', () => {
        it('should return empty array for no extensions', () => {
            const args = extensionUtils.getExtensionLaunchArgs([]);

            assert.deepStrictEqual(args, []);
        });

        it('should generate correct launch args for single extension', () => {
            const extensions = [{
                webstore_id: 'abcd1234',
                unpacked_path: '/path/to/extension'
            }];

            const args = extensionUtils.getExtensionLaunchArgs(extensions);

            assert.strictEqual(args.length, 4);
            assert.strictEqual(args[0], '--load-extension=/path/to/extension');
            assert.strictEqual(args[1], '--allowlisted-extension-id=abcd1234');
            assert.strictEqual(args[2], '--allow-legacy-extension-manifests');
            assert.strictEqual(args[3], '--disable-extensions-auto-update');
        });

        it('should generate correct launch args for multiple extensions', () => {
            const extensions = [
                { webstore_id: 'ext1', unpacked_path: '/path/ext1' },
                { webstore_id: 'ext2', unpacked_path: '/path/ext2' },
                { webstore_id: 'ext3', unpacked_path: '/path/ext3' }
            ];

            const args = extensionUtils.getExtensionLaunchArgs(extensions);

            assert.strictEqual(args.length, 4);
            assert.strictEqual(args[0], '--load-extension=/path/ext1,/path/ext2,/path/ext3');
            assert.strictEqual(args[1], '--allowlisted-extension-id=ext1,ext2,ext3');
        });

        it('should handle extensions with id instead of webstore_id', () => {
            const extensions = [{
                id: 'computed_id',
                unpacked_path: '/path/to/extension'
            }];

            const args = extensionUtils.getExtensionLaunchArgs(extensions);

            assert.strictEqual(args[1], '--allowlisted-extension-id=computed_id');
        });

        it('should filter out extensions without paths', () => {
            const extensions = [
                { webstore_id: 'ext1', unpacked_path: '/path/ext1' },
                { webstore_id: 'ext2', unpacked_path: null },
                { webstore_id: 'ext3', unpacked_path: '/path/ext3' }
            ];

            const args = extensionUtils.getExtensionLaunchArgs(extensions);

            assert.strictEqual(args[0], '--load-extension=/path/ext1,/path/ext3');
            assert.strictEqual(args[1], '--allowlisted-extension-id=ext1,ext3');
        });
    });

    describe('loadOrInstallExtension', () => {
        beforeEach(() => {
            // Create test extensions directory
            if (!fs.existsSync(TEST_EXTENSIONS_DIR)) {
                fs.mkdirSync(TEST_EXTENSIONS_DIR, { recursive: true });
            }
        });

        afterEach(() => {
            // Cleanup test extensions directory
            if (fs.existsSync(TEST_EXTENSIONS_DIR)) {
                fs.rmSync(TEST_EXTENSIONS_DIR, { recursive: true });
            }
        });

        it('should throw error if neither webstore_id nor unpacked_path provided', async () => {
            await assert.rejects(
                async () => {
                    await extensionUtils.loadOrInstallExtension({}, TEST_EXTENSIONS_DIR);
                },
                /Extension must have either/
            );
        });

        it('should set correct default values for extension metadata', async () => {
            const input = {
                webstore_id: 'test123',
                name: 'test_extension'
            };

            // Mock the installation to avoid actual download
            const originalInstall = extensionUtils.installExtension;
            extensionUtils.installExtension = async () => {
                // Create fake manifest
                const extDir = path.join(TEST_EXTENSIONS_DIR, 'test123__test_extension');
                fs.mkdirSync(extDir, { recursive: true });
                fs.writeFileSync(
                    path.join(extDir, 'manifest.json'),
                    JSON.stringify({ version: '1.0.0' })
                );
                return true;
            };

            const ext = await extensionUtils.loadOrInstallExtension(input, TEST_EXTENSIONS_DIR);

            // Restore original
            extensionUtils.installExtension = originalInstall;

            assert.strictEqual(ext.webstore_id, 'test123');
            assert.strictEqual(ext.name, 'test_extension');
            assert.ok(ext.webstore_url.includes(ext.webstore_id));
            assert.ok(ext.crx_url.includes(ext.webstore_id));
            assert.ok(ext.crx_path.includes('test123__test_extension.crx'));
            assert.ok(ext.unpacked_path.includes('test123__test_extension'));
        });

        it('should detect version from manifest after installation', async () => {
            const input = {
                webstore_id: 'test456',
                name: 'versioned_extension'
            };

            // Create pre-installed extension
            const extDir = path.join(TEST_EXTENSIONS_DIR, 'test456__versioned_extension');
            fs.mkdirSync(extDir, { recursive: true });
            fs.writeFileSync(
                path.join(extDir, 'manifest.json'),
                JSON.stringify({
                    manifest_version: 3,
                    name: "Versioned Extension",
                    version: "2.5.1"
                })
            );

            const ext = await extensionUtils.loadOrInstallExtension(input, TEST_EXTENSIONS_DIR);

            assert.strictEqual(ext.version, '2.5.1');
        });
    });

    describe('isTargetExtension', () => {
        it('should identify extension targets by URL', async () => {
            // Mock Puppeteer target
            const mockTarget = {
                type: () => 'service_worker',
                url: () => 'chrome-extension://abcdefgh/background.js',
                worker: async () => null,
                page: async () => null
            };

            const result = await extensionUtils.isTargetExtension(mockTarget);

            assert.strictEqual(result.target_is_extension, true);
            assert.strictEqual(result.target_is_bg, true);
            assert.strictEqual(result.extension_id, 'abcdefgh');
        });

        it('should not identify non-extension targets', async () => {
            const mockTarget = {
                type: () => 'page',
                url: () => 'https://example.com',
                worker: async () => null,
                page: async () => null
            };

            const result = await extensionUtils.isTargetExtension(mockTarget);

            assert.strictEqual(result.target_is_extension, false);
            assert.strictEqual(result.target_is_bg, false);
            assert.strictEqual(result.extension_id, null);
        });

        it('should handle closed targets gracefully', async () => {
            const mockTarget = {
                type: () => { throw new Error('No target with given id found'); },
                url: () => { throw new Error('No target with given id found'); },
                worker: async () => { throw new Error('No target with given id found'); },
                page: async () => { throw new Error('No target with given id found'); }
            };

            const result = await extensionUtils.isTargetExtension(mockTarget);

            assert.strictEqual(result.target_type, 'closed');
            assert.strictEqual(result.target_url, 'about:closed');
        });
    });
});

// Run tests if executed directly
if (require.main === module) {
    console.log('Run tests with: npm test');
    console.log('Or: node --test tests/test_chrome_extension_utils.js');
}
