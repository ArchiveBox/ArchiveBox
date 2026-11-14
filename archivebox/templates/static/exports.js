const archiveFormats = new Set(['html_zip', 'wacz', 'html', 'replay']);
const labels = {html_zip: 'ZIP', wacz: 'WACZ', html: 'HTML', replay: 'ReplayWeb.page'};
const style = document.createElement('link');
style.rel = 'stylesheet';
style.href = new URL('exports.css', import.meta.url).href;
document.head.append(style);

async function jsonResponse(response) {
  if (!response.ok) {
    const type = response.headers.get('content-type') || '';
    throw new Error(type.startsWith('text/plain') ? await response.text() : `Export failed (${response.status})`);
  }
  return response.json();
}

export async function startSnapshotExport(url, {format, anchor, data = new FormData(), csrf = '', session = false, api = false} = {}) {
  if (!archiveFormats.has(format)) throw new Error('Unknown archive format');
  const menu = anchor.closest('[popover]');
  menu?.hidePopover();
  const host = anchor.closest('.folder-row') || anchor.closest('.snapshot-export-block') || anchor.closest('.snapshot-export-links') || anchor.parentElement;
  const status = document.createElement('span');
  status.className = 'snapshot-export-status';
  status.dataset.format = format;
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  if (anchor.closest('td')) anchor.closest('td').append(status);
  else host.after(status);
  const text = document.createElement('span');
  status.append(text);
  const stop = document.createElement('button');
  stop.type = 'button';
  stop.textContent = 'Stop';
  stop.hidden = true;
  status.append(stop);
  let job;
  let stopping = false;
  const headers = {'Accept': 'application/json', ...(csrf ? {'X-CSRFToken': csrf} : {})};
  stop.addEventListener('click', async () => {
    stop.disabled = true;
    try {
      await jsonResponse(await fetch(job.cancel_url, {method: 'POST', headers, credentials: 'same-origin'}));
      stopping = true;
    } catch (error) {text.textContent = error.message; stop.disabled = false;}
  });
  text.textContent = `${labels[format]} · Starting…`;
  data.set('format', format);
  if (session) data.set('session', '1');
  try {
    job = await jsonResponse(await fetch(url, {method: 'POST', body: api ? JSON.stringify({}) : data, headers: api ? {...headers, 'Content-Type': 'application/json'} : headers, credentials: 'same-origin'}));
    while (true) {
      const result = job.result || {};
      status.dataset.status = job.status;
      status.dataset.jobId = job.id;
      status.dataset.exitCode = job.exit_code ?? '';
      status.dataset.exportPath = result.destination || '';
      stop.hidden = !job.can_cancel || job.status === 'exited';
      const count = result.total_pages ? `${result.pages || 0}/${result.total_pages}` : result.total_recordings ? `${result.recordings || 0}/${result.total_recordings}` : '';
      const bytes = result.bytes || result.total_bytes || 0;
      const size = bytes ? new Intl.NumberFormat(undefined, {maximumFractionDigits: 1}).format(bytes / 1024 / 1024) + ' MB' : '';
      text.textContent = [labels[format], stopping ? 'Stopping…' : result.complete ? 'Complete' : job.status === 'exited' ? 'Failed' : 'Exporting…', count, size].filter(Boolean).join(' · ');
      if (job.status === 'exited') {
        if (!result.complete || job.exit_code !== 0) throw new Error(result.error || (stopping ? 'Export stopped' : 'Export failed'));
        if (format === 'html_zip' || format === 'wacz') {
          const download = document.createElement('a');
          download.href = job.download_url;
          download.textContent = 'Download';
          download.setAttribute('download', '');
          download.dataset.exportDownload = '';
          status.append(download);
          download.click();
        } else {
          const path = document.createElement('code');
          path.textContent = result.destination;
          status.append(path);
        }
        return job;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
      job = await jsonResponse(await fetch(job.status_url, {headers, credentials: 'same-origin'}));
    }
  } catch (error) {
    status.dataset.status = 'failed';
    text.textContent = `${labels[format]} · ${error.message}`;
    stop.hidden = true;
    throw error;
  }
}

document.addEventListener('click', event => {
  const link = event.target.closest('a[data-export-format]');
  if (!link || !archiveFormats.has(link.dataset.exportFormat) || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  const controls = link.closest('.snapshot-export-links');
  startSnapshotExport(link.href, {format: link.dataset.exportFormat, anchor: link, csrf: controls?.dataset.exportCsrf, session: controls?.dataset.exportSession === '1', api: controls?.dataset.exportApi === '1'}).catch(() => {});
});
