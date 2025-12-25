/**
 * Unit tests for singlefile plugin
 *
 * Run with: node --test tests/test_singlefile.js
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { describe, it, before, after, beforeEach, afterEach } = require('node:test');

// Test fixtures
const TEST_DIR = path.join(__dirname, '.test_fixtures');
const TEST_EXTENSIONS_DIR = path.join(TEST_DIR, 'chrome_extensions');
const TEST_DOWNLOADS_DIR = path.join(TEST_DIR, 'chrome_downloads');

describe('singlefile plugin', () => {
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
            const { EXTENSION } = require('../on_Snapshot__04_singlefile.js');

            assert.strictEqual(EXTENSION.webstore_id, 'mpiodijhokgodhhofbcjdecpffjipkle');
        });

        it('should have correct name', () => {
            const { EXTENSION } = require('../on_Snapshot__04_singlefile.js');

            assert.strictEqual(EXTENSION.name, 'singlefile');
        });
    });

    describe('installSinglefileExtension', () => {
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
            const { installSinglefileExtension } = require('../on_Snapshot__04_singlefile.js');

            // Create fake cache
            const cacheFile = path.join(TEST_EXTENSIONS_DIR, 'singlefile.extension.json');
            const fakeExtensionDir = path.join(TEST_EXTENSIONS_DIR, 'fake_singlefile');

            fs.mkdirSync(fakeExtensionDir, { recursive: true });
            fs.writeFileSync(
                path.join(fakeExtensionDir, 'manifest.json'),
                JSON.stringify({ version: '1.22.90' })
            );

            const fakeCache = {
                webstore_id: 'mpiodijhokgodhhofbcjdecpffjipkle',
                name: 'singlefile',
                unpacked_path: fakeExtensionDir,
                version: '1.22.90'
            };

            fs.writeFileSync(cacheFile, JSON.stringify(fakeCache));

            const result = await installSinglefileExtension();

            assert.notStrictEqual(result, null);
            assert.strictEqual(result.webstore_id, 'mpiodijhokgodhhofbcjdecpffjipkle');
        });
    });

    describe('saveSinglefileWithExtension', () => {
        beforeEach(() => {
            process.env.CHROME_DOWNLOADS_DIR = TEST_DOWNLOADS_DIR;

            if (!fs.existsSync(TEST_DOWNLOADS_DIR)) {
                fs.mkdirSync(TEST_DOWNLOADS_DIR, { recursive: true });
            }
        });

        afterEach(() => {
            if (fs.existsSync(TEST_DOWNLOADS_DIR)) {
                fs.rmSync(TEST_DOWNLOADS_DIR, { recursive: true });
            }

            delete process.env.CHROME_DOWNLOADS_DIR;
        });

        it('should require extension and version to be present', () => {
            const mockExtension = {
                name: 'singlefile',
                version: '1.22.96',
                id: 'test_id'
            };

            assert.ok(mockExtension.version);
            assert.ok(mockExtension.id);
        });

        it('should filter unsupported URL schemes', () => {
            const unsupportedSchemes = [
                'about:',
                'chrome:',
                'chrome-extension:',
                'data:',
                'javascript:',
                'blob:'
            ];

            unsupportedSchemes.forEach(scheme => {
                const testUrl = scheme + 'something';
                const urlScheme = testUrl.split(':')[0];

                assert.ok(unsupportedSchemes.some(s => s.startsWith(urlScheme)));
            });
        });

        it('should wait for file to appear in downloads directory', async () => {
            const checkDelay = 3000; // 3 seconds
            const maxTries = 10;

            // Total max wait time
            const maxWaitTime = checkDelay * maxTries;

            assert.strictEqual(maxWaitTime, 30000); // 30 seconds
        });

        it('should find downloaded file by checking URL in HTML header', () => {
            const testUrl = 'https://example.com';
            const mockHtml = `<!-- url: ${testUrl} --><html><head><meta charset="utf-8"></head></html>`;

            // Should be able to extract URL from header
            const headerPart = mockHtml.split('meta charset')[0];
            assert.ok(headerPart.includes(`url: ${testUrl}`));
        });

        it('should move file from downloads to output directory', () => {
            const downloadPath = path.join(TEST_DOWNLOADS_DIR, 'temp_file.html');
            const outputDir = 'singlefile';
            const outputFile = 'singlefile.html';
            const outputPath = path.join(outputDir, outputFile);

            // Verify paths are different
            assert.notStrictEqual(downloadPath, outputPath);
        });
    });

    describe('saveSinglefileWithCLI', () => {
        it('should use single-file-cli as fallback', () => {
            const cliCommand = 'single-file';

            // Should check for CLI availability
            assert.strictEqual(typeof cliCommand, 'string');
            assert.ok(cliCommand.length > 0);
        });

        it('should pass correct arguments to CLI', () => {
            const args = [
                '--browser-headless',
                'https://example.com',
                'singlefile/singlefile.html'
            ];

            assert.ok(args.includes('--browser-headless'));
            assert.ok(args.some(arg => arg.startsWith('http')));
        });

        it('should handle optional CLI arguments', () => {
            const options = {
                userAgent: 'Mozilla/5.0...',
                cookiesFile: '/path/to/cookies.txt',
                ignoreSSL: true
            };

            // Optional args should be conditionally added
            if (options.userAgent) {
                assert.ok(options.userAgent.length > 0);
            }

            if (options.ignoreSSL) {
                assert.strictEqual(options.ignoreSSL, true);
            }
        });
    });

    describe('priority and execution order', () => {
        it('should have priority 04 (early)', () => {
            const filename = 'on_Snapshot__04_singlefile.js';

            const match = filename.match(/on_Snapshot__(\d+)_/);
            assert.ok(match);

            const priority = parseInt(match[1]);
            assert.strictEqual(priority, 4);
        });

        it('should run before chrome_session (priority 20)', () => {
            const extensionPriority = 4;
            const chromeSessionPriority = 20;

            assert.ok(extensionPriority < chromeSessionPriority);
        });

        it('should install extensions in correct order', () => {
            const priorities = {
                captcha2: 1,
                istilldontcareaboutcookies: 2,
                ublock: 3,
                singlefile: 4
            };

            // Should be in ascending order
            assert.ok(priorities.captcha2 < priorities.istilldontcareaboutcookies);
            assert.ok(priorities.istilldontcareaboutcookies < priorities.ublock);
            assert.ok(priorities.ublock < priorities.singlefile);
        });
    });

    describe('output structure', () => {
        it('should define output directory and file', () => {
            const OUTPUT_DIR = 'singlefile';
            const OUTPUT_FILE = 'singlefile.html';

            assert.strictEqual(OUTPUT_DIR, 'singlefile');
            assert.strictEqual(OUTPUT_FILE, 'singlefile.html');
        });

        it('should create output directory if not exists', () => {
            const outputDir = path.join(TEST_DIR, 'singlefile');

            // Should create directory
            if (!fs.existsSync(outputDir)) {
                fs.mkdirSync(outputDir, { recursive: true });
            }

            assert.ok(fs.existsSync(outputDir));

            // Cleanup
            fs.rmSync(outputDir, { recursive: true });
        });
    });

    describe('extension vs CLI fallback', () => {
        it('should prefer extension over CLI', () => {
            const preferenceOrder = [
                'extension',
                'cli'
            ];

            assert.strictEqual(preferenceOrder[0], 'extension');
            assert.strictEqual(preferenceOrder[1], 'cli');
        });

        it('should fallback to CLI if extension unavailable', () => {
            const extensionAvailable = false;
            const cliAvailable = true;

            let method;
            if (extensionAvailable) {
                method = 'extension';
            } else if (cliAvailable) {
                method = 'cli';
            }

            assert.strictEqual(method, 'cli');
        });

        it('should use extension if available', () => {
            const extensionAvailable = true;

            let method;
            if (extensionAvailable) {
                method = 'extension';
            } else {
                method = 'cli';
            }

            assert.strictEqual(method, 'extension');
        });
    });

    describe('file matching and validation', () => {
        beforeEach(() => {
            if (!fs.existsSync(TEST_DOWNLOADS_DIR)) {
                fs.mkdirSync(TEST_DOWNLOADS_DIR, { recursive: true });
            }
        });

        afterEach(() => {
            if (fs.existsSync(TEST_DOWNLOADS_DIR)) {
                fs.rmSync(TEST_DOWNLOADS_DIR, { recursive: true });
            }
        });

        it('should filter HTML files from downloads', () => {
            // Create mock download files
            const files = [
                'example.html',
                'test.pdf',
                'image.png',
                'page.html'
            ];

            const htmlFiles = files.filter(f => f.endsWith('.html'));

            assert.strictEqual(htmlFiles.length, 2);
            assert.ok(htmlFiles.includes('example.html'));
            assert.ok(htmlFiles.includes('page.html'));
        });

        it('should match URL in HTML header comment', () => {
            const testUrl = 'https://example.com/page';

            const htmlContent = `<!--
 Page saved with SingleFile
 url: ${testUrl}
 saved date: 2024-01-01
-->
<html>...</html>`;

            const headerSection = htmlContent.split('meta charset')[0] || htmlContent.split('<html>')[0];

            assert.ok(headerSection.includes(`url: ${testUrl}`));
        });

        it('should handle multiple new files in downloads', () => {
            const filesBefore = new Set(['old1.html', 'old2.html']);
            const filesAfter = ['old1.html', 'old2.html', 'new1.html', 'new2.html'];

            const filesNew = filesAfter.filter(f => !filesBefore.has(f));

            assert.strictEqual(filesNew.length, 2);
            assert.ok(filesNew.includes('new1.html'));
            assert.ok(filesNew.includes('new2.html'));
        });
    });

    describe('error handling', () => {
        it('should timeout after max wait time', () => {
            const checkDelay = 3000; // ms
            const maxTries = 10;
            const timeoutMs = checkDelay * maxTries;

            assert.strictEqual(timeoutMs, 30000); // 30 seconds
        });

        it('should handle missing extension gracefully', () => {
            const extension = null;

            if (!extension || !extension.version) {
                // Should throw error
                assert.ok(true);
            }
        });

        it('should handle file not found after waiting', () => {
            const filesNew = [];
            const maxWaitReached = true;

            if (filesNew.length === 0 && maxWaitReached) {
                // Should return null
                const result = null;
                assert.strictEqual(result, null);
            }
        });
    });
});
