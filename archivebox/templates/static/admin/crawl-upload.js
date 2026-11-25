(() => {
    const overlay = document.getElementById('crawl-drop-overlay');
    if (!overlay) return;
    const title = document.getElementById('crawl-drop-title');
    const message = document.getElementById('crawl-drop-message');
    const detail = document.getElementById('crawl-drop-detail');
    const close = document.getElementById('crawl-drop-close');
    const picker = document.getElementById('crawl-upload-files');
    let depth = 0;
    let busy = false;
    let previousFocus;

    function hide() {
        if (busy) return;
        overlay.hidden = true;
        depth = 0;
        if (previousFocus) previousFocus.focus();
        previousFocus = null;
    }
    function show(state, heading, description, hint = '') {
        overlay.dataset.state = state;
        title.textContent = heading;
        message.textContent = description;
        message.hidden = !description;
        detail.textContent = hint;
        detail.hidden = !hint;
        close.hidden = state !== 'error';
        overlay.hidden = false;
        if (state === 'error') {
            previousFocus = document.activeElement;
            close.focus();
        }
    }
    function accepts(event) {
        const types = Array.from(event.dataTransfer?.types || []);
        // Folder links can carry a native URL alongside the library's move data.
        if (types.includes('application/x-archivebox-folder') || types.includes('application/x-archivebox-snapshots')) return false;
        return types.some(type => ['Files', 'text/plain', 'text/uri-list', 'text/html'].includes(type));
    }
    async function openAdd(files, text = '') {
        if (busy) return;
        busy = true;
        depth = 0;
        show('uploading', 'Importing…', '', files.map(file => file.name).join(', '));
        try {
            await window.archiveboxAddInput.transfer({files, text});
            window.location.assign(overlay.dataset.addUrl);
        } catch (error) {
            busy = false;
            show('error', 'Import failed', error.message);
        }
    }
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-crawl-upload]');
        if (!button || busy) return;
        // The popover is in the top layer, above the upload overlay.
        button.closest(':popover-open')?.hidePopover();
        picker.click();
    });
    picker.addEventListener('change', () => {
        const files = Array.from(picker.files);
        picker.value = '';
        if (files.length) openAdd(files);
    });
    document.addEventListener('dragenter', event => {
        if (!accepts(event)) return;
        event.preventDefault();
        depth += 1;
        if (!busy) show('dragging', 'Drop to create a crawl', 'Import URLs from files or text.');
    });
    document.addEventListener('dragover', event => {
        if (!accepts(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = busy ? 'none' : 'copy';
    });
    document.addEventListener('dragleave', () => {
        depth = Math.max(0, depth - 1);
        if (!depth && overlay.dataset.state === 'dragging') hide();
    });
    document.addEventListener('drop', event => {
        if (!accepts(event)) return;
        event.preventDefault();
        depth = 0;
        if (busy) return;
        const files = Array.from(event.dataTransfer.files);
        if (files.length) return void openAdd(files);
        const text = event.dataTransfer.getData('text/html') || event.dataTransfer.getData('text/plain') || event.dataTransfer.getData('text/uri-list');
        if (text.trim()) openAdd([], text);
        else show('error', 'Nothing to import', 'Drop a file or text containing URLs.');
    });
    document.addEventListener('dragend', () => { if (overlay.dataset.state === 'dragging') hide(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
    window.addEventListener('blur', () => { if (overlay.dataset.state === 'dragging') hide(); });
    window.addEventListener('pageshow', event => {
        if (event.persisted) {
            busy = false;
            hide();
        }
    });
    close.addEventListener('click', hide);
})();
