#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');

const DEFAULT_URL = 'http://web.archivebox.localhost:8000/add/';
const DEFAULT_OUTPUT = 'tmp/add-page.png';

function usage() {
  console.log(`
Usage:
  node bin/take_screenshot.js [url] [output.png]

Environment:
  SESSIONID                  Django session cookie value for admin.archivebox.localhost
  SCREENSHOT_COOKIE_NAME     Cookie name, defaults to sessionid
  SCREENSHOT_COOKIE_DOMAIN   Cookie domain, defaults to admin.archivebox.localhost
  CHROME_BINARY              Chromium/Chrome executable path
  SCREENSHOT_WIDTH           Viewport width, defaults to 1600
  SCREENSHOT_HEIGHT          Viewport height, defaults to 1400
  SCREENSHOT_FULL_PAGE       Set to 1 to capture the full page, defaults to viewport only
  SCREENSHOT_SCROLL_SELECTOR Scroll this selector into view before capture
  SCREENSHOT_WAIT_SELECTOR   Wait for this selector before capture
  SCREENSHOT_CLICK_SELECTOR  Click this selector before capture
  SCREENSHOT_AFTER_CLICK_WAIT_SELECTOR  Wait for this selector after clicking
  SCREENSHOT_HOST_RESOLVER_RULES  Chrome host resolver rules
  SCREENSHOT_SNAPSHOT_VIEW   Set to list or grid before loading the page
  SCREENSHOT_RESET_FILTERS   Set to 1 to clear the admin filter collapsed preference
`);
}

function argValue(name) {
  const idx = process.argv.indexOf(name);
  return idx === -1 ? null : process.argv[idx + 1];
}

function firstPositionalArg(index) {
  return process.argv.slice(2).filter((arg) => !arg.startsWith('--'))[index] || null;
}

function chromePath() {
  const configured = process.env.CHROME_BINARY;
  if (!configured || !path.isAbsolute(configured) || !fs.existsSync(configured)) {
    throw new Error('CHROME_BINARY must be an absolute executable path resolved by abxpkg');
  }
  return configured;
}

async function main() {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    usage();
    return;
  }

  const url = argValue('--url') || firstPositionalArg(0) || DEFAULT_URL;
  const output = path.resolve(argValue('--output') || firstPositionalArg(1) || DEFAULT_OUTPUT);
  const width = Number(process.env.SCREENSHOT_WIDTH || 1600);
  const height = Number(process.env.SCREENSHOT_HEIGHT || 1400);
  const fullPage = process.env.SCREENSHOT_FULL_PAGE === '1';

  fs.mkdirSync(path.dirname(output), { recursive: true });

  const launchOptions = {
    headless: true,
    defaultViewport: { width, height },
    executablePath: chromePath(),
  };
  if (process.env.SCREENSHOT_HOST_RESOLVER_RULES) {
    launchOptions.args = [`--host-resolver-rules=${process.env.SCREENSHOT_HOST_RESOLVER_RULES}`];
  }
  const browser = await puppeteer.launch(launchOptions);
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(45000);

    if (process.env.SCREENSHOT_SNAPSHOT_VIEW || process.env.SCREENSHOT_RESET_FILTERS === '1') {
      await page.evaluateOnNewDocument((snapshotView, resetFilters) => {
        if (snapshotView) localStorage.setItem('preferred_snapshot_view_mode', snapshotView);
        if (resetFilters) localStorage.removeItem('admin-filters-collapsed');
      }, process.env.SCREENSHOT_SNAPSHOT_VIEW || '', process.env.SCREENSHOT_RESET_FILTERS === '1');
    }

    if (process.env.SESSIONID) {
      const cookie = {
        name: process.env.SCREENSHOT_COOKIE_NAME || 'sessionid',
        value: process.env.SESSIONID,
        path: '/',
      };
      if (process.env.SCREENSHOT_COOKIE_DOMAIN) {
        cookie.domain = process.env.SCREENSHOT_COOKIE_DOMAIN;
      } else {
        cookie.url = new URL(url).origin;
      }
      await page.setCookie(cookie);
    }

    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });

    await page.waitForSelector('body');
    await page.waitForSelector('#progress-monitor, #add-form', { timeout: 5000 }).catch(() => {});
    if (process.env.SCREENSHOT_WAIT_SELECTOR) {
      await page.waitForSelector(process.env.SCREENSHOT_WAIT_SELECTOR, { timeout: 45000 });
    }
    if (process.env.SCREENSHOT_CLICK_SELECTOR) {
      await page.waitForSelector(process.env.SCREENSHOT_CLICK_SELECTOR, { timeout: 45000 });
      await page.click(process.env.SCREENSHOT_CLICK_SELECTOR);
    }
    if (process.env.SCREENSHOT_AFTER_CLICK_WAIT_SELECTOR) {
      await page.waitForSelector(process.env.SCREENSHOT_AFTER_CLICK_WAIT_SELECTOR, { timeout: 45000 });
    }
    if (process.env.SCREENSHOT_SCROLL_SELECTOR) {
      await page.waitForSelector(process.env.SCREENSHOT_SCROLL_SELECTOR, { timeout: 45000 }).catch(() => {});
      await page.evaluate((selector) => {
        document.querySelector(selector)?.scrollIntoView({ block: 'start', inline: 'nearest' });
      }, process.env.SCREENSHOT_SCROLL_SELECTOR);
    }

    const frameHandle = await page.$('.crawl-snapshots-embed iframe');
    if (frameHandle) {
      const frame = await frameHandle.contentFrame();
      if (frame) {
        await frame.waitForSelector('#changelist-form', { timeout: 45000 }).catch(() => {});
        await frame.waitForSelector('#result_list', { timeout: 45000 }).catch(() => {});
      }
    }

    await new Promise((resolve) => setTimeout(resolve, 1200));

    const checks = await page.evaluate(() => ({
      url: location.href,
      title: document.title,
      progressMonitorDisplay: document.querySelector('#progress-monitor')
        ? getComputedStyle(document.querySelector('#progress-monitor')).display
        : 'missing',
      progressCrawls: document.querySelectorAll('#progress-monitor .crawl-item').length,
      progressSnapshots: document.querySelectorAll('#progress-monitor .snapshot-item').length,
      screencastVisible: Boolean(document.querySelector('#progress-monitor .screencast-panel.visible')),
      screencastImageLoaded: (() => {
        const img = document.querySelector('#progress-monitor .screencast-panel.visible img');
        return Boolean(img && img.complete && img.naturalWidth > 0 && img.naturalHeight > 0);
      })(),
      screencastImageSize: (() => {
        const img = document.querySelector('#progress-monitor .screencast-panel.visible img');
        return img ? `${img.naturalWidth}x${img.naturalHeight}` : '';
      })(),
      snapshotEmbed: Boolean(document.querySelector('.crawl-snapshots-embed iframe')),
      addForm: Boolean(document.querySelector('#add-form')),
      limitFields: Array.from(document.querySelectorAll('.crawl-limit-field label')).map((el) => el.textContent.trim()),
    }));

    let frameChecks = null;
    const embeddedFrameHandle = await page.$('.crawl-snapshots-embed iframe');
    if (embeddedFrameHandle) {
      const frame = await embeddedFrameHandle.contentFrame();
      if (frame) {
        frameChecks = await frame.evaluate(() => ({
          rows: document.querySelectorAll('#result_list tbody tr').length,
          actionCheckboxes: document.querySelectorAll('#result_list input.action-select').length,
          searchModeRadios: document.querySelectorAll('#changelist-search input[type="radio"][name="search_mode"]').length,
          progressMonitorDisplay: document.querySelector('#progress-monitor')
            ? getComputedStyle(document.querySelector('#progress-monitor')).display
            : 'missing',
        }));
      }
    }

    await page.screenshot({ path: output, fullPage });
    console.log(JSON.stringify({ screenshotPath: output, checks, frameChecks }, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
