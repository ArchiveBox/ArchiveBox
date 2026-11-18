/* Admin list previews: navigate only once their real thumbnail is visible. */
(() => {
    const selector = 'iframe[data-admin-preview-src]';
    const load = frame => {
        if (!frame.isConnected || !frame.dataset.adminPreviewSrc) return;
        frame.src = frame.dataset.adminPreviewSrc;
        frame.style.visibility = 'visible';
        delete frame.dataset.adminPreviewSrc;
    };
    const observer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
        for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            observer.unobserve(entry.target);
            load(entry.target);
        }
    }, {rootMargin: '0px'}) : null;
    function frames(node, visit) {
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        if (node.matches(selector)) visit(node);
        node.querySelectorAll(selector).forEach(visit);
    }
    const watch = frame => observer ? observer.observe(frame) : load(frame);
    frames(document.documentElement, watch);
    // Search streams and folder navigation replace the result panel without a
    // full page load. Also release removed frames rather than retaining rows.
    new MutationObserver(records => {
        for (const record of records) {
            record.removedNodes.forEach(node => frames(node, frame => observer?.unobserve(frame)));
            record.addedNodes.forEach(node => frames(node, watch));
        }
    }).observe(document.body, {childList: true, subtree: true});
})();
