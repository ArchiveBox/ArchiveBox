// Publish only the real news captures in the isolated gallery collection.
const fs = require('node:fs');
const path = require('node:path');

async function prepare(page, publicBaseUrl, libraryUrl) {
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
module.exports = {prepare};
