#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');

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

    await collapseAdminFilters(page, adminBaseUrl);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
