#!/usr/bin/env node
/**
 * Extract SEO metadata from a URL.
 *
 * Extracts all <meta> tags including:
 * - og:* (Open Graph)
 * - twitter:*
 * - description, keywords, author
 * - Any other meta tags
 *
 * Usage: on_Snapshot__38_seo.js --url=<url> --snapshot-id=<uuid>
 * Output: Writes seo/seo.json
 *
 * Environment variables:
 *     SAVE_SEO: Enable SEO extraction (default: true)
 */

const fs = require('fs');
const path = require('path');
// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

// Import shared utilities from chrome_utils.js
const {
    getEnvBool,
    getEnvInt,
    parseArgs,
    connectToPage,
    waitForPageLoaded,
} = require('../chrome/chrome_utils.js');

// Extractor metadata
const PLUGIN_NAME = 'seo';
const OUTPUT_DIR = '.';
const OUTPUT_FILE = 'seo.json';
const CHROME_SESSION_DIR = '../chrome';

// Extract SEO metadata
async function extractSeo(url) {
    // Output directory is current directory (hook already runs in output dir)
    const outputPath = path.join(OUTPUT_DIR, OUTPUT_FILE);
    const timeout = getEnvInt('SEO_TIMEOUT', getEnvInt('TIMEOUT', 30)) * 1000;
    let browser = null;

    try {
        // Connect to existing Chrome session and get target page
        const connection = await connectToPage({
            chromeSessionDir: CHROME_SESSION_DIR,
            timeoutMs: timeout,
            puppeteer,
        });
        browser = connection.browser;
        const page = connection.page;

        // Extract all meta tags
        const seoData = await page.evaluate(() => {
            const metaTags = Array.from(document.querySelectorAll('meta'));
            const seo = {
                url: window.location.href,
                title: document.title || '',
            };

            // Process each meta tag
            metaTags.forEach(tag => {
                // Get the key (name or property attribute)
                const key = tag.getAttribute('name') || tag.getAttribute('property') || '';
                const content = tag.getAttribute('content') || '';

                if (key && content) {
                    // Store by key
                    seo[key] = content;
                }
            });

            // Also get canonical URL if present
            const canonical = document.querySelector('link[rel="canonical"]');
            if (canonical) {
                seo.canonical = canonical.getAttribute('href');
            }

            // Get language
            const htmlLang = document.documentElement.lang;
            if (htmlLang) {
                seo.language = htmlLang;
            }

            return seo;
        });

        // Write output
        fs.writeFileSync(outputPath, JSON.stringify(seoData, null, 2));

        return { success: true, output: outputPath, seoData };

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
        console.error('Usage: on_Snapshot__38_seo.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const startTs = new Date();
    let status = 'failed';
    let output = null;
    let error = '';

    try {
        // Check if enabled
        if (!getEnvBool('SEO_ENABLED', true)) {
            console.log('Skipping SEO (SEO_ENABLED=False)');
            // Output clean JSONL (no RESULT_JSON= prefix)
            console.log(JSON.stringify({
                type: 'ArchiveResult',
                status: 'skipped',
                output_str: 'SEO_ENABLED=False',
            }));
            process.exit(0);
        }

        const timeout = getEnvInt('SEO_TIMEOUT', getEnvInt('TIMEOUT', 30)) * 1000;
        await waitForPageLoaded(CHROME_SESSION_DIR, timeout * 4, 200);

        const result = await extractSeo(url);

        if (result.success) {
            status = 'succeeded';
            output = result.output;
            const metaCount = Object.keys(result.seoData).length - 2;  // Subtract url and title
            console.log(`SEO metadata extracted: ${metaCount} meta tags`);
        } else {
            status = 'failed';
            error = result.error;
        }
    } catch (e) {
        error = `${e.name}: ${e.message}`;
        status = 'failed';
    }

    const endTs = new Date();

    if (error) console.error(`ERROR: ${error}`);

    // Output clean JSONL (no RESULT_JSON= prefix)
    console.log(JSON.stringify({
        type: 'ArchiveResult',
        status,
        output_str: output || error || '',
    }));

    process.exit(status === 'succeeded' ? 0 : 1);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
