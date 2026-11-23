// Parse into a template so discarded result previews never start loading.
function searchFragment(html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    template.content.querySelectorAll('script').forEach(script => script.remove());
    return template.content;
}

function syncSearchRows(current, incoming, retained = 0) {
    // Keep live browsing contexts attached. Even removing and reinserting the
    // same iframe node starts a new navigation in its embedded document.
    const next = Array.from(incoming.children);
    const keep = new Set(next.map(row => row.dataset.snapshotId).filter(Boolean));
    const existing = new Map();
    for (const row of Array.from(current.children).slice(retained)) {
        const id = row.dataset.snapshotId;
        if (keep.has(id)) existing.set(id, row);
        else row.remove();
    }
    const added = [];
    const tail = document.createDocumentFragment();
    let cursor = current.children[retained] || null;
    for (const fresh of next) {
        const row = existing.get(fresh.dataset.snapshotId);
        if (!row) {
            if (cursor) current.insertBefore(fresh, cursor);
            else tail.append(fresh);
            added.push(fresh);
            continue;
        }
        if (row !== cursor) {
            if (current.moveBefore) current.moveBefore(row, cursor);
            else current.insertBefore(row, cursor);
        }
        // Rank can change when a provisional page settles. Keep client state
        // such as selection and expanded tags on the original element.
        const rank = Array.from(fresh.classList).find(name => name.startsWith('search-rank-'));
        for (const name of Array.from(row.classList)) {
            if (name.startsWith('search-rank-') && name !== rank) row.classList.remove(name);
        }
        if (rank && !row.classList.contains(rank)) row.classList.add(rank);
        cursor = row.nextElementSibling;
    }
    // In the usual append-only wave this is the only write to the live list.
    if (tail.childElementCount) current.append(tail);
    return added;
}

function searchProgress(pageSize) {
    const bar = document.createElement('progress');
    bar.max = pageSize;
    bar.value = 0;
    bar.setAttribute('aria-label', 'Matches found for first page');
    let scanning = false;
    return {
        show(status) {
            if (bar.parentNode !== status) status.replaceChildren(bar, ' Searching...');
            status.hidden = false;
        },
        count(value) {
            if (!scanning) bar.value = Math.min(value, pageSize);
        },
        work(line) {
            if (!line.startsWith('batch ')) return false;
            // The provider already knows the size of its current batch. Measuring
            // the whole query here would make first paint wait for an extra scan.
            const [checked, size] = line.slice(6).split(' ').map(Number);
            scanning = true;
            bar.max = size;
            bar.value = checked;
            bar.setAttribute('aria-label', 'Snapshots checked in this archive batch');
            return true;
        },
        finishing() { bar.value = bar.max; },
    };
}
