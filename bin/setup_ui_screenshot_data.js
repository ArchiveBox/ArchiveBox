#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
const {spawnSync} = require('child_process');

const [adminBaseUrl, username] = process.argv.slice(2);
if (!adminBaseUrl || !username || !process.env.SCREENSHOT_USER_DATA_DIR) {
  throw new Error('usage: setup_ui_screenshot_data.js ADMIN_BASE_URL USERNAME (with SCREENSHOT_USER_DATA_DIR)');
}

function chromePath() {
  const configured = process.env.CHROME_BINARY || process.env.PUPPETEER_EXECUTABLE_PATH;
  return configured && fs.existsSync(configured) ? configured : undefined;
}

function needsNoSandbox() {
  return process.platform === 'linux' && !String(process.env.DISPLAY || '').trim();
}

function addLaunchArg(args, arg) {
  if (!args.includes(arg)) args.push(arg);
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

async function selectUser(page) {
  const selector = '#id_created_by';
  if (!(await page.$(selector))) return;
  const value = await page.$eval(selector, (select, wanted) => {
    const option = [...select.options].find((candidate) => candidate.textContent.trim() === wanted);
    return option ? option.value : '';
  }, username);
  if (value) await page.select(selector, value);
}

async function selectFirstRealOption(page, selector) {
  if (!(await page.$(selector))) return;
  const value = await page.$eval(selector, (select) => {
    const option = [...select.options].find((candidate) => candidate.value);
    return option ? option.value : '';
  });
  if (value) await page.select(selector, value);
}

async function replaceText(page, selector, value) {
  if (!(await page.$(selector))) return;
  await page.click(selector);
  const modifier = process.platform === 'darwin' ? 'Meta' : 'Control';
  await page.keyboard.down(modifier);
  await page.keyboard.press('KeyA');
  await page.keyboard.up(modifier);
  await page.type(selector, value);
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

async function main() {
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
  const executablePath = chromePath();
  if (executablePath) launchOptions.executablePath = executablePath;

  const browser = await puppeteer.launch(launchOptions);
  try {
    const page = await browser.newPage();
    await page.goto(`${adminBaseUrl}/admin/`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    if (page.url().includes('/admin/login/')) throw new Error('screenshot persona is not logged in');

    if (process.env.CREATE_API_TOKEN === '1') {
      await submitAdminAdd(page, `${adminBaseUrl}/admin/api/apitoken/add/`, async () => {
        await selectUser(page);
      });
    }

    if (process.env.CREATE_WEBHOOK === '1') await submitAdminAdd(page, `${adminBaseUrl}/admin/api/outboundwebhook/add/`, async () => {
      await replaceText(page, '#id_name', 'Snapshot completion notifications');
      await selectFirstRealOption(page, '#id_signal');
      await selectFirstRealOption(page, '#id_ref');
      await replaceText(page, '#id_endpoint', 'https://httpbin.org/post');
      if (await page.$('#id_enabled')) {
        const enabled = await page.$eval('#id_enabled', (input) => input.checked);
        if (!enabled) await page.click('#id_enabled');
      }
      await selectUser(page);
    });

    const repoDir = path.resolve(__dirname, '..');
    const dataDir = process.env.UI_LIBRARY_DATA_DIR;
    const viewsFile = process.env.UI_LIBRARY_VIEWS_FILE;
    if (!dataDir || !viewsFile || !process.env.UI_LIBRARY_CRAWL_ID) {
      throw new Error('Gallery features require a real captured library crawl and an isolated data directory.');
    }
    const runWorker = (args) => {
      const result = spawnSync('uv', ['run', '--no-sync', '--project', repoDir, 'archivebox', ...args], {
        cwd: dataDir, encoding: 'utf8', env: process.env, stdio: ['ignore', 'pipe', 'pipe'],
      });
      if (result.status !== 0) throw new Error(`Gallery worker failed: ${result.stderr || result.stdout}`);
    };
    const featureViews = [];
    const library = await require('../archivebox/core/library_gallery.js').prepare(page, adminBaseUrl, process.env.UI_LIBRARY_CRAWL_ID);
    featureViews.push(library);
    featureViews.push({...library, name: 'Folder search', mode: 'folder-search'});
    featureViews.push({...library, name: 'Folder export menu', mode: 'folder-menu'});
    featureViews.push({...library, name: 'Import sources menu', mode: 'import-menu'});
    featureViews.push(await require('../archivebox/core/public_library_gallery.js').prepare(page, process.env.UI_LIBRARY_PUBLIC_URL, library.url));
    featureViews.push({name: 'Add snapshots to a folder', url: library.addUrl, path: '/add/', source: 'archivebox/templates/core/add.html'});
    featureViews.push({name: 'Nested folders in grid view', url: library.url.replace('/snapshot/?', '/snapshot/grid/?'), path: '/admin/core/snapshot/grid/', source: 'archivebox/templates/admin/core/snapshot/change_list.html'});
    featureViews.push(...await require('../archivebox/core/library_gallery.js').prepareExports(page, adminBaseUrl, library.url));
    const clone = await require('../archivebox/domains/gallery.js').prepare(page, adminBaseUrl);
    runWorker(['run', '--crawl-id', clone.crawlId]);
    featureViews.push({name: 'Domain capture options', url: clone.moreOptionsUrl, path: '/add/', source: 'archivebox/templates/core/add.html'});
    featureViews.push({name: 'Domains', url: `${adminBaseUrl}/admin/domains/`, path: '/admin/domains/', source: 'archivebox/domains/views.py'}, {name: 'Add domain', url: `${adminBaseUrl}/admin/domains/?add=1`, path: '/admin/domains/?add=1', source: 'archivebox/domains/templates/domains/index.html'}, clone);
    featureViews.push(...await require('../archivebox/domains/gallery.js').replayViews(page, clone));
    featureViews.push(...await require('../archivebox/domains/gallery.js').exportViews(page, clone, path.join(path.dirname(viewsFile), 'site-exports'), process.env.UI_SITE_EXPORT_BASE_URL));
    featureViews.push(...await require('../archivebox/domains/wacz_gallery.js').exportViews(page, clone, path.join(path.dirname(viewsFile), 'site-exports'), process.env.UI_SITE_EXPORT_BASE_URL));
    const stories = JSON.parse(fs.readFileSync(path.join(path.dirname(viewsFile), 'hacker-news-urls.json'), 'utf8'));
    featureViews.push(...await require('../archivebox/domains/wacz_gallery.js').folderViews(page, library.url, stories, path.join(path.dirname(viewsFile), 'site-exports'), process.env.UI_SITE_EXPORT_BASE_URL));
    featureViews.push(await require('../archivebox/domains/wacz_gallery.js').storyView(page, adminBaseUrl, stories[1], path.join(path.dirname(viewsFile), 'site-exports'), process.env.UI_SITE_EXPORT_BASE_URL));
    const health = await require('../archivebox/linkhealth/gallery.js').prepare(page, adminBaseUrl, process.env.UI_LIBRARY_CRAWL_ID);
    featureViews.push(health);
    const audit = await require('../archivebox/storageaudit/gallery.js').prepare(page, adminBaseUrl);
    featureViews.push({name: 'Storage audit', url: audit.auditUrl, path: '/admin/storage-audit/', source: 'archivebox/storageaudit/views.py'});
    featureViews.push({name: 'Duplicate files by extension', url: audit.extensionUrl, path: '/admin/storage-audit/', source: 'archivebox/storageaudit/templates/storageaudit/index.html'});
    const storageUrl = await require('../archivebox/storage/gallery.js').setupStorage(page, {
      adminBaseUrl,
      destinationPath: path.join(path.dirname(viewsFile), 'rclone-primary-archive'),
    });
    featureViews.push({name: 'Primary archive storage', url: storageUrl, path: '/admin/storage/', source: 'archivebox/storage/views.py'});
    featureViews.push({name: 'Storage provider setup', url: `${adminBaseUrl}/admin/storage/configure/`, path: '/admin/storage/configure/', source: 'archivebox/storage/views.py'});
    fs.writeFileSync(viewsFile, featureViews.map(view => [view.name, view.url, view.path, view.source, view.mode || ''].join('|')).join('\n') + '\n');
    await collapseAdminFilters(page, adminBaseUrl);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
