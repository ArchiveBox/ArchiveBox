/* Admin list previews: create a real iframe only when its thumbnail is visible. */
(function observeSnapshotPreviews() {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', observeSnapshotPreviews, {once: true});
        return;
    }
    const selector = 'template[data-admin-preview]';
    const load = holder => {
        const template = holder.querySelector(selector);
        if (!holder.isConnected || !template) return;
        // The server-rendered frame retains its native URL, sandbox and sizing.
        // Template contents have no browsing context until inserted here.
        template.replaceWith(template.content);
    };
    const observer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
        for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            observer.unobserve(entry.target);
            load(entry.target);
        }
    }, {rootMargin: '0px'}) : null;
    function holders(node, visit) {
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        if (node.matches(selector)) visit(node.parentElement);
        node.querySelectorAll(selector).forEach(template => visit(template.parentElement));
    }
    const watch = holder => {
        if (!holder?.isConnected) return;
        if (observer) observer.observe(holder);
        else load(holder);
    };
    holders(document.documentElement, watch);
    // Search/folder panel replacements preserve the same lifecycle. Release
    // removed offscreen holders rather than retaining their old result rows.
    new MutationObserver(records => {
        for (const record of records) {
            record.removedNodes.forEach(node => holders(node, holder => holder && observer?.unobserve(holder)));
            record.addedNodes.forEach(node => holders(node, watch));
        }
    }).observe(document.body, {childList: true, subtree: true});
})();
