/* Load saved screenshots after the list has painted, including offscreen rows. */
(function observeSnapshotPreviews() {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', observeSnapshotPreviews, {once: true});
        return;
    }

    const selector = 'template[data-admin-preview]';
    const pending = new Set();
    const loading = new Set();
    const maxLoading = 6;
    let scheduled = false;

    function load(template) {
        const image = template.content.firstElementChild;
        const fallbacks = image.dataset.fallbacks?.split('\n') || [];
        loading.add(image);

        image.addEventListener('load', () => {
            const initial = image.parentElement?.querySelector('.snapshot-thumbnail-initial');
            if (initial) initial.hidden = true;
            image.hidden = false;
            loading.delete(image);
            schedule();
        }, {once: true});
        image.addEventListener('error', () => {
            const next = fallbacks.shift();
            if (next) {
                image.src = next;
                return;
            }
            image.remove();
            loading.delete(image);
            schedule();
        });
        template.replaceWith(template.content);
    }

    function schedule() {
        if (scheduled || !pending.size || loading.size >= maxLoading) return;
        scheduled = true;
        // Give the table a paint before starting replay requests. Limit the
        // number in flight so 50 offscreen images can't crowd out other work.
        requestAnimationFrame(() => requestAnimationFrame(() => {
            scheduled = false;
            for (const template of pending) {
                if (loading.size >= maxLoading) break;
                pending.delete(template);
                if (template.isConnected) load(template);
            }
        }));
    }

    function visitTemplates(node, visit) {
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        if (node.matches(selector)) visit(node);
        node.querySelectorAll(selector).forEach(visit);
    }

    visitTemplates(document.documentElement, template => pending.add(template));
    schedule();
    // A search or folder change can detach a still-loading image without
    // firing load or error. Free its slot for the replacement rows.
    new MutationObserver(records => {
        records.forEach(record => {
            record.removedNodes.forEach(node => visitTemplates(node, template => pending.delete(template)));
            record.addedNodes.forEach(node => visitTemplates(node, template => pending.add(template)));
        });
        for (const image of loading) {
            if (!image.isConnected) loading.delete(image);
        }
        schedule();
    }).observe(document.body, {childList: true, subtree: true});
})();
