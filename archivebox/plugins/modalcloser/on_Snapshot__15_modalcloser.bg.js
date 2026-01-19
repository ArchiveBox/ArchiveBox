#!/usr/bin/env node
/**
 * Auto-close browser dialogs and CSS modals.
 *
 * Runs as a background script that sets up listeners BEFORE navigation,
 * so it catches modals that appear on page load.
 *
 * Handles:
 * - Browser dialogs (alert, confirm, prompt, beforeunload)
 * - Framework modals (Bootstrap, Tailwind, shadcn, Angular Material, jQuery UI, SweetAlert)
 * - Cookie consent banners, newsletter popups, age gates
 *
 * Usage: on_Snapshot__15_modalcloser.bg.js --url=<url> --snapshot-id=<uuid>
 * Output: JSONL with modal close stats (no files created)
 * Termination: Send SIGTERM to exit cleanly
 *
 * Environment variables:
 *     MODALCLOSER_ENABLED: Enable/disable (default: true)
 *     MODALCLOSER_TIMEOUT: Delay before auto-closing dialogs in ms (default: 1250)
 *     MODALCLOSER_POLL_INTERVAL: How often to check for CSS modals in ms (default: 500)
 */

const fs = require('fs');
const path = require('path');

// Add NODE_MODULES_DIR to module resolution paths if set
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);

// Import shared utilities from chrome_utils.js
const {
    getEnvBool,
    getEnvInt,
    parseArgs,
    readCdpUrl,
    readTargetId,
} = require('../chrome/chrome_utils.js');

// Check if modalcloser is enabled BEFORE requiring puppeteer
if (!getEnvBool('MODALCLOSER_ENABLED', true)) {
    console.error('Skipping modalcloser (MODALCLOSER_ENABLED=False)');
    process.exit(0);
}

const puppeteer = require('puppeteer-core');

const PLUGIN_NAME = 'modalcloser';
const CHROME_SESSION_DIR = '../chrome';

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Close CSS modals using framework-specific dismiss methods.
 * Returns the number of modals closed.
 */
async function closeModals(page) {
    return page.evaluate(() => {
        let closed = 0;

        // Bootstrap 4/5 - use Bootstrap's modal API
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            document.querySelectorAll('.modal.show').forEach(el => {
                try {
                    const modal = bootstrap.Modal.getInstance(el);
                    if (modal) { modal.hide(); closed++; }
                } catch (e) {}
            });
        }

        // Bootstrap 3 / jQuery - use jQuery modal API
        if (typeof jQuery !== 'undefined' && jQuery.fn && jQuery.fn.modal) {
            try {
                const $modals = jQuery('.modal.in, .modal.show');
                if ($modals.length > 0) {
                    $modals.modal('hide');
                    closed += $modals.length;
                }
            } catch (e) {}
        }

        // shadcn/Radix UI - fire escape key to dismiss
        document.querySelectorAll('[data-radix-dialog-overlay], [data-state="open"][role="dialog"]').forEach(el => {
            try {
                el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
                closed++;
            } catch (e) {}
        });

        // Angular Material - click backdrop to dismiss
        document.querySelectorAll('.cdk-overlay-backdrop').forEach(el => {
            try {
                el.click();
                closed++;
            } catch (e) {}
        });

        // Tailwind / Headless UI - dispatch escape key
        document.querySelectorAll('[role="dialog"][aria-modal="true"]').forEach(el => {
            try {
                el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
                closed++;
            } catch (e) {}
        });

        // jQuery UI Dialog
        if (typeof jQuery !== 'undefined' && jQuery.ui && jQuery.ui.dialog) {
            try {
                const $dialogs = jQuery('.ui-dialog-content');
                if ($dialogs.length > 0) {
                    $dialogs.dialog('close');
                    closed += $dialogs.length;
                }
            } catch (e) {}
        }

        // SweetAlert2
        if (typeof Swal !== 'undefined' && Swal.close) {
            try { Swal.close(); closed++; } catch (e) {}
        }

        // SweetAlert 1
        if (typeof swal !== 'undefined' && swal.close) {
            try { swal.close(); closed++; } catch (e) {}
        }

        // Generic fallback - hide unrecognized modals with CSS
        const genericSelectors = [
            // CookieYes (cky)
            '.cky-consent-container', '.cky-popup-center', '.cky-overlay', '.cky-modal', '#ckyPreferenceCenter',
            // OneTrust
            '#onetrust-consent-sdk', '#onetrust-banner-sdk', '.onetrust-pc-dark-filter', '#onetrust-pc-sdk',
            // CookieBot
            '#CybotCookiebotDialog', '#CybotCookiebotDialogBodyUnderlay', '#CookiebotWidget',
            // Quantcast / CMP
            '.qc-cmp-ui-container', '#qc-cmp2-container', '.qc-cmp2-summary-buttons',
            // TrustArc / TrustE
            '#truste-consent-track', '.truste-banner', '#truste-consent-content',
            // Osano
            '.osano-cm-window', '.osano-cm-dialog',
            // Klaro
            '.klaro .cookie-modal', '.klaro .cookie-notice',
            // Tarteaucitron
            '#tarteaucitronRoot', '#tarteaucitronAlertBig',
            // Complianz (WordPress)
            '.cmplz-cookiebanner', '#cmplz-cookiebanner-container',
            // GDPR Cookie Consent (WordPress)
            '#gdpr-cookie-consent-bar', '.gdpr-cookie-consent-popup',
            // Cookie Notice (WordPress)
            '#cookie-notice', '.cookie-notice-container',
            // EU Cookie Law
            '.eupopup', '#eu-cookie-law',
            // Didomi
            '#didomi-popup', '#didomi-host', '.didomi-popup-container',
            // Usercentrics
            '#usercentrics-root', '.uc-banner',
            // Axeptio
            '#axeptio_overlay', '#axeptio_btn',
            // iubenda
            '#iubenda-cs-banner', '.iubenda-cs-container',
            // Termly
            '.termly-consent-banner', '#termly-code-snippet-support',
            // Borlabs Cookie (WordPress)
            '#BorlabsCookieBox', '.BorlabsCookie',
            // CookieFirst
            '.cookiefirst-root', '#cookiefirst-root',
            // CookieScript
            '#cookiescript_injected', '.cookiescript_injected_wrapper',
            // Civic Cookie Control
            '#ccc', '#ccc-overlay',
            // Generic patterns
            '#cookie-consent', '.cookie-banner', '.cookie-notice',
            '#cookieConsent', '.cookie-consent', '.cookies-banner',
            '[class*="cookie"][class*="banner"]', '[class*="cookie"][class*="notice"]',
            '[class*="cookie"][class*="popup"]', '[class*="cookie"][class*="modal"]',
            '[class*="consent"][class*="banner"]', '[class*="consent"][class*="popup"]',
            '[class*="gdpr"]', '[class*="privacy"][class*="banner"]',
            // Modal overlays and backdrops
            '.modal-overlay:not([style*="display: none"])',
            '.modal-backdrop:not([style*="display: none"])',
            '.overlay-visible',
            // Popup overlays
            '.popup-overlay', '.newsletter-popup', '.age-gate',
            '.subscribe-popup', '.subscription-modal',
            // Generic modal patterns
            '[class*="modal"][class*="open"]:not(.modal-open)',
            '[class*="modal"][class*="show"][class*="overlay"]',
            '[class*="modal"][class*="visible"]',
            '[class*="dialog"][class*="open"]',
            '[class*="overlay"][class*="visible"]',
            // Interstitials
            '.interstitial', '.interstitial-wrapper',
            '[class*="interstitial"]',
        ];

        genericSelectors.forEach(selector => {
            try {
                document.querySelectorAll(selector).forEach(el => {
                    // Skip if already hidden
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return;

                    el.style.display = 'none';
                    el.style.visibility = 'hidden';
                    el.style.opacity = '0';
                    el.style.pointerEvents = 'none';
                    closed++;
                });
            } catch (e) {}
        });

        // Remove body scroll lock (common pattern when modals are open)
        try {
            document.body.style.overflow = '';
            document.body.style.position = '';
            document.body.classList.remove('modal-open', 'overflow-hidden', 'no-scroll', 'scroll-locked');
            document.documentElement.style.overflow = '';
            document.documentElement.classList.remove('overflow-hidden', 'no-scroll');
        } catch (e) {}

        return closed;
    });
}

async function main() {
    const args = parseArgs();
    const url = args.url;
    const snapshotId = args.snapshot_id;

    if (!url || !snapshotId) {
        console.error('Usage: on_Snapshot__15_modalcloser.bg.js --url=<url> --snapshot-id=<uuid>');
        process.exit(1);
    }

    const dialogTimeout = getEnvInt('MODALCLOSER_TIMEOUT', 1250);
    const pollInterval = getEnvInt('MODALCLOSER_POLL_INTERVAL', 500);

    const cdpUrl = readCdpUrl(CHROME_SESSION_DIR);
    if (!cdpUrl) {
        console.error('ERROR: Chrome CDP URL not found (chrome plugin must run first)');
        process.exit(1);
    }

    let browser = null;
    let dialogsClosed = 0;
    let cssModalsClosed = 0;
    let running = true;

    // Handle SIGTERM for clean exit
    process.on('SIGTERM', () => {
        running = false;
        const total = dialogsClosed + cssModalsClosed;
        console.error(`Modalcloser exiting: closed ${dialogsClosed} dialogs, ${cssModalsClosed} CSS modals`);

        const outputStr = total > 0
            ? `closed ${total} modals (${dialogsClosed} dialogs, ${cssModalsClosed} CSS)`
            : 'no modals detected';

        console.log(JSON.stringify({
            type: 'ArchiveResult',
            status: 'succeeded',
            output_str: outputStr,
        }));

        if (browser) browser.disconnect();
        process.exit(0);
    });

    try {
        browser = await puppeteer.connect({ browserWSEndpoint: cdpUrl });

        const pages = await browser.pages();
        if (pages.length === 0) {
            throw new Error('No pages found in browser');
        }

        // Find the right page by target ID
        const targetId = readTargetId(CHROME_SESSION_DIR);
        let page = null;
        if (targetId) {
            page = pages.find(p => {
                const target = p.target();
                return target && target._targetId === targetId;
            });
        }
        if (!page) {
            page = pages[pages.length - 1];
        }

        // console.error(`Modalcloser listening on ${url}`);

        // Set up dialog handler (for JS alert/confirm/prompt/beforeunload)
        page.on('dialog', async (dialog) => {
            const type = dialog.type();
            const message = dialog.message().substring(0, 100);
            console.error(`Auto-closing dialog: ${type} - "${message}"`);

            // Small delay before accepting (some pages expect a brief pause)
            await sleep(dialogTimeout);
            try {
                await dialog.accept();
                dialogsClosed++;
            } catch (e) {
                // Dialog may have been dismissed by page
            }
        });

        // Poll for CSS modals
        while (running) {
            try {
                const closed = await closeModals(page);
                if (closed > 0) {
                    console.error(`Closed ${closed} CSS modals`);
                    cssModalsClosed += closed;
                }
            } catch (e) {
                // Page may have navigated or been closed
                if (!running) break;
            }
            await sleep(pollInterval);
        }

    } catch (e) {
        if (browser) browser.disconnect();
        console.error(`ERROR: ${e.name}: ${e.message}`);
        process.exit(1);
    }
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
