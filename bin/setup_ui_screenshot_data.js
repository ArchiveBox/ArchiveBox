#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
const {spawnSync} = require('child_process');

const [adminBaseUrl, username, phase] = process.argv.slice(2);
if (!['prepare', 'replay'].includes(phase)) throw new Error('Gallery requires prepare or replay phase');
if (!adminBaseUrl || !username || !process.env.SCREENSHOT_USER_DATA_DIR) {
  throw new Error('usage: setup_ui_screenshot_data.js ADMIN_BASE_URL USERNAME prepare|replay (with SCREENSHOT_USER_DATA_DIR)');
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

    if (phase === 'prepare' && process.env.CREATE_API_TOKEN === '1') {
      await submitAdminAdd(page, `${adminBaseUrl}/admin/api/apitoken/add/`, async () => {
        await selectUser(page);
      });
    }

    if (phase === 'prepare' && process.env.CREATE_WEBHOOK === '1') await submitAdminAdd(page, `${adminBaseUrl}/admin/api/outboundwebhook/add/`, async () => {
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
    const source = JSON.parse(fs.readFileSync(path.join(path.dirname(viewsFile), 'gallery-library-source.json'), 'utf8'));
    if (source.crawl_id !== process.env.UI_LIBRARY_CRAWL_ID || !source.homepage || !source.homepage_selector || !source.title || !Array.isArray(source.stories) || source.stories.length !== 3) {
      throw new Error('Gallery library replay metadata does not match the prepared crawl.');
    }
    const runWorker = (args, fixtureEnv = {}) => {
      const result = spawnSync('uv', ['run', '--no-sync', '--project', repoDir, 'archivebox', ...args], {
        cwd: dataDir, encoding: 'utf8', env: {...process.env, ...fixtureEnv}, stdio: ['ignore', 'inherit', 'inherit'],
      });
      if (result.status !== 0) throw new Error(`Gallery worker failed: ${result.error?.message || `exit ${result.status}, signal ${result.signal || 'none'}`}`);
    };
    const checkpoint = `${viewsFile}.prepared.json`;
    if (phase === 'prepare') {
      const featureViews = [];
      const library = await require('../archivebox/core/library_gallery.js').prepare(page, adminBaseUrl, process.env.UI_LIBRARY_CRAWL_ID, source);
      featureViews.push(library);
      featureViews.push({...library, name: 'Navigation tools menu', source: 'archivebox/templates/core/navigation.html', mode: 'navbar-tools'});
      featureViews.push({...library, name: 'Navigation account menu', source: 'archivebox/templates/core/navigation.html', mode: 'navbar-account'});
      const smart = await require('../archivebox/core/library_gallery.js').prepareSmartFolder(page, adminBaseUrl, process.env.UI_LIBRARY_CRAWL_ID, source);
      featureViews.push(smart, {...smart, name: 'Smart folder rule editor', mode: 'smart-folder'});
      featureViews.push({...library, name: 'Current view export menu', mode: 'view-export-menu'});
      featureViews.push({...library, name: 'Folder search', mode: 'folder-search'});
      featureViews.push({...library, name: 'Folder export menu', mode: 'folder-menu'});
      featureViews.push({...library, name: 'Import sources menu', mode: 'import-menu'});
      featureViews.push(await require('../archivebox/core/public_library_gallery.js').prepare(page, process.env.UI_LIBRARY_PUBLIC_URL, library.url));
      featureViews.push({name: 'Add snapshots to a folder', url: library.addUrl, path: '/add/', source: 'archivebox/templates/core/add.html'});
      featureViews.push({name: 'Nested folders in grid view', url: library.url.replace('/snapshot/?', '/snapshot/grid/?'), path: '/admin/core/snapshot/grid/', source: 'archivebox/templates/admin/core/snapshot/change_list.html'});
      featureViews.push(...await require('../archivebox/core/library_gallery.js').prepareExports(page, adminBaseUrl, library.url, source.homepage));
      // Mandatory same-origin replay navigation uses an owned two-page site.
      // The selected folder has its own independently verified recordings.
      const siteDirectory = path.join(path.dirname(viewsFile), 'site-exports', 'site-navigation');
      fs.cpSync(path.join(repoDir, 'archivebox/tests/fixtures/site-navigation'), siteDirectory, {recursive: true});
      const siteUrl = new URL('site-navigation/index.html', process.env.UI_SITE_EXPORT_BASE_URL).href;
      const clone = await require('../archivebox/domains/gallery.js').prepare(page, adminBaseUrl, siteUrl);
      runWorker(['run', '--crawl-id', clone.crawlId]);
      if (process.env.UI_SCREENSHOT_UNAVAILABLE_OUT) {
        runWorker(['manage', 'shell', '--no-imports', '-c',
          'import os; from archivebox.core.gallery_replay_fixture import prepare_site_navigation; prepare_site_navigation(os.environ["UI_GALLERY_CLONE_ID"], os.environ["UI_GALLERY_CLONE_FIXTURE"])',
        ], {UI_GALLERY_CLONE_ID: clone.crawlId, UI_GALLERY_CLONE_FIXTURE: siteDirectory});
      }
      featureViews.push({name: 'Domain capture options', url: clone.moreOptionsUrl, path: '/add/', source: 'archivebox/templates/core/add.html'});
      featureViews.push({name: 'Domains', url: `${adminBaseUrl}/admin/domains/`, path: '/admin/domains/', source: 'archivebox/domains/views.py'}, {name: 'Add domain', url: `${adminBaseUrl}/admin/domains/?add=1`, path: '/admin/domains/?add=1', source: 'archivebox/domains/templates/domains/index.html'}, clone);
      // The folder export and its linked-story navigation use owned recordings.
      // Keep the native HN captures and standalone story replay independent.
      const folderReplayFile = `${viewsFile}.folder-replay.json`;
      runWorker(['manage', 'shell', '--no-imports', '-c',
        'import json, os; from pathlib import Path; from archivebox.core.gallery_replay_fixture import prepare_folder; Path(os.environ["UI_GALLERY_FOLDER_REPLAY"]).write_text(json.dumps(prepare_folder()))',
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
    featureViews.push(...await require('../archivebox/domains/gallery.js').replayViews(page, clone));
    featureViews.push(...await require('../archivebox/domains/gallery.js').exportViews(page, clone, path.join(path.dirname(viewsFile), 'site-exports'), process.env.UI_SITE_EXPORT_BASE_URL));
    featureViews.push(...await require('../archivebox/domains/wacz_gallery.js').exportViews(page, clone, path.join(path.dirname(viewsFile), 'site-exports'), process.env.UI_SITE_EXPORT_BASE_URL));
    const waczGallery = require('../archivebox/domains/wacz_gallery.js');
    const exportDirectory = path.join(path.dirname(viewsFile), 'site-exports');
    const folderReplayUrl = `${adminBaseUrl}/admin/core/snapshot/?${new URLSearchParams({folder: folderReplay.folder_id})}`;
    featureViews.push(...await waczGallery.folderViews(page, folderReplayUrl, folderReplay, exportDirectory, process.env.UI_SITE_EXPORT_BASE_URL));
    const story = source.stories[0];
    featureViews.push(await waczGallery.storyView(page, adminBaseUrl, story, exportDirectory, process.env.UI_SITE_EXPORT_BASE_URL, source.replay_urls[story]));
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
