#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const {spawnSync} = require('node:child_process');

const DEFAULT_URL = 'http://web.archivebox.localhost:5797/add/';
const DEFAULT_OUTPUT = 'tmp/add-page.png';

function usage() {
  console.log(`
Usage:
  node bin/screenshot_gallery_helpers.js [url] [output.png]
  node bin/screenshot_gallery_helpers.js setup ADMIN_BASE_URL USERNAME prepare|replay

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
  SCREENSHOT_REQUIRE_IN_FRAME_SELECTOR Require this control within each screenshot viewport
  SCREENSHOT_WAIT_SELECTOR   Wait for this selector before capture
  SCREENSHOT_WAIT_FOR_TEXT   Wait for this visible page text before capture
  SCREENSHOT_PREVIEW_WAIT_FOR_TEXT Wait for this text in the selected snapshot preview iframe
  SCREENSHOT_WAIT_FOR_MODEL   Require nonempty rendered model geometry
  SCREENSHOT_REQUIRE_LIVE_PROGRESS  Require active snapshot progress and a nonblank decoded screencast within 60s
  SCREENSHOT_CLICK_SELECTOR  Click this selector before capture
  SCREENSHOT_AFTER_CLICK_WAIT_SELECTOR  Wait for this selector after clicking
  SCREENSHOT_HOST_RESOLVER_RULES  Chrome host resolver rules
  SCREENSHOT_SNAPSHOT_VIEW   Set to list or grid before loading the page
  SCREENSHOT_SNAPSHOT_HEADER Set to expanded or collapsed before loading a snapshot detail page
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

async function waitForVisibleCardPreviews(page, timeout = 45000) {
  // The page load event does not wait for nested lazy card images. Capture their
  // decoded pixels, without forcing hidden alternatives or offscreen cards to load.
  const cardHandles = await page.$$('iframe[title$=" card"]');
  const visibleFrames = [];
  for (const cardHandle of cardHandles) {
    const visible = await cardHandle.evaluate((iframe) => {
      const rect = iframe.getBoundingClientRect();
      const style = getComputedStyle(iframe);
      return rect.width > 0
        && rect.height > 0
        && rect.bottom > 0
        && rect.right > 0
        && rect.top < innerHeight
        && rect.left < innerWidth
        && style.visibility !== 'hidden'
        && Number(style.opacity) > 0;
    });
    if (!visible) continue;

    const expectedUrl = await cardHandle.evaluate((iframe) => iframe.hasAttribute('srcdoc') ? 'about:srcdoc' : iframe.src);
    const frame = await cardHandle.contentFrame();
    if (!frame) {
      // Live card refreshes can detach an owner while its document is loading.
      // Only detached owners cease to be required; a connected blank card is an error.
      if (!await cardHandle.evaluate((iframe) => iframe.isConnected)) continue;
      throw new Error(`Visible snapshot card iframe has no loaded document: ${new URL(expectedUrl).pathname}`);
    }
    visibleFrames.push({cardHandle, frame, expectedUrl});
  }

  await Promise.all(visibleFrames.map(async ({cardHandle, frame, expectedUrl}) => {
    try {
      await frame.waitForFunction(async (url) => {
        if (location.href !== url || document.readyState !== 'complete') return false;
        const images = [...document.images].filter((img) => {
          const rect = img.getBoundingClientRect();
          const style = getComputedStyle(img);
          return rect.width > 0
            && rect.height > 0
            && rect.bottom > 0
            && rect.right > 0
            && rect.top < innerHeight
            && rect.left < innerWidth
            && style.display !== 'none'
            && style.visibility !== 'hidden'
            && Number(style.opacity) > 0;
        });
        if (!images.every((img) => img.complete && img.naturalWidth > 0)) return false;
        await Promise.all(images.map((img) => img.decode()));
        return true;
      }, {timeout}, expectedUrl);
    } catch (error) {
      // Frame detachment is expected only when the page removed that actual iframe.
      if (await cardHandle.evaluate((iframe) => iframe.isConnected)) throw error;
    }
  }));

  const selectedViewer = await page.$('.thumb-card.selected-card[data-full-preview="1"]');
  const previewHandle = selectedViewer && await page.$('#main-frame');
  if (!previewHandle) return;
  const preview = await previewHandle.contentFrame();
  if (!preview) throw new Error('Selected plugin viewer has no loaded document');
  await preview.waitForFunction((url) => {
    if (document.readyState !== 'complete') return false;
    if (location.href === url) return true;
    // Download manifests use the shared native directory browser as their viewer.
    const files = new URL('files/', url);
    return location.origin === files.origin
      && location.pathname === files.pathname
      && new URL(location.href).searchParams.get('files') === '1'
      && Boolean(document.querySelector('.directory-list'));
  }, {timeout}, await previewHandle.evaluate((iframe) => iframe.src));
  for (const pdfHandle of await preview.$$('iframe')) {
    const visiblePdf = await pdfHandle.evaluate((iframe) => {
      const rect = iframe.getBoundingClientRect();
      return new URL(iframe.src, location.href).pathname.toLowerCase().endsWith('.pdf')
        && iframe.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
        && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
    });
    if (!visiblePdf) continue;
    const pdfFrame = await pdfHandle.contentFrame();
    if (!pdfFrame) throw new Error('Visible PDF preview has no loaded document');
    const viewer = await page.waitForFrame((frame) => frame.parentFrame() === pdfFrame
      && frame.url().startsWith('chrome-extension://'), {timeout});
    // The native viewer element exists before its PDF pages have rendered.
    await viewer.waitForFunction(() => {
      const pdf = document.querySelector('pdf-viewer');
      return pdf?.loadState_ === 'success' && pdf.initialLoadComplete_
        && pdf.documentDimensions?.pageDimensions?.length > 0;
    }, {timeout});
  }
}

async function liveProgressState(readyOnly = false, rejectedFrameUrl = '') {
  const visible = (element, inViewport = true) => {
    if (!element || !element.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    if (!inViewport) return true;
    const left = Math.max(0, rect.left);
    const right = Math.min(innerWidth, rect.right);
    const top = Math.max(0, rect.top);
    const bottom = Math.min(innerHeight, rect.bottom);
    return right > left && bottom > top
      && element.contains(document.elementFromPoint((left + right) / 2, (top + bottom) / 2));
  };
  const monitor = document.querySelector('#progress-monitor[data-progress-scope="snapshot"]');
  const panel = monitor?.querySelector('.screencast-panel.visible[data-mode="frame"]');
  const img = panel?.querySelector('.screencast-frame img');
  const src = img?.currentSrc || '';
  const snapshotId = monitor
    ? new URL(monitor.dataset.progressEndpoint, location.href).searchParams.get('snapshot_id')
    : '';
  const snapshot = [...(monitor?.querySelectorAll('.snapshot-item') || [])]
    .find((item) => item.dataset.snapshotId?.replaceAll('-', '') === snapshotId?.replaceAll('-', ''));
  const state = {
    url: location.href,
    title: document.title,
    progressMonitorVisible: visible(monitor),
    progressDetailsVisible: visible(monitor?.querySelector('.progress-content')),
    snapshotId,
    snapshotStarted: Boolean(snapshot?.querySelector('.status-badge.started')),
    runningExtractors: [...(snapshot?.querySelectorAll('.extractor-badge.started') || [])]
      .filter((element) => visible(element, false)).length,
    screencastVisible: visible(panel) && visible(img),
    screencastPlaceholderVisible: visible(monitor?.querySelector('.screencast-placeholder')),
    screencastImageLoaded: Boolean(img?.complete && img.naturalWidth > 0 && img.naturalHeight > 0),
    screencastImageSize: img ? `${img.naturalWidth}x${img.naturalHeight}` : '',
    screencastImageUrl: src,
  };
  state.ready = state.progressMonitorVisible && state.progressDetailsVisible
    && state.snapshotStarted && state.runningExtractors > 0
    && state.screencastVisible && !state.screencastPlaceholderVisible && state.screencastImageLoaded
    && /\/api\/v1\/core\/snapshot\/[^/]+\/screencast\.jpg$/.test(new URL(src || 'about:blank').pathname);
  if (!readyOnly) return state;
  if (!state.ready || src === rejectedFrameUrl) return false;
  try {
    await img.decode();
  } catch {
    return false;
  }
  return img.isConnected && img.currentSrc === src && visible(img) ? state : false;
}

async function waitForLiveProgress(page, deadline, screencastResponses) {
  let rejectedFrameUrl = '';
  try {
    while (Date.now() < deadline) {
      const handle = await page.waitForFunction(liveProgressState, {timeout: Math.max(1, deadline - Date.now()), polling: 100}, true, rejectedFrameUrl);
      const state = await handle.jsonValue();
      await handle.dispose();
      // Chrome's initial frame can be a fully decoded, solid black/white image.
      // Inspect the exact response displayed by the UI, without requesting a
      // newer latest.jpg or bypassing its normal authentication/CORS behavior.
      const response = screencastResponses.get(state.screencastImageUrl);
      if (!response) throw new Error('Displayed screencast has no observed image response');
      const imageData = `data:image/jpeg;base64,${(await response.buffer()).toString('base64')}`;
      const hasContent = await page.evaluate(async (data) => {
        const img = new Image();
        img.src = data;
        await img.decode();
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 64;
        const context = canvas.getContext('2d');
        // Ignore the outer edges: a site header alone can appear while the
        // actual page is still blank. Marketing captures need page content.
        context.drawImage(img, img.naturalWidth * 0.1, img.naturalHeight * 0.1,
          img.naturalWidth * 0.8, img.naturalHeight * 0.8, 0, 0, 64, 64);
        const pixels = context.getImageData(0, 0, 64, 64).data;
        // Check each channel separately: a solid colored frame is also blank.
        return [0, 1, 2].some((channel) => {
          let min = 255;
          let max = 0;
          for (let i = channel; i < pixels.length; i += 4) {
            min = Math.min(min, pixels[i]);
            max = Math.max(max, pixels[i]);
          }
          return max - min > 16;
        });
      }, imageData);
      if (hasContent) {
        const current = await page.evaluate(liveProgressState);
        if (current.ready && current.screencastImageUrl === state.screencastImageUrl) {
          return {...current, screencastImageHasContent: true};
        }
      } else {
        rejectedFrameUrl = state.screencastImageUrl;
      }
    }
    throw new Error('Live progress deadline expired');
  } catch (error) {
    const state = await page.evaluate(liveProgressState).catch(() => ({url: page.url()}));
    if (rejectedFrameUrl) state.rejectedBlankFrameUrl = rejectedFrameUrl;
    throw new Error(`Live progress with a decoded screencast frame was not visible within 60 seconds: ${JSON.stringify(state)}`, {cause: error});
  }
}

class NativePreviewAssertionError extends Error {}

async function takeScreenshot() {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    usage();
    return;
  }

  const url = argValue('--url') || firstPositionalArg(0) || DEFAULT_URL;
  const output = path.resolve(argValue('--output') || firstPositionalArg(1) || DEFAULT_OUTPUT);
  const width = Number(process.env.SCREENSHOT_WIDTH || 1600);
  const height = Number(process.env.SCREENSHOT_HEIGHT || 1400);
  const fullPage = process.env.SCREENSHOT_FULL_PAGE === '1';
  const requireLiveProgress = process.env.SCREENSHOT_REQUIRE_LIVE_PROGRESS === '1';
  // Include Chrome startup in the capture deadline. Starting a new 60s budget
  // after launch lets cold/contended browser startup exceed the caller's total
  // timeout before a missing screencast can produce its intended error.
  const liveProgressDeadline = Date.now() + 60000;
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
  const browser = await require('puppeteer').launch(launchOptions);
  let page;
  let exportDownloadDirectory;
  let exportDownload;
  if (process.env.SCREENSHOT_LIBRARY_MENU === 'export') {
    exportDownloadDirectory = fs.mkdtempSync(path.join(require('os').tmpdir(), 'archivebox-export-gallery-'));
    const downloads = await browser.target().createCDPSession();
    await downloads.send('Browser.setDownloadBehavior', {behavior: 'allowAndName', downloadPath: exportDownloadDirectory, eventsEnabled: true});
    exportDownload = new Promise((resolve, reject) => {
      downloads.once('Browser.downloadWillBegin', (started) => {
        const progress = (event) => {
          if (event.guid !== started.guid) return;
          if (event.state === 'completed' || event.state === 'canceled') {
            downloads.off('Browser.downloadProgress', progress);
            if (event.state === 'canceled') reject(new Error('The gallery export download was canceled.'));
            else resolve({format: 'wacz', bytes: fs.statSync(path.join(exportDownloadDirectory, event.guid)).size});
          }
        };
        downloads.on('Browser.downloadProgress', progress);
      });
    });
  }
  const documentRequests = new Map();
  const pageErrors = [];
  try {
    // Persistent persona profiles can restore tabs left by earlier launches.
    // Close them before navigating so repeated captures do not multiply live
    // admin requests and overwhelm the server being documented.
    const restoredPages = await browser.pages();
    page = await browser.newPage();
    page.on('error', (error) => pageErrors.push(error.name));
    await page.setCacheEnabled(false);
    await Promise.all(restoredPages.map((restoredPage) => restoredPage.close()));
    page.setDefaultTimeout(45000);
    const screencastResponses = new Map();
    if (requireLiveProgress) {
      page.on('response', (response) => {
        if (/\/api\/v1\/core\/snapshot\/[^/]+\/screencast\.jpg$/.test(new URL(response.url()).pathname) && response.ok()) {
          screencastResponses.set(response.url(), response);
        }
      });
    }

    const client = await page.createCDPSession();
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

    let navigationResponse = await page.goto(url, { waitUntil: 'load', timeout: 60000 });

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
    if (process.env.SCREENSHOT_REPLAY_URL) {
      const original = process.env.SCREENSHOT_REPLAY_URL;
      const replay = await page.waitForFrame(frame => frame.url().split('#')[0].endsWith('/' + original), {timeout: 45000});
      await replay.waitForFunction(() => document.readyState === 'complete' && (document.body?.innerText.length || 0) > 80, {timeout: 45000});
      if (await replay.evaluate(() => document.body.innerText.includes('Archived Page Not Found'))) {
        throw new Error(`Exported WACZ does not contain ${original}`);
      }
    }
    if (process.env.SCREENSHOT_WAIT_FOR_TEXT) {
      await page.waitForFunction((text) => document.body.innerText.includes(text), {}, process.env.SCREENSHOT_WAIT_FOR_TEXT);
    }
    if (process.env.SCREENSHOT_WAIT_SELECTOR) {
      await page.waitForSelector(process.env.SCREENSHOT_WAIT_SELECTOR, { timeout: 45000 });
    }
    if (process.env.SCREENSHOT_PREVIEW_WAIT_FOR_TEXT) {
      const previewHandle = await page.waitForSelector('#main-frame', {timeout: 45000});
      const preview = await previewHandle.contentFrame();
      if (!preview) throw new Error('Snapshot preview iframe has no document');
      try {
        await preview.waitForFunction(
          (text) => document.body?.innerText.includes(text),
          {timeout: 45000},
          process.env.SCREENSHOT_PREVIEW_WAIT_FOR_TEXT,
        );
      } catch (error) {
        if (error.name !== 'TimeoutError' || navigationResponse?.status() !== 200
          || page.url() !== new URL(url).href
          || !await page.$('.thumb-card.selected-card[data-plugin-name]')
          || !await preview.evaluate(() => document.readyState === 'complete' && Boolean(document.body))) throw error;
        throw new NativePreviewAssertionError('Selected plugin preview did not render its native proof text.');
      }
    }
    if (process.env.SCREENSHOT_CLICK_SELECTOR) {
      await page.waitForSelector(process.env.SCREENSHOT_CLICK_SELECTOR, { timeout: 45000 });
      const summaries = await page.evaluateHandle((selector) => {
        const closed = [];
        const target = document.querySelector(selector);
        for (let parent = target?.parentElement; parent; parent = parent.parentElement) {
          const summary = parent.tagName === 'DETAILS' && parent.querySelector(':scope > summary');
          if (summary && summary !== target && !parent.open) closed.unshift(summary);
        }
        return closed;
      }, process.env.SCREENSHOT_CLICK_SELECTOR);
      for (const handle of (await summaries.getProperties()).values()) {
        const summary = handle.asElement();
        if (summary) await summary.click();
        await handle.dispose();
      }
      await summaries.dispose();
      await page.click(process.env.SCREENSHOT_CLICK_SELECTOR);
    }
    if (process.env.SCREENSHOT_AFTER_CLICK_WAIT_SELECTOR) {
      await page.waitForSelector(process.env.SCREENSHOT_AFTER_CLICK_WAIT_SELECTOR, { timeout: 45000 });
    }

    if (requireLiveProgress) {
      await waitForLiveProgress(page, liveProgressDeadline, screencastResponses);
    } else {
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }

    // Selecting a hash opens its output stack after the saved header preference
    // is read. Apply the requested collapse through the real toggle afterwards.
    if (process.env.SCREENSHOT_SNAPSHOT_HEADER === 'collapsed') {
      const toggle = await page.$('.header-toggle[aria-expanded="true"]');
      if (toggle) await toggle.click();
    }

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
          outputPath: card.dataset.outputPath || '',
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

    const screenshotPaths = [];
    if (requireLiveProgress) checks.liveProgressCaptures = [];
    const capture = async (screenshotPath) => {
      if (process.env.SCREENSHOT_LIBRARY_MENU === 'export' && !await page.$('#export-notifications .success')) {
        await openFolderMenu(page);
        await page.click('.folder-menu:popover-open [data-export-format="wacz"]');
        await page.waitForSelector('#export-notifications [data-status="exited"],#export-notifications .error', {timeout:120000});
        if (await page.$('#export-notifications .error')) throw new Error('The gallery export failed.');
        if (await page.$('.folder-sidebar .snapshot-export-status,#result_list .snapshot-export-status')) throw new Error('Export notifications must not be embedded in the list.');
        checks.exportDownload = await exportDownload;
        if (!checks.exportDownload.bytes) throw new Error('The gallery export download is empty.');
      }
      if (process.env.SCREENSHOT_LIBRARY_MENU === 'view-export') await openViewExportMenu(page);
      if (process.env.SCREENSHOT_LIBRARY_MENU === 'smart') await openSmartFolder(page);
      if (process.env.SCREENSHOT_LIBRARY_MENU === 'search') await openFolderSearch(page);
      if (process.env.SCREENSHOT_LIBRARY_MENU === 'folder') await openFolderMenu(page);
      if (process.env.SCREENSHOT_LIBRARY_MENU === 'import') await openImportMenu(page);
      // Resizing can move the target to a different row/column. Re-anchor each
      // gallery variant so it photographs the requested controls at every width.
      if (process.env.SCREENSHOT_SCROLL_SELECTOR) {
        await page.waitForSelector(process.env.SCREENSHOT_SCROLL_SELECTOR, { timeout: 45000 }).catch(() => {});
        await page.evaluate((selector) => {
          document.querySelector(selector)?.scrollIntoView({ block: 'start', inline: 'nearest' });
        }, process.env.SCREENSHOT_SCROLL_SELECTOR);
      }
      await waitForVisibleCardPreviews(page, requireLiveProgress ? Math.max(1, liveProgressDeadline - Date.now()) : 45000);
      if (requireLiveProgress) {
        const liveProgress = await waitForLiveProgress(page, liveProgressDeadline, screencastResponses);
        checks.liveProgressCaptures.push({path: screenshotPath, viewport: page.viewport(), ...liveProgress});
      }
      const libraryAlignment = await page.evaluate(() => {
        const library = document.querySelector('.snapshot-library:not(.sidebar-hidden)');
        if (innerWidth < 768 || !library) return null;
        const rect = selector => library.querySelector(selector).getBoundingClientRect();
        // All Snapshots now shares one row with search and the sidebar toggle.
        // The compact toggle is smaller than search, but their centers must align.
        const header = rect('.folder-section-heading');
        const toolbar = rect('.public-snapshot-toolbar,#changelist #toolbar');
        const toggle = rect('.folder-mobile-toggle');
        const search = rect('#changelist-search .abx-query-control');
        const column = library.querySelector('#table-bookmarks thead th,#result_list thead th');
        const style = column && getComputedStyle(column);
        return {headerTop:header.top, toolbarTop:toolbar.top, headerBottom:header.bottom, toolbarBottom:toolbar.bottom, toggleCenter:toggle.top + toggle.height / 2, searchCenter:search.top + search.height / 2, borderTop:style?.borderTopWidth, borderBottom:style?.borderBottomWidth};
      });
      if (libraryAlignment && (Math.abs(libraryAlignment.headerTop - libraryAlignment.toolbarTop) > 0.5 || Math.abs(libraryAlignment.headerBottom - libraryAlignment.toolbarBottom) > 0.5 || Math.abs(libraryAlignment.toggleCenter - libraryAlignment.searchCenter) > 0.5 || (libraryAlignment.borderTop !== undefined && (libraryAlignment.borderTop !== '0px' || libraryAlignment.borderBottom !== '1px')))) {
        throw new Error(`Library controls are misaligned: ${JSON.stringify(libraryAlignment)}`);
      }
      if (process.env.SCREENSHOT_WAIT_FOR_MODEL === '1') {
        const state = await page.waitForFunction(() => {
          const canvas = document.querySelector('#model');
          if (canvas?.dataset.state === 'error') return 'error';
          return canvas?.dataset.state === 'ready' && Number(canvas.dataset.renderedTriangles) > 0 && canvas.clientWidth > 0 && canvas.clientHeight > 0;
        }, {timeout: 45000});
        const failed = await state.jsonValue() === 'error';
        await state.dispose();
        if (failed) {
          const message = 'Selected model preview reported a rendering error.';
          if (navigationResponse?.status() === 200 && page.url() === new URL(url).href) {
            throw new NativePreviewAssertionError(message);
          }
          throw new Error(message);
        }
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        checks.model = await page.$eval('#model', canvas => ({format: document.body.dataset.modelFormat, meshes: Number(canvas.dataset.meshes), triangles: Number(canvas.dataset.triangles), renderedTriangles: Number(canvas.dataset.renderedTriangles)}));
      }
      const captureFullPage = process.env.SCREENSHOT_FULL_PAGE ? fullPage : Boolean(await page.$('#plugin-settings'));
      if (captureFullPage) {
        await page.evaluate(() => window.scrollTo({top: 0, left: 0, behavior: 'instant'}));
        await page.waitForFunction(() => window.scrollX === 0 && window.scrollY === 0);
      }
      if (process.env.SCREENSHOT_REQUIRE_IN_FRAME_SELECTOR) {
        const selector = process.env.SCREENSHOT_REQUIRE_IN_FRAME_SELECTOR;
        await page.waitForSelector(selector, {visible: true, timeout: 45000});
        const inFrame = await page.$eval(selector, element => {
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 &&
            rect.top >= -1 && rect.left >= -1 &&
            rect.bottom <= innerHeight + 1 && rect.right <= innerWidth + 1;
        });
        if (!inFrame) throw new Error(`Screenshot control is outside the viewport: ${selector}`);
      }
      await page.screenshot({path: screenshotPath, fullPage: captureFullPage});
      screenshotPaths.push(screenshotPath);
    };
    if (variants.length) {
      for (const variant of variants) {
        const variantPath = path.resolve(variant.path);
        fs.mkdirSync(path.dirname(variantPath), { recursive: true });
        await page.setViewport({width: variant.width, height: variant.height, deviceScaleFactor: 1});
        await new Promise((resolve) => setTimeout(resolve, 300));
        await capture(variantPath);
      }
    } else {
      await capture(output);
    }
    console.log(JSON.stringify({ screenshotPath: screenshotPaths[0], screenshotPaths, checks }, null, 2));
  } catch (error) {
    if (process.env.SCREENSHOT_FAILURE_DIR) {
      // CI removes provider data after failure. Retain only URL paths and native
      // frame/request state, never persona data, request headers, or response bodies.
      const safeUrl = (value) => {
        try {
          const parsed = new URL(value);
          return ['http:', 'https:'].includes(parsed.protocol) ? `${parsed.origin}${parsed.pathname}` : parsed.protocol;
        } catch { return ''; }
      };
      const failureDir = path.resolve(process.env.SCREENSHOT_FAILURE_DIR);
      fs.mkdirSync(failureDir, {recursive: true});
      fs.writeFileSync(path.join(failureDir, `${path.basename(output)}.json`), JSON.stringify({
        error: error.name,
        pageErrors,
        url: safeUrl(page?.url()),
        frames: page?.frames().map((frame) => ({url: safeUrl(frame.url()), detached: frame.detached})),
        documents: [...documentRequests.values()].map((record) => ({
          ...record, url: safeUrl(record.url), responseUrl: safeUrl(record.responseUrl),
        })),
      }, null, 2));
    }
    throw error;
  } finally {
    await browser.close();
    if (exportDownloadDirectory) fs.rmSync(exportDownloadDirectory, {recursive: true, force: true});
  }
}

// Exercise the ordinary Django folder forms and bulk actions on real captures.
async function submit(page, selector) {
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click(selector)]);
  const errors = await page.$$eval('.errornote,.errorlist', nodes => nodes.map(node => node.textContent.trim()).join(' '));
  if (errors) throw new Error(errors);
}

async function prepareLibrary(page, adminBaseUrl, crawlId, librarySource) {
  const {homepage, title} = librarySource;
  if (!crawlId) throw new Error('A real captured crawl is required for the folder gallery.');
  async function loadFolderChildren(id) {
    const row = `.folder-row[data-folder-id="${id}"]`;
    await page.waitForSelector(row, {visible: true});
    const toggle = await page.$(`${row} .folder-toggle`);
    if (!toggle) return;
    if (await toggle.evaluate(button => button.getAttribute('aria-expanded') === 'false')) await toggle.click();
    await page.waitForFunction(selector => document.querySelector(selector)?.dataset.childrenLoaded === 'true', {}, row);
  }
  async function folder(name, parent = '') {
    await page.goto(`${adminBaseUrl}/admin/core/snapshot/`, {waitUntil: 'domcontentloaded'});
    if (await page.$('.folder-sidebar-reopen:not([hidden])')) await page.click('.folder-sidebar-reopen');
    if (parent) await loadFolderChildren(parent);
    const existing = await page.$$eval('.folder-row', (rows, name, parent) => rows.find(row => row.dataset.folderName === name && row.dataset.parentId === parent)?.dataset.folderId, name, parent);
    if (existing) return existing;
    if (parent) {
      const row = `.folder-row[data-folder-id="${parent}"]`;
      await page.hover(row);
      await page.click(`${row} .folder-menu-toggle`);
      await page.click(`${row} .folder-menu .folder-new:not([data-smart])`);
    } else {
      await page.goto(`${adminBaseUrl}/add/?${new URLSearchParams({url: homepage})}`, {waitUntil: 'domcontentloaded'});
      await page.click('.folder-field .folder-new');
    }
    await page.waitForSelector('#folder-dialog[open] .folder-save:not([disabled])');
    await page.type('#folder-name', name);
    if (await page.$eval('#folder-parent', select => select.value) !== parent) throw new Error('New folder dialog lost the selected parent.');
    const saved = page.waitForResponse(response => response.url().endsWith('/admin/core/folder/save/') && response.request().method() === 'POST');
    await page.click('.folder-save');
    const response = await saved;
    if (!response.ok()) throw new Error(`Creating the gallery folder failed: HTTP ${response.status()}`);
    const created = await response.json();
    await page.waitForSelector('#folder-dialog:not([open])');
    if (parent) await page.waitForSelector(`.folder-row[data-folder-id="${created.id}"][data-parent-id="${parent}"]`);
    if (!parent) {
      if (await page.$eval('#id_folder', select => select.value) !== String(created.id) || await page.$eval('#id_url', input => input.value) !== homepage) throw new Error('Creating a folder lost the Add form state.');
    }
    await page.goto(`${adminBaseUrl}/admin/core/snapshot/?folder=${encodeURIComponent(created.id)}`, {waitUntil: 'domcontentloaded'});
    const persisted = await page.$eval(
      `.folder-row[data-folder-id="${created.id}"]`,
      (row, folderName, parentId) => row.dataset.folderName === folderName && row.dataset.parentId === parentId
        && row.querySelector('.folder-link[aria-current="page"]') !== null,
      name, parent,
    );
    if (!persisted) throw new Error(`Folder was not saved: ${name}`);
    return created.id;
  }
  const parent = await folder(title);
  const child = await folder('Recent stories', parent);
  await page.goto(`${adminBaseUrl}/admin/core/snapshot/?crawl_id=${encodeURIComponent(crawlId)}`, {waitUntil: 'domcontentloaded'});
  await loadFolderChildren(parent);
  const rows = await page.$$('#result_list tbody tr');
  if (!rows.length) throw new Error('No real captures in the gallery crawl.');
  await page.click('#action-toggle');
  const source = await page.$('#result_list tbody tr .field-title_str');
  const target = await page.$(`.folder-row[data-folder-id="${child}"]`);
  const from = await source.boundingBox();
  const to = await target.boundingBox();
  if (!from || !to) throw new Error('The real drag source or destination is not visible.');
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, {steps: 15});
  // Chrome emits dragover on a subsequent move after dragenter.
  await page.mouse.move(to.x + to.width / 2 + 1, to.y + to.height / 2);
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.mouse.up()]);
  const message = await page.$eval('.messagelist', node => node.textContent);
  if (!message.includes(`Moved ${rows.length} snapshot(s)`)) throw new Error('Dragging the checked captures did not save their folder.');
  const result = {name: 'Nested snapshot folders', url: `${adminBaseUrl}/admin/core/snapshot/?folder=${parent}`, path: `/admin/core/snapshot/?folder=${parent}`, source: 'archivebox/core/admin_snapshots.py', addUrl: `${adminBaseUrl}/add/?${new URLSearchParams({folder: child, url: homepage})}`};
  await page.goto(result.url, {waitUntil: 'domcontentloaded'});
  await page.click('.library-mode-toggle');
  await page.waitForSelector('#library-mode-menu:popover-open');
  const domains = await page.$eval('#library-mode-menu a[data-sidebar-mode-link="domains"]', node => ({
    label: node.textContent.trim(),
    mode: new URL(node.href).searchParams.get('sidebar'),
  }));
  if (domains.label !== 'Domains' || domains.mode !== 'domains') throw new Error('The sidebar view menu omitted Domains.');
  await page.keyboard.press('Escape');
  if (!await page.$('.folder-sidebar a[aria-current="page"]')) throw new Error('Saved folder filter is not selected.');
  if (await page.$('.library-context,.library-breadcrumbs')) throw new Error('The removed folder header is still present.');
  if (!await page.$('#toolbar .folder-sidebar-reopen')) throw new Error('The folder restore control is outside the snapshot toolbar.');
  await page.click('.folder-mobile-toggle');
  await page.waitForSelector('.snapshot-library.sidebar-hidden');
  if (!await page.$eval('.folder-sidebar-reopen', button => !button.hidden && button.getAttribute('aria-expanded') === 'false' && document.activeElement === button)) throw new Error('Hidden desktop folders have no focused reopen control.');
  await page.reload({waitUntil: 'domcontentloaded'});
  await page.waitForSelector('.snapshot-library.sidebar-hidden');
  await page.goto(`${adminBaseUrl}/admin/core/snapshot/grid/?folder=${parent}`, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('.snapshot-library.sidebar-hidden');
  await page.click('.folder-sidebar-reopen');
  await page.waitForSelector('.snapshot-library:not(.sidebar-hidden)');
  if (!await page.$eval('.folder-mobile-toggle', button => button.getAttribute('aria-expanded') === 'true' && document.activeElement === button)) throw new Error('Restoring desktop folders lost keyboard focus.');
  await page.goto(result.url, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('.snapshot-library:not(.sidebar-hidden)');
  // Keep the real-capture gallery checking the flush sidebar at responsive sizes.
  const viewport = page.viewport();
  for (const [width, height] of [[1440, 1000], [1024, 768], [768, 1024], [390, 844], [320, 640]]) {
    await page.setViewport({width, height});
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    if (width < 768) {
      if (await page.$eval('.folder-current', node => node.textContent.trim()) !== title) throw new Error('The mobile folder bar lost the selected folder.');
      await page.click('.folder-mobile-toggle');
    }
    const layout = await page.evaluate(() => {
      const sidebar = document.querySelector('.folder-sidebar').getBoundingClientRect();
      const table = document.querySelector('#result_list').getBoundingClientRect();
      return {left: sidebar.left, bottom: sidebar.bottom, gap: table.left - sidebar.right, overflow: document.documentElement.scrollWidth > innerWidth};
    });
    if (layout.overflow || Math.abs(layout.left) > 1 || (width >= 768 && (Math.abs(layout.gap) > 1 || Math.abs(layout.bottom - height) > 1))) {
      throw new Error(`Folder layout at ${width}x${height}: ${JSON.stringify(layout)}`);
    }
    if (width < 768) await page.click('.folder-mobile-toggle');
  }
  await page.setViewport(viewport);
  await page.goto(result.addUrl, {waitUntil: 'domcontentloaded'});
  if (await page.$eval('#id_folder', select => select.value) !== child) throw new Error('The Add gallery did not select the nested folder.');
  await page.goto(result.url, {waitUntil: 'domcontentloaded'});
  return result;
}

// Derive exports from saved native filters; never create export records or keys.
async function prepareExports(page, adminBaseUrl, libraryUrl, homepage) {
  await page.goto(libraryUrl, {waitUntil: 'domcontentloaded'});
  const snapshotIds = await page.$$eval('#result_list input.action-select', nodes => nodes.map(node => node.value.replaceAll('-', '')));
  if (!snapshotIds.length) throw new Error('The export gallery folder has no real captures.');
  await page.click('#folder-sidebar button[popovertarget="snapshot-export-menu-sidebar"]');
  const urls = await page.$$eval('.folder-actions [data-export-format]', links => Object.fromEntries(links.map(link => [link.dataset.exportFormat, link.href])));
  await page.keyboard.press('Escape');
  for (const format of ['rss', 'csv', 'jsonl']) {
    // This anonymous gallery check uses the native public-only feed link.
    const linkFormat = format === 'rss' ? 'rss_public' : format;
    if (!urls[linkFormat]) throw new Error(`Missing native ${linkFormat} export link.`);
    const url = new URL(urls[linkFormat]);
    if (['api_key', 'token', 'password'].some(key => url.searchParams.has(key))) throw new Error('Generated export links must not contain credentials.');
    if (format === 'rss' && url.searchParams.get('public_only') !== '1') throw new Error('Public RSS export must preserve public-only visibility.');
    if (url.searchParams.get('folder') !== new URL(libraryUrl).searchParams.get('folder')) throw new Error('Export lost the selected folder.');
    const response = await page.evaluate(async url => { const response = await fetch(url, {credentials: 'omit'}); return {status: response.status, text: await response.text()}; }, url.href);
    if (response.status !== 200) throw new Error(`${format} export failed: ${response.status}`);
    if (format === 'rss') {
      const feed = await page.evaluate(text => {
        const xml = new DOMParser().parseFromString(text, 'application/xml');
        return {valid: !xml.querySelector('parsererror') && xml.documentElement.tagName === 'rss', ids: [...xml.querySelectorAll('channel > item > guid')].map(item => item.textContent.replaceAll('-', '')), descriptions: [...xml.querySelectorAll('channel > item > description')].map(item => item.textContent.split('\n'))};
      }, response.text);
      if (!feed.valid || !snapshotIds.every(id => feed.ids.includes(id))) throw new Error('RSS omitted actual displayed captures.');
      if (!feed.descriptions.some(lines => lines.some(line => line === `Original URL: ${homepage}`))) throw new Error('RSS omitted the selected library homepage.');
    } else {
      const records = format === 'jsonl'
        ? response.text.trim().split('\n').map(line => JSON.parse(line))
        : JSON.parse(require('node:child_process').execFileSync('uv', ['run', '--no-sync', '--project', path.resolve(__dirname, '..'), 'python', '-c', 'import csv, json, sys; print(json.dumps(list(csv.DictReader(sys.stdin))))'], {input: response.text, encoding: 'utf8'}));
      if (!snapshotIds.every(id => records.some(record => String(record.id).replaceAll('-', '') === id))) throw new Error(`${format} omitted actual displayed captures.`);
      if (!records.some(record => record.url === homepage)) throw new Error(`${format} omitted the selected library homepage.`);
    }
    url.searchParams.set('api_key', 'invalid-gallery-key');
    const invalidStatus = await page.evaluate(async url => (await fetch(url, {credentials: 'include'})).status, url.href);
    if (invalidStatus !== 401) throw new Error(`Invalid ${format} key inherited browser permissions: ${invalidStatus}`);
  }
  await page.goto(`${adminBaseUrl}/admin/importers/`, {waitUntil: 'domcontentloaded'});
  let sourceUrl = await page.$$eval('table a', links => links.find(link => link.textContent.trim() === 'Hacker News RSS')?.href);
  if (!sourceUrl) {
    await page.goto(`${adminBaseUrl}/admin/importers/new/importer_rss/feed/`, {waitUntil: 'domcontentloaded'});
    await page.type('#id_setting_IMPORTER_RSS_URL', 'https://news.ycombinator.com/rss');
    await page.click('details.advanced summary');
    await page.$eval('#id_name', node => { node.value = ''; });
    await page.type('#id_name', 'Hacker News RSS');
    await page.type('#id_schedule', 'daily');
    await submit(page, '.form-card button[type="submit"]');
    sourceUrl = page.url();
    if (!/\/admin\/importers\/[0-9a-f-]+\/$/.test(new URL(sourceUrl).pathname)) throw new Error('Native RSS importer was not saved.');
  }
  return [
    {name: 'Filtered snapshot exports', url: libraryUrl, path: new URL(libraryUrl).pathname + new URL(libraryUrl).search, source: 'archivebox/core/admin_snapshots.py'},
    {name: 'RSS importer settings', url: `${sourceUrl}edit/`, path: `${new URL(sourceUrl).pathname}edit/`, source: 'archivebox/importers/views.py'},
  ];
}

async function openFolderMenu(page) {
  if (await page.$('.folder-sidebar.is-collapsed')) await page.click('.folder-mobile-toggle');
  if (await page.$('.snapshot-library.sidebar-hidden')) await page.click('.folder-sidebar-reopen');
  const row = '.folder-row:has(.folder-link[aria-current="page"])';
  await page.waitForSelector(row);
  await page.hover(row);
  if (await page.$eval(`${row} .folder-menu-toggle`, node => node.getAttribute('aria-expanded')) !== 'true') await page.click(`${row} .folder-menu-toggle`);
  await page.waitForSelector(`${row} .folder-menu:popover-open`);
  await page.waitForFunction(row => document.querySelector(`${row} .folder-menu`).contains(document.activeElement), {}, row);
  const menu = await page.$eval(`${row} .folder-menu`, node => {
    const box = node.getBoundingClientRect();
    return {left:box.left,right:box.right,top:box.top,bottom:box.bottom,width:innerWidth,height:innerHeight,formats:[...node.querySelectorAll('[data-export-format]')].map(link=>link.dataset.exportFormat)};
  });
  if (menu.left < 0 || menu.top < 0 || menu.right > menu.width || menu.bottom > menu.height) throw new Error('Folder menu extends beyond the viewport.');
  const expected = await page.$$eval('.folder-actions [data-export-format]', links => links.map(link => link.dataset.exportFormat));
  if (expected.some(format => !menu.formats.includes(format))) throw new Error('Folder menu omitted a supported export format.');
}

async function openImportMenu(page) {
  if (await page.$('.snapshot-library.sidebar-hidden')) await page.click('.folder-sidebar-reopen');
  if (await page.$('.folder-mobile-toggle[aria-expanded="false"]')) await page.click('.folder-mobile-toggle');
  let id;
  for (const button of await page.$$('.library-import-toggle')) {
    if (!await button.boundingBox()) continue;
    id = await button.evaluate(node => node.getAttribute('popovertarget'));
    if (!await page.$(`#${id}:popover-open`)) await button.click();
    break;
  }
  if (!id) throw new Error('No visible Import button.');
  await page.waitForSelector(`#${id}:popover-open`);
  await page.waitForFunction(id => document.getElementById(id).contains(document.activeElement), {}, id);
  const menu = await page.$eval(`#${id}`, node => {
    const box = node.getBoundingClientRect();
    const items = [...node.querySelectorAll('.folder-menu-label')].map(label => {
      const item = label.closest('[role=menuitem],[role=group]');
      return {text:label.textContent.trim(),href:item.getAttribute('href'),hasIcon:!!item.querySelector('.folder-menu-icon')};
    });
    const mobileLinks = [...node.querySelectorAll('.library-import-icons a')].map(link => link.getAttribute('href'));
    const aiLinks = [...node.querySelectorAll('.library-import-links a')].map(link => link.getAttribute('href'));
    return {left:box.left,right:box.right,top:box.top,bottom:box.bottom,width:innerWidth,height:innerHeight,items,mobileLinks,aiLinks};
  });
  if (menu.left < 0 || menu.top < 0 || menu.right > menu.width || menu.bottom > menu.height) throw new Error('Import menu extends beyond the viewport.');
  const expected = [
    'Upload file', 'RSS Feed', 'From Social Media', 'Google Sheets',
    'Browser extension', 'From Mobile App', 'Via chat bot', 'Using AI', 'Via MITM proxy',
    'Pinboard', 'Instapaper', 'Reddit Saved Posts', 'Shaarli', 'Unmark.it', 'Wallabag',
    'Clone an entire site', 'Watch a site for changes',
  ];
  if (JSON.stringify(menu.items.map(item => item.text)) !== JSON.stringify(expected)) throw new Error('Import menu is missing a source.');
  if (menu.items.some(item => !item.hasIcon)) throw new Error('Import menu is missing an icon.');
  if (menu.items.find(item => item.text === 'RSS Feed').href !== '/admin/importers/new/importer_rss/feed/') throw new Error('RSS import does not open the feed form.');
  if (JSON.stringify(menu.mobileLinks) !== JSON.stringify(['https://app.archivebox.io/', 'https://android.archivebox.io/'])) throw new Error('Mobile app links are missing.');
  const expectedAiLinks = [
    '/admin/agent/',
    'https://github.com/ArchiveBox/ArchiveBox/tree/dev/archivebox/mcp',
    'https://www.skills.sh/archivebox/archivebox/archivebox',
  ];
  if (JSON.stringify(menu.aiLinks) !== JSON.stringify(expectedAiLinks)) throw new Error('AI links are missing.');
  if (menu.items.find(item => item.text === 'Clone an entire site').href !== '/admin/domains/') throw new Error('Site import does not open Domains.');
}

async function openFolderSearch(page) {
  if (await page.$('.snapshot-library.sidebar-hidden')) await page.click('.folder-sidebar-reopen');
  if (await page.$('.folder-mobile-toggle[aria-expanded="false"]')) await page.click('.folder-mobile-toggle');
  if (await page.$('#folder-search[hidden]')) {
    const height = await page.$eval('.folder-section-heading', node => node.getBoundingClientRect().height);
    await page.click('.folder-search-toggle');
    if (await page.$eval('.folder-section-heading', node => node.getBoundingClientRect().height) !== height) throw new Error('Folder search changed the heading height.');
    const name = await page.$eval('.folder-row', node => node.dataset.folderName);
    await page.type('#folder-search', name);
  }
  await page.waitForFunction(() => {
    const term = document.querySelector('#folder-search').value;
    return term && document.querySelector('.library-load-status').hidden &&
      [...document.querySelectorAll('.folder-row:not([hidden])')].some(row => row.dataset.folderName === term);
  });
  if (!await page.$eval('.folder-section-label', node => node.hidden)) throw new Error('Folder search did not replace its label.');
  const aligned = await page.evaluate(() => {
    const box = selector => document.querySelector(selector).getBoundingClientRect();
    const heading = box('.folder-section-heading');
    const root = document.querySelector('.folder-row[data-parent-id=""]:not([hidden])');
    const icon = [...root.querySelectorAll('.folder-toggle>svg,.folder-toggle>.folder-title-emoji,.folder-link>svg,.folder-link>.folder-title-emoji')].find(node => node.getClientRects().length);
    const rootIcon = icon.getBoundingClientRect(), rootText = root.querySelector('.folder-link>span:not(.folder-title-emoji)').getBoundingClientRect();
    const input = box('#folder-search'), toggle = box('.folder-search-toggle');
    return {
      left: input.x - rootIcon.x,
      labelCenter: rootIcon.y + rootIcon.height / 2 - rootText.y - rootText.height / 2,
      searchCenter: input.y + input.height / 2 - toggle.y - toggle.height / 2,
      mobileHeading: innerWidth >= 768 ? 0 : heading.top - box('.folder-sidebar').top,
    };
  });
  if (Object.values(aligned).some(offset => offset !== 0)) throw new Error(`Folder navigation icons, labels or search controls are misaligned: ${JSON.stringify(aligned)}`);
}

async function openViewExportMenu(page) {
  const buttons = await page.$$('.library-export-toggle');
  for (const button of buttons) {
    if (!await button.boundingBox()) continue;
    const id = await button.evaluate(node => node.getAttribute('popovertarget'));
    if (!await page.$(`#${id}:popover-open`)) await button.click();
    await page.waitForSelector(`#${id}:popover-open`);
    await page.waitForFunction(id => document.getElementById(id).contains(document.activeElement), {}, id);
    const state = await page.$eval(`#${id}`, node => {
      const rect = node.getBoundingClientRect();
      return {inside: rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight, formats: [...node.querySelectorAll('[data-export-format]')].map(link => link.dataset.exportFormat)};
    });
    if (!state.inside || !state.formats.includes('rss') || !state.formats.every(format => ['rss', 'rss_public', 'csv', 'jsonl', 'html_zip', 'wacz'].includes(format))) throw new Error('The current-view export menu is clipped or missing formats.');
    return;
  }
  throw new Error('No visible current-view Export button.');
}

// Create and reopen a smart folder using the ordinary rule editor and real captures.
async function prepareSmartFolder(page, adminBaseUrl, crawlId, source) {
  await page.goto(`${adminBaseUrl}/admin/core/snapshot/`, {waitUntil:'domcontentloaded'});
  if (await page.$('.folder-sidebar-reopen:not([hidden])')) await page.click('.folder-sidebar-reopen');
  const name = `📰 Saved ${source.title}`;
  let id = await page.$$eval('.folder-row', (rows,name) => rows.find(row => row.dataset.folderName === name)?.dataset.folderId, name);
  if (!id) {
    await page.click('.library-create-toggle');
    await page.click('#library-create-menu .folder-new[data-smart]');
    await page.waitForSelector('#folder-dialog[open] .folder-save:not([disabled])');
    await page.type('#folder-name',name);
    await page.click('.folder-advanced > summary');
    await page.click('.folder-rules > button');
    await page.select('.rule-condition select[aria-label="Field"]','domain');
    await page.select('.rule-condition select[aria-label="Comparison"]','iendswith');
    await page.type('.rule-condition input[aria-label="Value"]',new URL(source.homepage).hostname);
    const buttons = await page.$$('.rule-group-toolbar button');
    await buttons[0].click();
    await page.select('.rule-condition:nth-child(4) select[aria-label="Field"]','archiveresult__output_size');
    await page.select('.rule-condition:nth-child(4) select[aria-label="Comparison"]','gt');
    await page.type('.rule-condition:nth-child(4) input[aria-label="Amount"]','1');
    await page.select('.rule-condition:nth-child(4) select[aria-label="Unit"]','KB');
    const saved=page.waitForResponse(response => response.url().endsWith('/admin/core/folder/save/') && response.request().method()==='POST');
    await page.click('.folder-save');
    const response=await saved;
    if (!response.ok()) throw new Error(`Saving smart folder failed: HTTP ${response.status()} (${(await response.json()).error})`);
    const created=await response.json();
    await page.waitForSelector('#folder-dialog:not([open])');
    await page.waitForSelector(`.folder-row[data-folder-id="${created.id}"]`);
    id=await page.$$eval('.folder-row',(rows,name)=>rows.find(row=>row.dataset.folderName===name)?.dataset.folderId,name);
    if (!id) throw new Error('Saved smart folder is missing from the sidebar.');
  }
  const url=`${adminBaseUrl}/admin/core/snapshot/?${new URLSearchParams({folder:id,...(crawlId ? {crawl__id__exact:crawlId} : {})})}`;
  await page.goto(url,{waitUntil:'domcontentloaded'});
  if (!await page.$('#result_list input.action-select')) throw new Error('Smart folder omitted the selected native library rows.');
  const icon=await page.$eval(`.folder-row[data-folder-id="${id}"] .folder-title-emoji`,node => node.textContent);
  if (icon !== '📰') throw new Error('The title emoji did not replace the folder icon.');
  await openSmartFolder(page);
  const root='.folder-rules > .rule-group';
  const directConditions=await page.$$(`${root} > .rule-condition`);
  if (directConditions.length===2) {
    for (let index=0;index<2;index++) {
      const condition=await page.$(`${root} > .rule-condition`);
      await (await condition.$('[aria-label="Nest condition in group"]')).click();
      const added=`${root} > .rule-group:nth-child(${index===0 ? 2 : 4}) > .rule-condition:nth-child(4)`;
      await page.select(`${added} select[aria-label="Field"]`,'status');
      await page.select(`${added} select[aria-label="Value"]`,'queued');
      await page.select(`${added} select[aria-label="Condition polarity"]`,'not');
    }
    await page.select(`${root} > .rule-join select`,'OR');
    const saved=page.waitForResponse(response=>response.url().endsWith('/admin/core/folder/save/') && response.request().method()==='POST');
    await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.click('.folder-save')]);
    if (!(await saved).ok()) throw new Error('Saving nested smart-folder rules failed.');
  } else await page.click('.folder-dialog-heading .folder-dialog-close');
  return {name:'Smart folder',url,path:new URL(url).pathname+new URL(url).search,source:'archivebox/core/smart_folders.py'};
}

async function openSmartFolder(page) {
  if (await page.$('#folder-dialog[open]')) return;
  if (await page.$('.folder-sidebar.is-collapsed')) await page.click('.folder-mobile-toggle');
  if (await page.$('.folder-sidebar-reopen:not([hidden])')) await page.click('.folder-sidebar-reopen');
  const row=await page.$('.folder-row:has(.folder-link[aria-current="page"])');
  await row.hover();
  await (await row.$('.folder-menu-toggle')).click();
  await page.click('.folder-menu:popover-open .folder-edit');
  await page.waitForSelector('#folder-dialog.has-rules[open] .folder-save:not([disabled])');
  if (!await page.$('.folder-options select[aria-label="Sort by"] option[value="?"]') ||
      !await page.$('.folder-options input[aria-label="Limit"]:not([required])')) throw new Error('Smart-folder sort and optional limit controls are missing.');
  const values=await page.$$eval('.rule-condition select[aria-label="Field"]',nodes=>nodes.map(node=>node.value));
  if (!values.includes('domain') || !values.includes('archiveresult__output_size')) throw new Error('Reopening the smart folder lost its rules.');
  const checks=await page.evaluate(()=>({
    binary:[...document.querySelectorAll('.rule-group')].every(group=>{
      const count=group.querySelectorAll(':scope > .rule-group,:scope > .rule-condition').length;
      const toolbar=group.querySelector(':scope > .rule-group-toolbar');
      return count<=2 && (group.parentElement.matches('.folder-rules') ? toolbar?.querySelectorAll('button').length===2 : count<2 || !toolbar);
    }),
    choices:[...document.querySelectorAll('.rule-condition')].filter(row=>row.querySelector('[aria-label="Field"]').value==='status').every(row=>Boolean(row.querySelector('.rule-value select')) && !row.querySelector('.rule-value input')),
    heading:document.querySelector('#folder-dialog-title').textContent,
    footerNot:!!document.querySelector('.rule-negate')
  }));
  if (!checks.binary || !checks.choices || checks.footerNot || checks.heading!=='Edit smart folder rules') throw new Error(`Invalid smart-folder controls: ${JSON.stringify(checks)}`);

}

// Publish only the real news captures in the isolated gallery collection.

async function preparePublicLibrary(page, publicBaseUrl, libraryUrl) {
  if (!publicBaseUrl) throw new Error('The gallery requires its configured public URL.');
  await page.goto(libraryUrl, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('#result_list input.action-select');
  const snapshotIds = await page.$$eval('#result_list input.action-select', nodes => nodes.map(node => node.value.replaceAll('-', '')).sort());
  await page.click('#action-toggle');
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.select('.action-permissions-select', 'public')]);
  const message = await page.$eval('.messagelist', node => node.textContent);
  if (!message.includes('Set permissions to public')) throw new Error(`Publishing the gallery captures failed: ${message}`);
  const url = new URL('/public/', publicBaseUrl);
  url.search = new URL(libraryUrl).search;
  const context = await page.browser().createBrowserContext();
  try {
    const visitor = await context.newPage();
    const response = await visitor.goto(url.href, {waitUntil: 'domcontentloaded'});
    if (response.status() !== 200 || !await visitor.$('.folder-link[aria-current="page"]')) {
      const title = await visitor.title();
      if (response.status() === 500 && process.env.UI_LIBRARY_DATA_DIR) {
        // Read a bounded tail of the isolated gallery server log. Emit only
        // traceback frame locations and the exception class, never raw logs.
        let fd;
        try {
          fd = fs.openSync(path.join(process.env.UI_LIBRARY_DATA_DIR, 'ui-screenshot-server.log'), 'r');
          const stat = fs.fstatSync(fd);
          if (stat.isFile()) {
            const length = Math.min(stat.size, 1024 * 1024);
            const bytes = Buffer.alloc(length);
            const read = fs.readSync(fd, bytes, 0, length, stat.size - length);
            const log = bytes.subarray(0, read).toString('utf8');
            const request = log.lastIndexOf('Internal Server Error: /public/');
            const traceback = request < 0 ? -1 : log.lastIndexOf('Traceback (most recent call last):');
            if (traceback > request) {
              const lines = log.slice(traceback).split(/\r?\n/);
              const frames = [];
              let exception = '';
              for (const line of lines) {
                const frame = /^\s*File "([^"]+)", line (\d+), in ([\w.<>]+)\s*$/.exec(line);
                if (frame) {
                  const filename = path.basename(frame[1]);
                  if (/^[A-Za-z0-9_.-]+$/.test(filename)) frames.push(`${filename}:${frame[2]} in ${frame[3]}`);
                }
                const klass = /^([A-Za-z_][A-Za-z0-9_.]{0,127}(?:Error|Exception|Warning|DoesNotExist))(?::|$)/.exec(line);
                if (klass) exception = klass[1];
              }
              if (exception || frames.length) console.error(`Public folder traceback: ${exception || 'unknown exception'}${frames.length ? ` at ${frames.slice(-20).join(' <- ')}` : ''}`);
            }
          }
        } catch {
          console.error('Public folder traceback unavailable');
        } finally {
          if (fd !== undefined) fs.closeSync(fd);
        }
      }
      throw new Error(`Public folders did not render real captured pages: HTTP ${response.status()}, URL ${visitor.url()}, title ${title}`);
    }
    await visitor.waitForFunction(expected => {
      const ids = [...document.querySelectorAll('#table-bookmarks tbody .snapshot-title')].map(link => new URL(link.href).pathname.match(/\/([a-f0-9]{32})\/?$/)?.[1]).sort();
      return JSON.stringify(ids) === JSON.stringify(expected);
    }, {}, snapshotIds);
    if (await visitor.$('.folder-new,.folder-edit,.folder-drop-target,#folder-dialog')) throw new Error('Public folders exposed editing controls.');
  } finally {
    await context.close();
  }
  return {name: 'Public snapshot folders', url: url.href, path: '/public/', source: 'archivebox/templates/core/folder_sidebar.html', mode: 'public'};
}

// Run against the real logged-in gallery browser. The caller runs the ordinary
// worker after this submission, then photographs the native snapshot list.
async function prepareDomain(page, adminBaseUrl, homeUrl) {
  const nextUrl = new URL('chapter.html', homeUrl).href;
  const domain = new URL(homeUrl).host;
  await page.goto(`${adminBaseUrl}/admin/domains/`, {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('#siteclone-form');
  if (await page.$eval('#site-add-options', el => el.hidden)) await page.click('#site-add-button');
  async function fill(selector, text) {
    await page.focus(selector);
    await page.keyboard.press('End');
    await page.keyboard.down('Shift');
    await page.keyboard.press('Home');
    await page.keyboard.up('Shift');
    await page.keyboard.press('Backspace');
    await page.type(selector, text);
    if (await page.$eval(selector, input => input.value) !== text) {
      throw new Error(`Site clone field ${selector} was not entered correctly.`);
    }
  }
  await fill('#id_url', homeUrl);
  await fill('#id_max_depth', '1');
  await fill('#id_max_urls', '2');
  await fill('#id_concurrency', '2');
  await fill('#id_timeout_minutes', '30');
  await page.click('#siteclone-form .url-filter-patterns > summary');
  const escapeRegex = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  await fill('#id_url_filters_allowlist', `^(?:${[homeUrl, nextUrl].map(escapeRegex).join('|')})$`);
  for (const tag of ['replay-contract', 'site-clone', 'screenshot-gallery']) {
    await page.type('#id_tags_input', tag);
    await page.keyboard.press('Enter');
  }
  if (await page.$eval('#id_tags', input => input.value.split(',').sort().join(',')) !== 'replay-contract,screenshot-gallery,site-clone') {
    throw new Error('Native tag editor did not preserve the selected tags.');
  }
  // A backlink must not capture the same page twice.
  if (!await page.$eval('#id_url_filters_only_new', (input) => input.checked)) await page.click('#id_url_filters_only_new');
  const moreOptionsUrl = await page.$eval('#site-more-options', link => link.href);
  await Promise.all([
    page.waitForNavigation({waitUntil: 'domcontentloaded'}),
    page.click('#siteclone-form button[type="submit"]'),
  ]);
  const crawlId = new URL(page.url()).pathname.match(/^\/admin\/crawls\/crawl\/([a-f0-9-]{32,36})\/change\/$/)?.[1];
  if (!crawlId) {
    throw new Error(`Site-clone form did not save: ${await page.$eval('main', (main) => main.innerText)}`);
  }
  const url = `${adminBaseUrl}/admin/core/snapshot/?${new URLSearchParams({domain})}`;
  return {name: 'Domain snapshots', homeUrl, nextUrl, domain, url, moreOptionsUrl, path: new URL(url).pathname, crawlId, source: 'archivebox/templates/admin/core/snapshot/change_list.html'};
}

async function findDomainRow(page, adminUrl, originalUrl) {
  const domainsUrl = new URL('/admin/domains/', adminUrl).href;
  await page.goto(domainsUrl, {waitUntil: 'domcontentloaded'});
  if (page.url() !== domainsUrl) throw new Error('Domains redirected away from the gallery server.');
  await page.waitForSelector('#result_list');
  const selected = await page.evaluateHandle(url => {
    const original = new URL(url);
    const port = value => ['80', '443'].includes(value) ? '' : value;
    return [...document.querySelectorAll('#result_list tbody tr')].find(row => {
      const scope = row.querySelector('.domain-identity')?.dataset.filterValue;
      if (!scope) return false;
      const authority = new URL('http://' + scope.replace(/^\*\./, ''));
      return port(original.port) === port(authority.port) && (original.hostname === authority.hostname ||
        (scope.startsWith('*.') && original.hostname.endsWith('.' + authority.hostname)));
    });
  }, originalUrl);
  const row = selected.asElement();
  if (!row) throw new Error('The captured site is missing from Domains.');
  return row;
}

async function replayAuthUrl(page, snapshotsUrl, originalUrl) {
  await page.goto(snapshotsUrl, {waitUntil: 'domcontentloaded'});
  const snapshot = await page.$$eval('#result_list tbody tr', (rows, url) => {
    const original = new URL(url);
    const matched = rows.find(row => row.querySelector('.snapshot-original-url')?.href === original.href) ||
      rows.find(row => {
        const href = row.querySelector('.snapshot-original-url')?.href;
        return href && new URL(href).host === original.host;
      });
    return matched?.querySelector('input.action-select')?.value;
  }, originalUrl);
  if (!snapshot) throw new Error('The selected domain has no matching capture to replay.');
  const original = new URL(originalUrl);
  const auth = new URL('/admin/core/snapshot/replay-auth/', snapshotsUrl);
  auth.search = new URLSearchParams({snapshot, original_domain: original.hostname, next: original.pathname + original.search});
  return auth;
}

async function replayViews(page, clone) {
  const row = await findDomainRow(page, clone.url, clone.homeUrl);
  const snapshotsUrl = await row.$eval('.field-count a', link => link.href);
  const homeAuth = await replayAuthUrl(page, snapshotsUrl, clone.homeUrl);
  const response = await page.goto(homeAuth.href, {waitUntil: 'domcontentloaded'});
  if (!response || response.status() !== 200 || !new URL(page.url()).hostname.startsWith(new URL(clone.homeUrl).hostname + '.')) {
    throw new Error('Saved site did not load on its original-domain replay host.');
  }
  await assertCapturedPage(page, 'Field Notes');
  const next = await page.$eval('#chapter-link', link => link.href);
  if (!next || new URL(next).origin !== new URL(page.url()).origin) {
    const current = new URL(page.url());
    const link = next ? new URL(next) : null;
    throw new Error(`The saved chapter is not available for internal replay: ${JSON.stringify({
      page: current.origin + current.pathname,
      title: (await page.title()).slice(0, 160),
      next: link ? link.origin + link.pathname : null,
    })}`);
  }
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click(`a[href="${next}"]`)]);
  if (page.url() !== next) throw new Error('Captured internal-link navigation failed.');
  await assertCapturedPage(page, 'A Walk by the River');
  await page.goBack({waitUntil: 'domcontentloaded'});
  await assertCapturedPage(page, 'Field Notes');
  await page.goForward({waitUntil: 'domcontentloaded'});
  await assertCapturedPage(page, 'A Walk by the River');
  const nextAuth = new URL(homeAuth);
  nextAuth.searchParams.set('next', new URL(next).pathname + new URL(next).search);
  return [
    {name: 'Saved site replay', url: homeAuth.href, path: new URL(clone.homeUrl).pathname, source: 'archivebox/core/views.py'},
    {name: 'Captured internal link replay', url: nextAuth.href, path: new URL(clone.nextUrl).pathname, source: 'archivebox/core/views.py'},
  ];
}

// Assert captured text and subresources, not merely the replay frame's URL.
async function assertCapturedPage(frame, title) {
  await frame.waitForFunction(expected => {
    const image = document.querySelector('#notebook');
    return document.title === expected && document.querySelector('h1')?.textContent === expected &&
      document.querySelector('#description')?.textContent === (expected === 'Field Notes'
        ? 'Keep the pages, pictures, and paths that connect them.'
        : 'Willow branches leaned over the water as the afternoon light faded.') &&
      image?.complete && image.naturalWidth === 96 &&
      getComputedStyle(document.querySelector('#field-notes')).borderTopColor === 'rgb(47, 111, 78)';
  }, {}, title);
}

// Exports stay on the server filesystem. Exercise the selected-domains export,
// then open its actual output directly: the static export needs no replay server.
async function domainExportViews(page, clone, directory, baseUrl) {

  if (!baseUrl) throw new Error('The static gallery requires its localhost export server.');
  fs.mkdirSync(directory, {recursive: true});
  const row = await findDomainRow(page, clone.url, clone.homeUrl);
  await (await row.$('input.action-select')).click();
  const destinationPrompt = new Promise(resolve => page.once('dialog', async dialog => {
    await dialog.accept(directory);
    resolve();
  }));
  await Promise.all([
    page.select('.site-domain-export', 'html'),
    destinationPrompt,
  ]);
  await page.waitForFunction(() => ['exited', 'failed'].includes(document.querySelector('.snapshot-export-status')?.dataset.status), {timeout: 120000});
  const status = await page.$eval('.snapshot-export-status', element => ({...element.dataset}));
  if (new URL(page.url()).pathname !== '/admin/domains/') throw new Error('Export navigated away from Domains.');
  if (String(status.exitCode) !== '0') throw new Error('Static site export failed; inspect its process log.');
  const exported = status.exportPath;
  if (!path.isAbsolute(exported) || !fs.statSync(exported).isDirectory()) throw new Error('Export did not create its server directory.');
  if (!exported.startsWith(path.resolve(directory) + path.sep)) throw new Error('Export did not use the selected server directory.');
  const relative = path.relative(directory, exported);
  const root = new URL(`${relative.split(path.sep).map(encodeURIComponent).join('/')}/`, baseUrl);
  const index = new URL('index.html', root).href;
  const pages = JSON.parse(fs.readFileSync(path.join(exported, 'pages.json'), 'utf8'));
  const home = pages.find(item => item.url === clone.homeUrl);
  const next = pages.find(item => item.url === clone.nextUrl);
  if (!home || !next) throw new Error('The native export omitted captured site pages.');
  const homeUrl = new URL(home.path, root).href;
  const nextUrl = new URL(next.path, root).href;
  const snapshotId = home.path.split('/')[1];
  await page.goto(index, {waitUntil: 'domcontentloaded'});
  let snapshotLink;
  for (const link of await page.$$('a.snapshot-title')) {
    if (await link.evaluate((element, id) => new URL(element.href).pathname.endsWith(`/${id}/index.html`), snapshotId)) { snapshotLink = link; break; }
  }
  if (!snapshotLink) throw new Error('The native static index has no captured site detail link.');
  await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), snapshotLink.click()]);
  const detail = page.url();
  if (!detail.startsWith(root.href)) throw new Error('The native detail left the exported directory.');
  await page.click('.output-stack-html');
  let htmlCard;
  for (const card of await page.$$('.thumb-card[data-output-group="html"]')) {
    if (await card.evaluate((element, expected) => new URL(element.dataset.previewUrl, location.href).href === expected, homeUrl)) { htmlCard = card; break; }
  }
  if (!htmlCard) throw new Error('The native detail has no rewritten HTML output card.');
  const plugin = await htmlCard.evaluate(element => element.dataset.pluginName);
  // Click the native output link, not its download action or thumbnail iframe.
  await page.click(`.stack-tray .thumb-card[data-plugin-name="${plugin}"] h4`);
  const frame = await page.waitForFrame(frame => frame.name() === 'preview' && frame.url() === homeUrl);
  await assertCapturedPage(frame, 'Field Notes');
  const chapterLink = await frame.$('#chapter-link');
  if (!chapterLink || await chapterLink.evaluate(element => element.href) !== nextUrl) throw new Error('Static export did not rewrite the captured chapter link.');
  await chapterLink.click();
  const nextFrame = await page.waitForFrame(frame => frame.url() === nextUrl);
  await assertCapturedPage(nextFrame, 'A Walk by the River');
  await page.evaluate(() => history.back());
  await assertCapturedPage(await page.waitForFrame(frame => frame.url() === homeUrl), 'Field Notes');
  await page.evaluate(() => history.forward());
  await assertCapturedPage(await page.waitForFrame(frame => frame.url() === nextUrl), 'A Walk by the River');
  fs.writeFileSync(path.join(exported, 'gallery-navigation-proof.json'), JSON.stringify({index, detail, plugin, snapshotId, from: homeUrl, to: nextUrl}, null, 2) + '\n');
  return [
    {name: 'Static snapshot index', url: index, path: new URL(index).pathname, source: 'archivebox/core/querysets.py'},
    {name: 'Static snapshot detail', url: `${detail}#${plugin}`, path: new URL(detail).pathname, source: 'archivebox/templates/core/snapshot.html'},
    {name: 'Static site export', url: homeUrl, path: new URL(homeUrl).pathname, source: 'archivebox/domains/exports.py'},
    {name: 'Static export internal navigation', url: nextUrl, path: new URL(nextUrl).pathname, source: 'archivebox/domains/exports.py'},
  ];
}

// Gallery failure metadata only: never retain page text, credentials or URL queries.
function safeReplayUrl(value) {
  const url = URL.parse(value);
  if (!url || !['http:', 'https:'].includes(url.protocol)) return null;
  // Replay paths embed the original URL, including possible userinfo.
  const embedded = url.pathname.search(/https?:\/\//);
  const pathname = embedded < 0 ? url.pathname : url.pathname.slice(0, embedded) + (safeReplayUrl(url.pathname.slice(embedded)) || '[invalid]');
  return (url.origin + pathname).slice(0, 1024);
}

async function replayFailureDetails(frame, storyUrl, replayUrl, failures) {
  let timer;
  let state = {unavailable: true};
  if (frame) {
    try {
      state = await Promise.race([
        frame.evaluate(() => ({readyState: document.readyState, textLength: document.body?.innerText.length || 0})),
        new Promise(resolve => { timer = setTimeout(() => resolve({unavailable: true}), 1000); }),
      ]);
    } catch {
      // A detached/crashed frame must not hide the original replay assertion.
    } finally {
      clearTimeout(timer);
    }
  }
  return {story: safeReplayUrl(storyUrl), replay: safeReplayUrl(replayUrl), frame: frame ? safeReplayUrl(frame.url()) : null, ...state, failures};
}

// Use the real inline export controls, then browse unchanged recordings using the
// installed ReplayWeb.page player in a shared localhost gallery harness.
function matchesReplayUrl(frameUrl, playerUrl, originalUrl) {
  const replay = URL.parse(frameUrl);
  const prefix = new URL('replay/w/', playerUrl);
  if (!replay || replay.origin !== prefix.origin || !replay.pathname.startsWith(prefix.pathname)) return false;
  const embedded = replay.pathname.match(/\/(https?:\/\/.*)$/)?.[1];
  return Boolean(embedded) && URL.parse(embedded + replay.search + replay.hash)?.href === new URL(originalUrl).href;
}

async function downloadWacz(page, directory, trigger) {

  fs.mkdirSync(directory, {recursive: true});
  const downloadDirectory = fs.mkdtempSync(path.join(directory, 'wacz-download-'));
  const before = page.url();
  const cdp = await page.browser().target().createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', {behavior: 'allowAndName', downloadPath: downloadDirectory, eventsEnabled: true});
  let downloadUrl, downloadTimeout;
  const downloaded = new Promise((resolve, reject) => {
    downloadTimeout = setTimeout(() => reject(new Error('WACZ did not finish downloading.')), 120000);
    cdp.on('Browser.downloadWillBegin', event => { downloadUrl = event.url; });
    cdp.on('Browser.downloadProgress', event => {
      if (event.state === 'completed') { clearTimeout(downloadTimeout); resolve(path.join(downloadDirectory, event.guid)); }
      if (event.state === 'canceled') { clearTimeout(downloadTimeout); reject(new Error('WACZ download was canceled.')); }
    });
  });
  let file;
  try {
    [file] = await Promise.all([
      downloaded,
      (async () => {
        await trigger();
        await page.waitForFunction(() => ['exited', 'failed'].includes(document.querySelector('.snapshot-export-status')?.dataset.status), {timeout: 120000});
        const status = await page.$eval('.snapshot-export-status', element => ({...element.dataset}));
        if (status.exitCode !== '0') throw new Error('WACZ export failed; inspect its native Process log.');
        if (page.url() !== before) throw new Error('WACZ export navigated away from the selected view.');
      })(),
    ]);
  } finally {
    clearTimeout(downloadTimeout);
    await cdp.detach();
  }
  const expectedDownload = await page.$eval('[data-export-download]', link => link.href);
  if (downloadUrl !== expectedDownload || !fs.statSync(file).size) throw new Error('The browser did not download the selected WACZ.');
  return {file, downloadUrl};
}

async function replayHarness(page, exportedWacz, directory, baseUrl, adminUrl, originalUrl, snapshotsUrl) {

  if (!baseUrl) throw new Error('The WACZ gallery requires its localhost static server.');
  const playerDirectory = fs.mkdtempSync(path.join(directory, 'wacz-player-'));
  fs.mkdirSync(path.join(playerDirectory, 'replay'));
  if (!snapshotsUrl) {
    const row = await findDomainRow(page, adminUrl, originalUrl);
    snapshotsUrl = await row.$eval('.field-count a', link => link.href);
  }
  // Reuse the installed plugin's real assets through its existing isolated
  // snapshot route. This harness is gallery infrastructure, not an export mode.
  const auth = await replayAuthUrl(page, snapshotsUrl, originalUrl);
  auth.searchParams.delete('original_domain');
  auth.searchParams.set('next', '/replay/ui.js');
  const first = await page.goto(auth.href, {waitUntil: 'domcontentloaded'});
  if (!first || first.status() !== 200 || !new URL(first.url()).pathname.endsWith('/replay/ui.js')) throw new Error('Installed ReplayWeb.page assets are unavailable.');
  fs.writeFileSync(path.join(playerDirectory, 'replay/ui.js'), await first.buffer());
  for (const name of ['sw.js', 'sw-index.js', 'replay.html']) {
    const response = await page.goto(new URL(name, first.url()).href, {waitUntil: 'domcontentloaded'});
    if (!response || response.status() !== 200) throw new Error(`Installed ReplayWeb.page asset is unavailable: ${name}`);
    fs.writeFileSync(path.join(playerDirectory, 'replay', name), await response.buffer());
  }
  fs.copyFileSync(exportedWacz, path.join(playerDirectory, 'site.wacz'));
  const escape = value => value.replace(/[&<>"']/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[character]));
  fs.writeFileSync(path.join(playerDirectory, 'index.html'),
    '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">' +
    '<title>ReplayWeb.page</title><script src="replay/ui.js"></script>' +
    '<style>html,body{margin:0;height:100%}replay-web-page{display:block;height:100%}</style></head><body>' +
    `<replay-web-page source="./site.wacz" replaybase="./replay/" embed="default" deepLink url="${escape(originalUrl)}"></replay-web-page></body></html>`);
  const relative = path.relative(directory, playerDirectory);
  return {directory: playerDirectory, url: new URL(`${relative.split(path.sep).map(encodeURIComponent).join('/')}/index.html`, baseUrl).href};
}

async function exportPlayer(page, siteUrl, directory, baseUrl, originalUrl) {
  const row = await findDomainRow(page, siteUrl, originalUrl);
  const snapshotsUrl = await row.$eval('.field-count a', link => link.href);
  await row.hover();
  await (await row.$('.folder-menu-toggle')).click();
  const {file} = await downloadWacz(page, directory, () => page.click('#library-entry-menu:popover-open [data-export-format="wacz"]'));
  return replayHarness(page, file, directory, baseUrl, siteUrl, originalUrl, snapshotsUrl);
}

async function waczExportViews(page, clone, directory, baseUrl) {
  const {url} = await exportPlayer(page, clone.url, directory, baseUrl, clone.homeUrl);
  await page.goto(url, {waitUntil: 'domcontentloaded'});
  const frame = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, clone.homeUrl), {timeout: 45000});
  await assertCapturedPage(frame, 'Field Notes');
  await frame.click('#chapter-link');
  const next = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, clone.nextUrl), {timeout: 45000});
  await assertCapturedPage(next, 'A Walk by the River');
  await page.waitForFunction(target => new URLSearchParams(location.hash.slice(1)).get('url') === target, {}, clone.nextUrl);
  const nextPlayerUrl = page.url();
  await page.evaluate(() => history.back());
  await assertCapturedPage(await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, clone.homeUrl)), 'Field Notes');
  await page.evaluate(() => history.forward());
  await assertCapturedPage(await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, clone.nextUrl)), 'A Walk by the River');
  return [
    {name: 'WACZ site export', url, path: new URL(url).pathname, source: 'archivebox/domains/wacz.py', mode: `wait-replay-url:${clone.homeUrl}`},
    {name: 'WACZ export internal navigation', url: nextPlayerUrl, path: new URL(url).pathname, source: 'archivebox/domains/exports.py', mode: `wait-replay-url:${clone.nextUrl}`},
  ];
}

async function storyView(page, adminBaseUrl, storyUrl, directory, baseUrl, replayUrl = storyUrl) {
  const {url} = await exportPlayer(page, adminBaseUrl, directory, baseUrl, storyUrl);
  const story = `${url}#${new URLSearchParams({url: storyUrl})}`;
  await page.goto(story, {waitUntil: 'domcontentloaded'});
  const frame = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, replayUrl), {timeout: 45000}).catch(cause => {
    throw new Error(`WACZ story export did not open the recorded frame for ${new URL(storyUrl).hostname}.`, {cause});
  });
  await frame.waitForFunction(() => document.readyState === 'complete' && (document.body?.innerText.length || 0) > 80, {timeout: 45000});
  if (await frame.evaluate(() => document.body.innerText.includes('Archived Page Not Found'))) throw new Error('The archived story is missing from the WACZ export.');
  await page.waitForFunction(story => new URLSearchParams(location.hash.slice(1)).get('url') === story, {}, replayUrl);
  return {name: 'WACZ archived story', url: story, path: new URL(url).pathname, source: 'archivebox/domains/exports.py', mode: `wait-replay-url:${replayUrl}`};
}

async function folderViews(page, libraryUrl, source, directory, baseUrl) {
  const {homepage: originHomepage, stories, replay_urls: replayUrls, homepage_selector: homepageSelector} = source;
  const replayHomepage = replayUrls[originHomepage] || originHomepage;

  const {createHash} = require('crypto');
  const digest = async file => {
    const hash = createHash('sha256');
    for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
    return hash.digest('hex');
  };
  await page.goto(libraryUrl, {waitUntil: 'domcontentloaded'});
  if (page.url() !== libraryUrl) throw new Error('Folder redirected away from the selected gallery view.');
  await openFolderMenu(page);
  const link = '.folder-row:has(.folder-link[aria-current="page"]) .folder-menu [data-export-format="wacz"]';
  const exportUrl = await page.$eval(link, link => link.href);
  if (new URL(exportUrl).searchParams.get('folder') !== new URL(libraryUrl).searchParams.get('folder')) {
    throw new Error('The WACZ export lost the selected folder.');
  }
  const {file: exportedWacz, downloadUrl} = await downloadWacz(page, directory, () => page.click(link));
  const sourceDigest = await digest(exportedWacz);
  const {url, directory: playerDirectory} = await replayHarness(page, exportedWacz, directory, baseUrl, libraryUrl, originHomepage);
  const playerWacz = path.join(playerDirectory, 'site.wacz');
  if (await digest(playerWacz) !== sourceDigest) throw new Error('The player must use the exact standalone folder WACZ bytes.');

  const homepage = `${url}#${new URLSearchParams({url: originHomepage})}`;
  await page.goto(homepage, {waitUntil: 'domcontentloaded'});
  const frame = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, replayHomepage), {timeout: 45000}).catch(cause => {
    throw new Error('Folder WACZ export did not open its recorded homepage frame.', {cause});
  });
  await frame.waitForSelector(homepageSelector, {timeout: 45000});
  let storyLink, storyUrl;
  for (const anchor of await frame.$$('a[href]')) {
    const href = await anchor.evaluate(element => element.href);
    const story = stories.find(candidate => new URL(candidate).href === href && new URL(candidate).hostname !== new URL(originHomepage).hostname);
    if (story) { storyLink = anchor; storyUrl = story; break; }
  }
  if (!storyLink) throw new Error('The folder WACZ has no homepage link to a story in the selected recording.');
  const replayUrl = replayUrls[storyUrl] || storyUrl;
  const failures = [];
  const recordFailure = (request, status) => {
    if (failures.length >= 10) return;
    const requestUrl = URL.parse(request.url());
    const prefix = new URL('replay/w/', url);
    if (requestUrl?.origin === prefix.origin && requestUrl.pathname.startsWith(prefix.pathname)) {
      failures.push({url: safeReplayUrl(request.url()), status});
    }
  };
  const onFailed = request => recordFailure(request, 'requestfailed');
  const onResponse = response => { if (response.status() >= 400) recordFailure(response.request(), response.status()); };
  page.on('requestfailed', onFailed);
  page.on('response', onResponse);
  let next;
  try {
    await storyLink.click();
    next = await page.waitForFrame(frame => matchesReplayUrl(frame.url(), url, replayUrl), {timeout: 45000}).catch(cause => {
      throw new Error(`Folder WACZ export did not follow its recorded story link to ${new URL(storyUrl).hostname}.`, {cause});
    });
    await next.waitForFunction(() => document.readyState === 'complete' && (document.body?.innerText.length || 0) > 80, {timeout: 45000});
  } catch (cause) {
    try {
      console.error('Folder WACZ linked-story failure:', JSON.stringify(await replayFailureDetails(next, storyUrl, replayUrl, failures)));
    } catch {
      console.error('Folder WACZ linked-story diagnostics unavailable.');
    }
    throw cause;
  } finally {
    page.off('requestfailed', onFailed);
    page.off('response', onResponse);
  }
  const text = await next.evaluate(() => document.body.innerText);
  if (text.includes('Archived Page Not Found')) throw new Error('The linked story is missing from the selected folder WACZ.');
  await page.waitForFunction(story => new URLSearchParams(location.hash.slice(1)).get('url') === story, {}, replayUrl);
  if (await digest(exportedWacz) !== sourceDigest || await digest(playerWacz) !== sourceDigest) {
    throw new Error('Browsing changed the exported folder WACZ bytes.');
  }
  fs.writeFileSync(path.join(playerDirectory, 'folder-wacz-proof.json'), JSON.stringify({
    selection: libraryUrl, exportUrl, downloadUrl, source: exportedWacz, player: playerWacz,
    sha256: sourceDigest, bytes: fs.statSync(exportedWacz).size,
    from: originHomepage, to: storyUrl, replayUrl, frame: next.url(),
  }, null, 2) + '\n');
  return [
    {name: 'Export notification', url: libraryUrl, path: new URL(libraryUrl).pathname, source: 'archivebox/templates/static/exports.js', mode: 'export-notification'},
    {name: 'Folder WACZ homepage', url: homepage, path: new URL(url).pathname, source: 'archivebox/domains/wacz.py', mode: `wait-replay-url:${replayHomepage}`},
    {name: 'Folder WACZ story navigation', url: page.url(), path: new URL(url).pathname, source: 'archivebox/domains/wacz.py', mode: `wait-replay-url:${replayUrl}`},
  ];
}

async function submitAdminAdd(page, url, configure) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  if (!page.url().includes('/add/')) return false;
  await configure();
  const saveButton = 'button[name="_save"], input[name="_save"]';
  await page.waitForSelector(saveButton, { visible: true, timeout: 10000 });
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 60000 }),
    page.click(saveButton),
  ]);
  if (page.url().includes('/add/')) {
    const errors = await page.$$eval('.errornote, .errorlist', (nodes) => nodes.map((node) => node.textContent.trim()).join(' '));
    throw new Error(`admin setup form failed at ${page.url()}: ${errors || 'no form error shown'}`);
  }
  return true;
}

async function selectUser(page, username) {
  const selector = '#id_created_by';
  if (!(await page.$(selector))) return;
  const value = await page.$eval(selector, (select, wanted) => {
    const option = [...select.options].find((candidate) => candidate.textContent.trim() === wanted);
    return option ? option.value : '';
  }, username);
  if (value) await page.select(selector, value);
}

async function collapseAdminFilters(page, adminBaseUrl) {
  await page.goto(`${adminBaseUrl}/admin/core/snapshot/`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  const toggle = await page.$('#changelist-filter-toggle');
  if (!toggle) throw new Error('snapshot filter control is missing');
  const expanded = await page.$eval('#changelist-filter-toggle', (button) => button.getAttribute('aria-expanded') === 'true');
  if (expanded) {
    await page.click('#changelist-filter-toggle');
    await page.waitForFunction(() => document.body.classList.contains('filters-collapsed'));
  }
}

async function setupGallery(adminBaseUrl, username, phase) {
  if (!['prepare', 'replay'].includes(phase)) throw new Error('Gallery requires prepare or replay phase');
  if (!adminBaseUrl || !username || !process.env.SCREENSHOT_USER_DATA_DIR) {
    throw new Error('usage: screenshot_gallery_helpers.js setup ADMIN_BASE_URL USERNAME prepare|replay (with SCREENSHOT_USER_DATA_DIR)');
  }
  const launchOptions = {
    headless: true,
    userDataDir: path.resolve(process.env.SCREENSHOT_USER_DATA_DIR),
    defaultViewport: {
      width: Number(process.env.SCREENSHOT_WIDTH || 1600),
      height: Number(process.env.SCREENSHOT_HEIGHT || 1000),
    },
    protocolTimeout: 300000,
    args: [],
  };
  if (needsNoSandbox()) {
    addLaunchArg(launchOptions.args, '--no-sandbox');
    addLaunchArg(launchOptions.args, '--disable-setuid-sandbox');
  }
  const executablePath = process.env.CHROME_BINARY || process.env.PUPPETEER_EXECUTABLE_PATH;
  if (executablePath && fs.existsSync(executablePath)) launchOptions.executablePath = executablePath;

  const browser = await require('puppeteer').launch(launchOptions);
  try {
    const page = await browser.newPage();
    await page.goto(`${adminBaseUrl}/admin/`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    if (page.url().includes('/admin/login/')) throw new Error('screenshot persona is not logged in');

    if (phase === 'prepare' && process.env.CREATE_API_TOKEN === '1') {
      await submitAdminAdd(page, `${adminBaseUrl}/admin/api/apitoken/add/`, async () => {
        await selectUser(page, username);
      });
    }

    const repoDir = path.resolve(__dirname, '..');
    const dataDir = process.env.UI_LIBRARY_DATA_DIR;
    const viewsFile = process.env.UI_LIBRARY_VIEWS_FILE;
    if (!dataDir || !viewsFile || !process.env.UI_LIBRARY_CRAWL_ID) {
      throw new Error('Gallery features require a real captured library crawl and an isolated data directory.');
    }
    const source = JSON.parse(fs.readFileSync(path.join(path.dirname(viewsFile), 'gallery-library-source.json'), 'utf8'));
    if (source.crawl_id !== process.env.UI_LIBRARY_CRAWL_ID || !source.homepage || !source.homepage_selector || !source.title || !Array.isArray(source.stories) || source.stories.length !== 3) {
      throw new Error('Gallery library replay metadata does not match the prepared crawl.');
    }
    const runWorker = (args, fixtureEnv = {}) => {
      const result = spawnSync('uv', ['run', '--no-sync', '--project', repoDir, 'archivebox', ...args], {
        cwd: dataDir, encoding: 'utf8', env: {...process.env, PYTHONPATH: [__dirname, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter), ...fixtureEnv}, stdio: ['ignore', 'inherit', 'inherit'],
      });
      if (result.status !== 0) throw new Error(`Gallery worker failed: ${result.error?.message || `exit ${result.status}, signal ${result.signal || 'none'}`}`);
    };
    const checkpoint = `${viewsFile}.prepared.json`;
    if (phase === 'prepare') {
      const featureViews = [];
      const library = await prepareLibrary(page, adminBaseUrl, process.env.UI_LIBRARY_CRAWL_ID, source);
      featureViews.push(library);
      featureViews.push({...library, name: 'Navigation tools menu', source: 'archivebox/templates/core/navigation.html', mode: 'navbar-tools'});
      featureViews.push({...library, name: 'Navigation account menu', source: 'archivebox/templates/core/navigation.html', mode: 'navbar-account'});
      const smart = await prepareSmartFolder(page, adminBaseUrl, process.env.UI_LIBRARY_CRAWL_ID, source);
      featureViews.push(smart, {...smart, name: 'Smart folder rule editor', mode: 'smart-folder'});
      featureViews.push({...library, name: 'Current view export menu', mode: 'view-export-menu'});
      featureViews.push({...library, name: 'Folder search', mode: 'folder-search'});
      featureViews.push({...library, name: 'Folder export menu', mode: 'folder-menu'});
      featureViews.push({...library, name: 'Import sources menu', mode: 'import-menu'});
      featureViews.push(await preparePublicLibrary(page, process.env.UI_LIBRARY_PUBLIC_URL, library.url));
      featureViews.push({name: 'Add snapshots to a folder', url: library.addUrl, path: '/add/', source: 'archivebox/templates/core/add.html'});
      featureViews.push({name: 'Nested folders in grid view', url: library.url.replace('/snapshot/?', '/snapshot/grid/?'), path: '/admin/core/snapshot/grid/', source: 'archivebox/templates/admin/core/snapshot/change_list.html'});
      featureViews.push(...await prepareExports(page, adminBaseUrl, library.url, source.homepage));
      // Mandatory same-origin replay navigation uses an owned two-page site.
      // The selected folder has its own independently verified recordings.
      const siteDirectory = path.join(path.dirname(viewsFile), 'site-exports', 'site-navigation');
      fs.cpSync(path.join(repoDir, 'archivebox/tests/fixtures/site-navigation'), siteDirectory, {recursive: true});
      const siteUrl = new URL('site-navigation/index.html', process.env.UI_SITE_EXPORT_BASE_URL).href;
      const clone = await prepareDomain(page, adminBaseUrl, siteUrl);
      runWorker(['run', '--crawl-id', clone.crawlId]);
      if (process.env.UI_SCREENSHOT_UNAVAILABLE_OUT) {
        runWorker(['manage', 'shell', '--no-imports', '-c',
          'import os; from screenshot_gallery_helpers import prepare_site_navigation; prepare_site_navigation(os.environ["UI_GALLERY_CLONE_ID"], os.environ["UI_GALLERY_CLONE_FIXTURE"])',
        ], {UI_GALLERY_CLONE_ID: clone.crawlId, UI_GALLERY_CLONE_FIXTURE: siteDirectory});
      }
      featureViews.push({name: 'Domain capture options', url: clone.moreOptionsUrl, path: '/add/', source: 'archivebox/templates/core/add.html'});
      featureViews.push({name: 'Domains', url: `${adminBaseUrl}/admin/domains/`, path: '/admin/domains/', source: 'archivebox/domains/views.py'}, {name: 'Add domain', url: `${adminBaseUrl}/admin/domains/?add=1`, path: '/admin/domains/?add=1', source: 'archivebox/domains/templates/domains/index.html'}, clone);
      // The folder export and its linked-story navigation use owned recordings.
      // Keep the native HN captures and standalone story replay independent.
      const folderReplayFile = `${viewsFile}.folder-replay.json`;
      runWorker(['manage', 'shell', '--no-imports', '-c',
        'import json, os; from pathlib import Path; from screenshot_gallery_helpers import prepare_folder; Path(os.environ["UI_GALLERY_FOLDER_REPLAY"]).write_text(json.dumps(prepare_folder()))',
      ], {UI_GALLERY_FOLDER_REPLAY: folderReplayFile});
      const folderReplay = JSON.parse(fs.readFileSync(folderReplayFile, 'utf8'));
      fs.writeFileSync(checkpoint, JSON.stringify({adminBaseUrl, crawlId: process.env.UI_LIBRARY_CRAWL_ID, profile: path.resolve(process.env.SCREENSHOT_USER_DATA_DIR), featureViews, clone, folderReplay}));
      return;
    }
    // Reopen the same authenticated persona after the fixture owner starts a
    // fresh server. Never retry a stale page or weaken actual replay/export checks.
    const prepared = JSON.parse(fs.readFileSync(checkpoint, 'utf8'));
    if (prepared.adminBaseUrl !== adminBaseUrl || prepared.crawlId !== process.env.UI_LIBRARY_CRAWL_ID || prepared.profile !== path.resolve(process.env.SCREENSHOT_USER_DATA_DIR)) {
      throw new Error('Gallery preparation belongs to a different server, crawl, or persona');
    }
    const {featureViews, clone, folderReplay} = prepared;
    featureViews.push(...await replayViews(page, clone));
    featureViews.push(...await domainExportViews(page, clone, path.join(path.dirname(viewsFile), 'site-exports'), process.env.UI_SITE_EXPORT_BASE_URL));
    featureViews.push(...await waczExportViews(page, clone, path.join(path.dirname(viewsFile), 'site-exports'), process.env.UI_SITE_EXPORT_BASE_URL));
    const exportDirectory = path.join(path.dirname(viewsFile), 'site-exports');
    const folderReplayUrl = `${adminBaseUrl}/admin/core/snapshot/?${new URLSearchParams({folder: folderReplay.folder_id})}`;
    featureViews.push(...await folderViews(page, folderReplayUrl, folderReplay, exportDirectory, process.env.UI_SITE_EXPORT_BASE_URL));
    const story = source.stories[0];
    featureViews.push(await storyView(page, adminBaseUrl, story, exportDirectory, process.env.UI_SITE_EXPORT_BASE_URL, source.replay_urls[story]));
    fs.writeFileSync(viewsFile, featureViews.map(view => [view.name, view.url, view.path, view.source, view.mode || ''].join('|')).join('\n') + '\n');
    await collapseAdminFilters(page, adminBaseUrl);
  } finally {
    await browser.close();
  }
}

if (require.main === module) {
  const command = process.argv[2] === 'setup' ? setupGallery(...process.argv.slice(3)) : takeScreenshot();
  command.catch((err) => {
    console.error(err);
    process.exitCode = err instanceof NativePreviewAssertionError ? 42 : 1;
  });
}

module.exports = {
  waitForVisibleCardPreviews, prepareLibrary, prepareSmartFolder,
  prepareDomain, replayViews, domainExportViews, waczExportViews, safeReplayUrl, replayFailureDetails,
};
