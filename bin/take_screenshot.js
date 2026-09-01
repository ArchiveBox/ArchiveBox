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
  SCREENSHOT_USER_DATA_DIR   Chrome profile directory (e.g. a persona's chrome_profile)
  SCREENSHOT_LOGIN_USERNAME  Log in through #id_username before capture
  SCREENSHOT_LOGIN_PASSWORD  Password used with SCREENSHOT_LOGIN_USERNAME
  CHROME_BINARY              Chromium/Chrome executable path
  SCREENSHOT_WIDTH           Viewport width, defaults to 1600
  SCREENSHOT_HEIGHT          Viewport height, defaults to 1400
  SCREENSHOT_VARIANTS_JSON   JSON array of {path,width,height} captures from one loaded page
  SCREENSHOT_FULL_PAGE       Set to 1 to capture the full page, defaults to viewport only
  SCREENSHOT_SCROLL_SELECTOR Scroll this selector into view before capture
  SCREENSHOT_WAIT_SELECTOR   Wait for this selector before capture
  SCREENSHOT_CLICK_SELECTOR  Click this selector before capture
  SCREENSHOT_AFTER_CLICK_WAIT_SELECTOR  Wait for this selector after clicking
  SCREENSHOT_HOST_RESOLVER_RULES  Chrome host resolver rules
  SCREENSHOT_SNAPSHOT_VIEW   Set to list or grid before loading the page
  SCREENSHOT_SNAPSHOT_HEADER Set to expanded or collapsed before loading a snapshot detail page
  SCREENSHOT_EXPECT_PLUGIN   Require this snapshot output plugin to be selected
  SCREENSHOT_EXPECT_LIVE_PROGRESS  Require real progress bars and a loaded screencast frame
  SCREENSHOT_COLLAPSE_FILTERS Set to 1 to keep admin filters out of screenshots
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

function needsNoSandbox() {
  return process.platform === 'linux' && !String(process.env.DISPLAY || '').trim();
}

function addLaunchArg(args, arg) {
  if (!args.includes(arg)) args.push(arg);
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
  const variants = process.env.SCREENSHOT_VARIANTS_JSON
    ? JSON.parse(process.env.SCREENSHOT_VARIANTS_JSON)
    : [];

  if (!Array.isArray(variants)) {
    throw new Error('SCREENSHOT_VARIANTS_JSON must be a JSON array');
  }
  for (const variant of variants) {
    if (!variant.path || !Number.isInteger(variant.width) || !Number.isInteger(variant.height)) {
      throw new Error('Each screenshot variant requires path, integer width, and integer height');
    }
  }

  fs.mkdirSync(path.dirname(output), { recursive: true });

  const launchOptions = {
    headless: true,
    defaultViewport: { width, height },
    executablePath: chromePath(),
    args: [],
  };
  if (process.env.SCREENSHOT_USER_DATA_DIR) {
    launchOptions.userDataDir = path.resolve(process.env.SCREENSHOT_USER_DATA_DIR);
  }
  if (process.env.SCREENSHOT_HOST_RESOLVER_RULES) {
    addLaunchArg(launchOptions.args, `--host-resolver-rules=${process.env.SCREENSHOT_HOST_RESOLVER_RULES}`);
  }
  if (needsNoSandbox()) {
    addLaunchArg(launchOptions.args, '--no-sandbox');
    addLaunchArg(launchOptions.args, '--disable-setuid-sandbox');
  }
  const browser = await puppeteer.launch(launchOptions);
  try {
    // Persistent persona profiles can restore tabs left by earlier launches.
    // Close them before navigating so repeated captures do not multiply live
    // admin requests and overwhelm the server being documented.
    const restoredPages = await browser.pages();
    const page = await browser.newPage();
    await page.setCacheEnabled(false);
    await Promise.all(restoredPages.map((restoredPage) => restoredPage.close()));
    page.setDefaultTimeout(45000);

    const client = await page.createCDPSession();
    const documentRequests = new Map();
    await client.send('Network.enable');
    client.on('Network.requestWillBeSent', (event) => {
      if (event.type !== 'Document') return;
      documentRequests.set(event.requestId, {
        url: event.request.url,
        requestTimestamp: event.timestamp,
      });
    });
    client.on('Network.responseReceived', (event) => {
      if (event.type !== 'Document') return;
      const record = documentRequests.get(event.requestId);
      if (!record) return;
      record.responseTimestamp = event.timestamp;
      record.status = event.response.status;
      record.responseUrl = event.response.url;
      if (Number.isFinite(record.requestTimestamp) && Number.isFinite(record.responseTimestamp)) {
        record.ttfbMs = Math.round((record.responseTimestamp - record.requestTimestamp) * 1000);
      }
    });

    if (process.env.SCREENSHOT_SNAPSHOT_VIEW || process.env.SCREENSHOT_SNAPSHOT_HEADER || process.env.SCREENSHOT_COLLAPSE_FILTERS === '1' || process.env.SCREENSHOT_RESET_FILTERS === '1') {
      await page.evaluateOnNewDocument((snapshotView, snapshotHeader, collapseFilters, resetFilters) => {
        if (snapshotView) localStorage.setItem('preferred_snapshot_view_mode', snapshotView);
        if (snapshotHeader === 'expanded') localStorage.setItem('archivebox-snapshot-header-visible', 'true');
        if (snapshotHeader === 'collapsed') localStorage.setItem('archivebox-snapshot-header-visible', 'false');
        if (collapseFilters) localStorage.setItem('admin-filters-collapsed', 'true');
        else if (resetFilters) localStorage.removeItem('admin-filters-collapsed');
      }, process.env.SCREENSHOT_SNAPSHOT_VIEW || '', process.env.SCREENSHOT_SNAPSHOT_HEADER || '', process.env.SCREENSHOT_COLLAPSE_FILTERS === '1', process.env.SCREENSHOT_RESET_FILTERS === '1');
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

    let navigationResponse = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });

    if (process.env.SCREENSHOT_LOGIN_USERNAME || process.env.SCREENSHOT_LOGIN_PASSWORD) {
      if (!process.env.SCREENSHOT_LOGIN_USERNAME || !process.env.SCREENSHOT_LOGIN_PASSWORD) {
        throw new Error('SCREENSHOT_LOGIN_USERNAME and SCREENSHOT_LOGIN_PASSWORD must be set together');
      }
      await page.waitForSelector('#id_username');
      await page.type('#id_username', process.env.SCREENSHOT_LOGIN_USERNAME);
      await page.type('#id_password', process.env.SCREENSHOT_LOGIN_PASSWORD);
      const [loginResponse] = await Promise.all([
        page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 60000 }),
        page.click('button[type="submit"], input[type="submit"]'),
      ]);
      navigationResponse = loginResponse || navigationResponse;
      if (new URL(page.url()).pathname.includes('/admin/login/')) {
        const loginError = await page.evaluate(() => Array.from(document.querySelectorAll('.errornote, .errorlist')).map((element) => element.textContent.trim()).filter(Boolean).join(' '));
        const cookieDetails = (await page.cookies()).map((cookie) => `${cookie.name}@${cookie.domain}${cookie.path}${cookie.secure ? ';Secure' : ''}`).join(', ') || 'none';
        throw new Error(`ArchiveBox persona login failed at ${page.url()}: ${loginError || 'no form error shown'} (cookies: ${cookieDetails})`);
      }
    }

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

    if (process.env.SCREENSHOT_EXPECT_PLUGIN) {
      const expectedPlugin = process.env.SCREENSHOT_EXPECT_PLUGIN.toLowerCase();
      await page.waitForFunction((pluginName) => {
        const selectedCard = document.querySelector('.thumb-card.selected-card[data-plugin-name]');
        const frame = document.querySelector('#main-frame');
        const frameRect = frame?.getBoundingClientRect();
        return selectedCard?.dataset.pluginName?.toLowerCase() === pluginName
          && frame
          && frame.getAttribute('src')
          && frame.getAttribute('src') !== 'about:blank'
          && frameRect
          && frameRect.width >= Math.min(window.innerWidth * 0.9, window.innerWidth - 8)
          && frameRect.height >= Math.min(window.innerHeight * 0.35, 320);
      }, { timeout: 45000 }, expectedPlugin);
      await page.waitForFunction(() => {
        const frames = [document.querySelector('#main-frame'), document.querySelector('.thumb-card.selected-card iframe')]
          .filter(Boolean);
        if (!frames.length) return true;
        return frames.every((frame) => {
          try {
            const doc = frame.contentDocument || frame.contentWindow?.document;
            if (!doc || doc.readyState === 'loading') return false;
            const images = Array.from(doc.images || []);
            return images.every((img) => img.complete && (img.naturalWidth > 0 || img.currentSrc.startsWith('data:')));
          } catch (err) {
            return true;
          }
        });
      }, { timeout: 45000, polling: 250 }).catch(() => {});
    }

    if (process.env.SCREENSHOT_EXPECT_LIVE_PROGRESS === '1') {
      await page.waitForFunction(() => {
        const monitor = document.querySelector('#progress-monitor');
        const bars = [...document.querySelectorAll('#progress-monitor .progress-bar')]
          .filter((bar) => bar.getClientRects().length > 0 && bar.offsetWidth > 0 && bar.offsetHeight > 0);
        const panel = document.querySelector('#progress-monitor .screencast-panel.visible');
        const image = panel?.querySelector('img');
        const placeholder = panel?.querySelector('.screencast-placeholder');
        return monitor
          && getComputedStyle(monitor).display !== 'none'
          && !monitor.classList.contains('collapsed')
          && monitor.querySelector('.progress-content')?.getClientRects().length > 0
          && bars.length >= 2
          && panel?.getClientRects().length > 0
          && panel.offsetWidth > 0
          && panel.offsetHeight > 0
          && (
            (
              image?.complete
              && image.naturalWidth > 0
              && image.naturalHeight > 0
            )
            || placeholder?.getClientRects().length > 0
          );
      }, { timeout: 120000, polling: 250 });
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
      screencastPlaceholderVisible: Boolean(document.querySelector('#progress-monitor .screencast-panel.visible .screencast-placeholder')),
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
      snapshotOutputPlugins: [...new Set(
        [...document.querySelectorAll('.thumb-card[data-plugin-name] a[target="preview"]')]
          .map((link) => link.closest('.thumb-card')?.dataset.pluginName)
          .filter(Boolean),
      )],
      snapshotOutputs: [...document.querySelectorAll('.thumb-card[data-plugin-name]')]
        .map((card) => ({
          plugin: card.dataset.pluginName || '',
          previewUrl: card.dataset.previewUrl || card.querySelector('a[target="preview"]')?.getAttribute('href') || '',
        }))
        .filter((output) => output.plugin && output.previewUrl),
      selectedSnapshotOutputPlugin: document.querySelector('.thumb-card.selected-card[data-plugin-name]')?.dataset.pluginName || '',
    }));
    checks.status = navigationResponse ? navigationResponse.status() : null;
    checks.finalUrl = page.url();
    const navigationUrl = navigationResponse?.url() || page.url();
    const matchingDocumentRequests = [...documentRequests.values()]
      .filter((record) => record.status === checks.status && Number.isFinite(record.ttfbMs))
      .filter((record) => {
        const responseUrl = record.responseUrl || record.url || '';
        return responseUrl === navigationUrl || responseUrl === checks.finalUrl || responseUrl.split('#')[0] === checks.finalUrl.split('#')[0];
      });
    const timingRecord = matchingDocumentRequests.at(-1)
      || [...documentRequests.values()].filter((record) => Number.isFinite(record.ttfbMs)).at(-1);
    if (timingRecord) {
      checks.ttfbMs = timingRecord.ttfbMs;
    }

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

    const screenshotPaths = [];
    if (variants.length) {
      for (const variant of variants) {
        const variantPath = path.resolve(variant.path);
        fs.mkdirSync(path.dirname(variantPath), { recursive: true });
        await page.setViewport({width: variant.width, height: variant.height, deviceScaleFactor: 1});
        await new Promise((resolve) => setTimeout(resolve, 300));
        await page.screenshot({ path: variantPath, fullPage });
        screenshotPaths.push(variantPath);
      }
    } else {
      await page.screenshot({ path: output, fullPage });
      screenshotPaths.push(output);
    }
    console.log(JSON.stringify({ screenshotPath: screenshotPaths[0], screenshotPaths, checks, frameChecks }, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
