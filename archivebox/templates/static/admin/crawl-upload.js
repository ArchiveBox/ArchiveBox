(() => {
    const input = document.getElementById('crawl-upload-file');
    const overlay = document.getElementById('crawl-drop-overlay');
    if (!overlay) return;
    const title = document.getElementById('crawl-drop-title');
    const message = document.getElementById('crawl-drop-message');
    const detail = document.getElementById('crawl-drop-detail');
    const close = document.getElementById('crawl-drop-close');
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
        detail.textContent = hint;
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
        show('uploading', 'Opening Add…', 'Loading your files or text into the existing import form.', files.map(file => file.name).join(', ') || 'Dropped text');
        try {
            await window.archiveboxAddInput.transfer({files, text});
            window.location.assign(overlay.dataset.addUrl);
        } catch (error) {
            busy = false;
            show('error', 'Could not open Add', error.message);
        } finally {
            input.value = '';
        }
    }
    document.addEventListener('click', event => {
        const trigger = event.target.closest('[data-crawl-upload]');
        if (!trigger) return;
        event.preventDefault();
        if (!busy) input.click();
    });
    input.addEventListener('change', () => {
        if (input.files.length) openAdd(Array.from(input.files));
    });
    document.addEventListener('dragenter', event => {
        if (!accepts(event)) return;
        event.preventDefault();
        depth += 1;
        if (!busy) show('dragging', 'Drop to create a crawl', 'Open these files or text in Add to import any URLs found.', 'Review your URLs and settings before starting');
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
