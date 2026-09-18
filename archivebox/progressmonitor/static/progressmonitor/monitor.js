(function() {
    const monitor = document.getElementById('progress-monitor');
    const collapseBtn = document.getElementById('progress-collapse');
    const treeContainer = document.getElementById('tree-container');
    const crawlTree = document.getElementById('crawl-tree');
    const idleMessage = document.getElementById('idle-message');
    const screencastPanel = document.getElementById('screencast-panel');

    let pollInterval = null;
    let pollDelayMs = 1000;
    let idleTicks = 0;
    let isCollapsed = monitor.dataset.autoExpand !== '1';
    const snapshotMedia = new Map();

    function stableSnapshotMedia(snapshot) {
        // The progress endpoint can briefly omit media URLs while ArchiveResult
        // rows settle. Once this page has seen a snapshot image URL, keep using
        // it so the preview/favicon branch does not flicker back to placeholder.
        const snapshotId = String(snapshot.id || '');
        const media = snapshotMedia.get(snapshotId) || {};
        if (snapshot.favicon_url) media.favicon_url ||= snapshot.favicon_url;
        if (snapshot.preview_url) {
            media.preview_url ||= snapshot.preview_url;
            media.preview_link ||= snapshot.preview_link;
            media.preview_fallbacks ||= snapshot.preview_fallbacks || [];
        }
        if (snapshotId) snapshotMedia.set(snapshotId, media);
        return media;
    }
    function preserveStableMediaNodes(nextRoot) {
        // Snapshot preview/favicon files are immutable once visible. Keep the
        // loaded DOM nodes across poll renders so the browser never reloads
        // them while progress text/badges continue updating around them.
        const currentCards = new Map(
            Array.from(crawlTree.querySelectorAll('.snapshot-item[data-snapshot-id]')).map(card => [card.dataset.snapshotId, card])
        );
        nextRoot.querySelectorAll('.snapshot-item[data-snapshot-id]').forEach(nextCard => {
            const currentCard = currentCards.get(nextCard.dataset.snapshotId);
            if (!currentCard) return;
            currentCard.querySelectorAll('[data-stable-media]').forEach(currentNode => {
                const nextNode = nextCard.querySelector(`[data-stable-media="${currentNode.dataset.stableMedia}"]`);
                if (nextNode) nextNode.replaceWith(currentNode);
            });
        });
    }
    function replaceCrawlTree(html) {
        const template = document.createElement('template');
        template.innerHTML = html;
        preserveStableMediaNodes(template.content);
        crawlTree.replaceChildren(...template.content.childNodes);
    }
    window.nextPreviewFallback = function(img) {
        const fallbacks = (img.dataset.fallbacks || '').split(',').filter(Boolean);
        if (fallbacks.length > 0) {
            img.src = fallbacks.shift();
            img.dataset.fallbacks = fallbacks.join(',');
        } else {
            const preview = img.closest('.snapshot-preview');
            if (preview) {
                preview.removeAttribute('data-stable-media');
                preview.classList.add('placeholder');
                preview.innerHTML = '<span>▤</span>';
            }
        }
    };
    function formatUrl(url) {
        if (!url) return '(no URL)';
        try {
            const u = new URL(url);
            return u.hostname + u.pathname.substring(0, 30) + (u.pathname.length > 30 ? '...' : '');
        } catch {
            return String(url).substring(0, 50) + (String(url).length > 50 ? '...' : '');
        }
    }

    function getPluginIcon(plugin) {
        const icons = {
            'screenshot': '▧',
            'chrome_mhtml': '▧',
            'favicon': '◆',
            'dom': '&lt;/&gt;',
            'pdf': 'PDF',
            'title': 'T',
            'headers': '{}',
            'singlefile': '▣',
            'readability': 'R',
            'mercury': 'M',
            'wget': '↓',
            'media': '▶',
        };
        return icons[plugin] || '•';
    }

    function formatDuration(seconds) {
        seconds = Math.max(0, Math.floor(seconds || 0));
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;
        if (hours > 0) return `${hours}hr ${minutes}m ${secs}s`;
        if (minutes > 0) return `${minutes}m ${secs}s`;
        return `${secs}s`;
    }

    function durationText(startedAt) {
        const startedMs = Date.parse(startedAt || '');
        if (!Number.isFinite(startedMs)) return '';
        return formatDuration((Date.now() - startedMs) / 1000);
    }

    function renderDurationBadge(startedAt) {
        const text = durationText(startedAt);
        if (!text) return '';
        return `<span class="duration-badge" data-started-at="${ArchiveBoxUI.escapeHtml(startedAt)}" title="Duration">${ArchiveBoxUI.escapeHtml(text)}</span>`;
    }

    function updateDurationBadges() {
        document.querySelectorAll('#progress-monitor .duration-badge[data-started-at]').forEach((badge) => {
            const text = durationText(badge.dataset.startedAt);
            if (text) badge.textContent = text;
        });
    }

    function activeScreencastTarget(data) {
        const hookText = (item) => `${item.plugin || ''} ${item.hook_name || ''} ${item.label || ''}`.toLowerCase();
        let fallback = null;
        for (const crawl of data.active_crawls || []) {
            for (const snapshot of crawl.active_snapshots || []) {
                if (!Array.isArray(snapshot) && snapshot.screencast_url) {
                    return {type: 'frame', crawl, snapshot};
                }
            }
        }
        for (const crawl of data.active_crawls || []) {
            if (fallback) continue;

            const setupPlugins = crawl.setup_plugins || [];
            const browserReady = setupPlugins.some((item) => (
                item.status === 'succeeded' && hookText(item).includes('chrome wait')
            ));
            if (!browserReady && setupPlugins.some((item) => item.status === 'started' && hookText(item).includes('chrome launch'))) {
                fallback = {
                    type: 'placeholder',
                    crawl,
                    state: 'launching',
                    icon: '▣',
                    title: 'Launching browser',
                    subtitle: 'Chrome is starting and publishing its CDP session.',
                };
                continue;
            }
            const openingSnapshot = (crawl.active_snapshots || []).find((snapshot) => {
                if (Array.isArray(snapshot)) return false;
                const plugins = snapshot.all_plugins || [];
                const tabReady = plugins.some((item) => (
                    item.status === 'succeeded' && hookText(item).includes('chrome wait')
                ));
                return !tabReady && plugins.some((item) => (
                    item.status === 'started' && hookText(item).includes('chrome tab')
                ));
            });
            if (openingSnapshot) {
                fallback = {
                    type: 'placeholder',
                    crawl,
                    snapshot: openingSnapshot,
                    state: 'launching',
                    icon: '▣',
                    title: 'Opening browser tab',
                    subtitle: 'The snapshot tab is being attached for capture.',
                };
                continue;
            }
            if ((crawl.status === 'queued' || crawl.status === 'started') && !setupPlugins.some((item) => hookText(item).includes('chrome launch'))) {
                fallback = {
                    type: 'placeholder',
                    crawl,
                    state: 'not-launched',
                    icon: '▯',
                    title: 'Browser not launched yet',
                    subtitle: 'Waiting for the crawl setup hooks to start Chrome.',
                };
            }
        }
        return fallback;
    }

    function updateScreencastPanel(data) {
        const hasWork = (data.active_crawls || []).length > 0 ||
            (data.crawls_queued || 0) > 0 ||
            (data.crawls_active || 0) > 0 ||
            (data.snapshots_queued || 0) > 0 ||
            (data.snapshots_active || 0) > 0;
        let target = activeScreencastTarget(data);
        if (!target) {
            const currentFrame = screencastPanel.querySelector('.screencast-frame img');
            if (
                hasWork &&
                screencastPanel.dataset.mode === 'frame' &&
                currentFrame?.getAttribute('src') &&
                currentFrame.complete &&
                currentFrame.naturalWidth > 0
            ) {
                screencastPanel.classList.add('visible');
                currentFrame.style.opacity = '1';
                return;
            }
            if (!hasWork) {
                screencastPanel.classList.remove('visible');
                screencastPanel.dataset.mode = '';
                screencastPanel.innerHTML = '';
                return;
            }
            target = {
                type: 'placeholder',
                state: 'not-launched',
                icon: '▯',
                title: 'Waiting for browser',
                subtitle: 'Live preview will appear whenever Chrome is active.',
            };
        }
        if (target.type === 'placeholder') {
            const currentFrame = screencastPanel.querySelector('.screencast-frame img');
            if (
                screencastPanel.dataset.mode === 'frame' &&
                currentFrame?.getAttribute('src') &&
                currentFrame.complete &&
                currentFrame.naturalWidth > 0
            ) {
                screencastPanel.classList.add('visible');
                currentFrame.style.opacity = '1';
                return;
            }
            const crawlUrl = target.crawl?.id ? `/admin/crawls/crawl/${target.crawl.id}/change/` : '/admin/';
            const placeholderKey = [target.state, target.title, target.subtitle, crawlUrl].join('|');
            if (screencastPanel.dataset.mode === 'placeholder' && screencastPanel.dataset.key === placeholderKey) {
                return;
            }
            screencastPanel.dataset.mode = 'placeholder';
            screencastPanel.dataset.key = placeholderKey;
            screencastPanel.classList.add('visible');
            screencastPanel.innerHTML = `
                <a class="screencast-frame" href="${ArchiveBoxUI.escapeHtml(crawlUrl)}" title="Open crawl admin">
                    <span class="screencast-placeholder ${ArchiveBoxUI.escapeHtml(target.state)}">
                        <span class="screencast-placeholder-icon">${ArchiveBoxUI.escapeHtml(target.icon)}</span>
                        <span class="screencast-placeholder-title">${ArchiveBoxUI.escapeHtml(target.title)}</span>
                        <span class="screencast-placeholder-subtitle">${ArchiveBoxUI.escapeHtml(target.subtitle)}</span>
                    </span>
                </a>
                <a class="screencast-caption" href="${ArchiveBoxUI.escapeHtml(crawlUrl)}" title="Open crawl admin">
                    <span class="screencast-dot ${ArchiveBoxUI.escapeHtml(target.state)}"></span>
                    <span class="screencast-text">
                        <span class="screencast-title">${ArchiveBoxUI.escapeHtml(target.title)}</span>
                        <span class="screencast-url">Crawl setup</span>
                    </span>
                </a>
            `;
            return;
        }
        const snapshot = target.snapshot;
        const adminUrl = snapshot.admin_url || `/admin/core/snapshot/${snapshot.id || 'unknown'}/change/`;
        const linkUrl = snapshot.screencast_link || snapshot.view_url || adminUrl;
        const titleText = snapshot.title || formatUrl(snapshot.full_url || snapshot.url);
        const urlText = snapshot.full_url || snapshot.url || '';
        const newUrl = snapshot.screencast_url;
        const snapshotKey = `${target.crawl?.id || ''}|${snapshot.id || ''}`;
        screencastPanel.dataset.desiredFrameKey = snapshotKey;

        if (screencastPanel.dataset.mode !== 'frame' && !screencastPanel.querySelector('.screencast-frame img')?.getAttribute('src')) {
            if (screencastPanel.dataset.pendingFrameSrc) return;
            screencastPanel.dataset.pendingFrameSrc = newUrl;
            screencastPanel.dataset.pendingFrameKey = snapshotKey;
            const firstFrame = new Image();
            firstFrame.decoding = 'async';
            firstFrame.onload = () => {
                (firstFrame.decode ? firstFrame.decode() : Promise.resolve()).catch(() => {}).finally(() => {
                    if (screencastPanel.dataset.pendingFrameSrc !== newUrl) return;
                    delete screencastPanel.dataset.pendingFrameSrc;
                    delete screencastPanel.dataset.pendingFrameKey;
                    if (screencastPanel.dataset.desiredFrameKey !== snapshotKey) return;
                    screencastPanel.dataset.mode = 'frame';
                    screencastPanel.dataset.key = '';
                    screencastPanel.dataset.currentFrameSrc = newUrl;
                    screencastPanel.innerHTML = `
                        <a class="screencast-frame" href="${ArchiveBoxUI.escapeHtml(linkUrl)}" title="Open active snapshot">
                            <img src="${ArchiveBoxUI.escapeHtml(newUrl)}" alt="" decoding="async" loading="eager">
                        </a>
                        <a class="screencast-caption" href="${ArchiveBoxUI.escapeHtml(adminUrl)}" title="Open snapshot admin">
                            <span class="screencast-dot"></span>
                            <span class="screencast-text">
                                <span class="screencast-title">${ArchiveBoxUI.escapeHtml(titleText)}</span>
                                <span class="screencast-url">${ArchiveBoxUI.escapeHtml(urlText)}</span>
                            </span>
                        </a>
                    `;
                    screencastPanel.classList.add('visible');
                });
            };
            firstFrame.onerror = () => {
                if (screencastPanel.dataset.pendingFrameSrc === newUrl) {
                    delete screencastPanel.dataset.pendingFrameSrc;
                    delete screencastPanel.dataset.pendingFrameKey;
                }
            };
            firstFrame.src = newUrl;
            return;
        }

        if (screencastPanel.dataset.mode !== 'frame') {
            screencastPanel.dataset.mode = 'frame';
            screencastPanel.dataset.key = '';
            screencastPanel.innerHTML = `
                <a class="screencast-frame" href="" title="Open active snapshot">
                    <img src="" alt="" decoding="async" loading="eager">
                </a>
                <a class="screencast-caption" href="" title="Open snapshot admin">
                    <span class="screencast-dot"></span>
                    <span class="screencast-text">
                        <span class="screencast-title"></span>
                        <span class="screencast-url"></span>
                    </span>
                </a>
            `;
        }
        const frameLink = screencastPanel.querySelector('.screencast-frame');
        const captionLink = screencastPanel.querySelector('.screencast-caption');
        const img = screencastPanel.querySelector('.screencast-frame img');
        const titleEl = screencastPanel.querySelector('.screencast-title');
        const urlEl = screencastPanel.querySelector('.screencast-url');
        frameLink.href = linkUrl;
        captionLink.href = adminUrl;
        titleEl.textContent = titleText;
        urlEl.textContent = urlText;
        if (img.getAttribute('src')) {
            img.style.opacity = '1';
            screencastPanel.classList.add('visible');
        }
        if (screencastPanel.dataset.currentFrameSrc !== newUrl && screencastPanel.dataset.pendingFrameSrc !== newUrl && !screencastPanel.dataset.pendingFrameSrc) {
            screencastPanel.dataset.pendingFrameSrc = newUrl;
            screencastPanel.dataset.pendingFrameKey = snapshotKey;
            const nextFrame = new Image();
            nextFrame.decoding = 'async';
            nextFrame.onload = () => {
                (nextFrame.decode ? nextFrame.decode() : Promise.resolve()).catch(() => {}).finally(() => {
                    if (screencastPanel.dataset.pendingFrameSrc !== newUrl) return;
                    delete screencastPanel.dataset.pendingFrameSrc;
                    delete screencastPanel.dataset.pendingFrameKey;
                    if (screencastPanel.dataset.desiredFrameKey !== snapshotKey) return;
                    const currentImg = screencastPanel.querySelector('.screencast-frame img');
                    if (!currentImg) return;
                    nextFrame.alt = '';
                    nextFrame.loading = 'eager';
                    nextFrame.style.opacity = '1';
                    currentImg.replaceWith(nextFrame);
                    screencastPanel.dataset.currentFrameSrc = newUrl;
                    screencastPanel.classList.add('visible');
                });
            };
            nextFrame.onerror = () => {
                if (screencastPanel.dataset.pendingFrameSrc === newUrl) {
                    delete screencastPanel.dataset.pendingFrameSrc;
                    delete screencastPanel.dataset.pendingFrameKey;
                    if (!screencastPanel.querySelector('.screencast-frame img')?.getAttribute('src')) {
                        screencastPanel.classList.remove('visible');
                    }
                }
            };
            nextFrame.src = newUrl;
        }
    }

    function renderExtractor(extractor) {
        const statusIcons = {started: '▶', succeeded: '✓', failed: '!', backoff: 'wait', skipped: 'skip', noresults: '∅'};
        const icon = statusIcons[extractor.status] || getPluginIcon(extractor.plugin);
        const progress = typeof extractor.progress === 'number'
            ? Math.max(0, Math.min(100, extractor.progress))
            : null;
        const progressStyle = progress !== null ? ` style="width: ${progress}%;"` : '';
        const pidHtml = extractor.status === 'started' && extractor.pid ? `<span class="pid-label compact">pid ${extractor.pid}</span>` : '';
        const href = extractor.output_url || extractor.admin_url || '';
        const tag = href ? 'a' : 'span';
        const hrefAttr = href ? ` href="${ArchiveBoxUI.escapeHtml(href)}"` : '';
        const title = extractor.output_path
            ? `${extractor.plugin || 'output'}: ${extractor.output_path}`
            : `${extractor.plugin || 'hook'}${extractor.hook_name ? `: ${extractor.hook_name}` : ''}`;

        return `
            <${tag} class="extractor-badge ${extractor.status || 'queued'}"${hrefAttr} title="${ArchiveBoxUI.escapeHtml(title)}">
                <span class="progress-fill"${progressStyle}></span>
                <span class="badge-content">
                    <span class="badge-icon">${icon}</span>
                    <span>${ArchiveBoxUI.escapeHtml(extractor.label || extractor.plugin || 'unknown')}</span>
                    ${pidHtml}
                </span>
            </${tag}>
        `;
    }

    function renderExtractors(extractors = []) {
        if (!extractors.length) return '';
        const sorted = [...extractors].sort((a, b) => (a.plugin || '').localeCompare(b.plugin || ''));
        return `<div class="extractor-list">${sorted.map(renderExtractor).join('')}</div>`;
    }

    function renderSnapshot(snapshot) {
        if (Array.isArray(snapshot)) {
            snapshot = {
                id: snapshot[0],
                url: snapshot[1],
                title: snapshot[2],
                status: snapshot[3] || 'queued',
            };
        }
        const statusIcon = snapshot.status === 'started' ? '▤' : '▢';
        const adminUrl = snapshot.admin_url || `/admin/core/snapshot/${snapshot.id || 'unknown'}/change/`;
        const canCancel = snapshot.status === 'queued';
        const cancelBtn = canCancel
            ? `<button class="cancel-item-btn" data-cancel-type="snapshot" data-snapshot-id="${snapshot.id}" data-label="✕" title="Cancel snapshot">✕</button>`
            : '';
        const snapshotPidHtml = snapshot.worker_pid ? `<span class="pid-label compact">pid ${snapshot.worker_pid}</span>` : '';
        const snapshotDurationHtml = renderDurationBadge(snapshot.started);
        const titleText = snapshot.title || formatUrl(snapshot.full_url || snapshot.url);
        const urlText = snapshot.full_url || snapshot.url || '';
        const media = stableSnapshotMedia(snapshot);
        const faviconHtml = media.favicon_url
            ? `<img class="snapshot-favicon" data-stable-media="favicon" src="${ArchiveBoxUI.escapeHtml(media.favicon_url)}" alt="" decoding="async" loading="lazy" onerror="this.remove()">`
            : '';
        const previewHtml = media.preview_url
            ? `<a class="snapshot-preview" data-stable-media="preview" href="${ArchiveBoxUI.escapeHtml(media.preview_link || snapshot.view_url || adminUrl)}" title="Open snapshot output"><img src="${ArchiveBoxUI.escapeHtml(media.preview_url)}" alt="" decoding="async" loading="lazy" data-fallbacks="${ArchiveBoxUI.escapeHtml((media.preview_fallbacks || []).join(','))}" onerror="nextPreviewFallback(this)"></a>`
            : `<a class="snapshot-preview placeholder" href="${ArchiveBoxUI.escapeHtml(snapshot.view_url || adminUrl)}" title="Open snapshot"><span>${statusIcon}</span></a>`;

        const extractorHtml = renderExtractors(snapshot.all_plugins);

        const hasProcessEntries = (snapshot.all_plugins || []).some(extractor => extractor.source === 'process');
        const hasArchiveResults = (snapshot.all_plugins || []).some(extractor => extractor.source === 'archiveresult');
        const processOnly = hasProcessEntries && !hasArchiveResults;
        const runningProcessCount = (snapshot.all_plugins || []).filter(extractor => extractor.source === 'process' && extractor.status === 'started').length;
        const failedProcessCount = (snapshot.all_plugins || []).filter(extractor => extractor.source === 'process' && extractor.status === 'failed').length;
        const snapshotMeta = (snapshot.total_plugins || 0) > 0
            ? processOnly
                ? runningProcessCount > 0
                    ? `Running ${runningProcessCount}/${snapshot.total_plugins || 0} setup hooks`
                    : failedProcessCount > 0
                        ? `${failedProcessCount} setup hook${failedProcessCount === 1 ? '' : 's'} failed`
                        : `${snapshot.completed_plugins || 0}/${snapshot.total_plugins || 0} setup hooks`
                : hasProcessEntries
                    ? `${snapshot.completed_plugins || 0}/${snapshot.total_plugins || 0} tasks${(snapshot.failed_plugins || 0) > 0 ? ` <span style="color:#f85149">(${snapshot.failed_plugins} failed)</span>` : ''}${runningProcessCount > 0 ? ` <span style="color:#d29922">(${runningProcessCount} hooks running)</span>` : ''}`
                    : `${snapshot.completed_plugins || 0}/${snapshot.total_plugins || 0} extractors${(snapshot.failed_plugins || 0) > 0 ? ` <span style="color:#f85149">(${snapshot.failed_plugins} failed)</span>` : ''}`
            : snapshot.worker_state === 'crashed'
                ? '<span style="color:#f85149">Worker stopped before extractors started</span>'
                : snapshot.worker_state === 'stalled'
                    ? '<span style="color:#d29922">Waiting for runner to resume</span>'
                    : snapshot.worker_state === 'cancelled'
                        ? '<span style="color:#8b949e">Cancelled before completion</span>'
                        : 'Waiting for extractors...';

        return `
            <div class="snapshot-item" data-snapshot-id="${ArchiveBoxUI.escapeHtml(snapshot.id || '')}">
                <div class="snapshot-header">
                    ${previewHtml}
                    <a class="snapshot-header-link" href="${adminUrl}">
                        <div class="snapshot-info">
                            <div class="snapshot-title-line">
                                ${faviconHtml}
                                <span class="snapshot-title">${ArchiveBoxUI.escapeHtml(titleText)}</span>
                            </div>
                            <div class="snapshot-url">${ArchiveBoxUI.escapeHtml(urlText)}</div>
                            <div class="snapshot-meta">
                                ${snapshotMeta}
                            </div>
                        </div>
                        ${snapshotPidHtml}
                        ${snapshotDurationHtml}
                        <span class="status-badge ${snapshot.status || 'unknown'}">${snapshot.status || 'unknown'}</span>
                    </a>
                    ${cancelBtn}
                </div>
                <div class="snapshot-progress">
                    <div class="progress-bar-container">
                        <div class="progress-bar snapshot ${((processOnly && runningProcessCount > 0) || (snapshot.status === 'started' && (snapshot.progress || 0) === 0)) ? 'indeterminate' : ''}"
                             style="width: ${snapshot.progress || 0}%"></div>
                    </div>
                </div>
                ${extractorHtml}
            </div>
        `;
    }

    function renderCrawl(crawl) {
        const adminUrl = `/admin/crawls/crawl/${crawl.id || 'unknown'}/change/`;
        const adminFieldUrl = (fieldName) => `${adminUrl}#id_${fieldName}`;
        const crawlBadge = (className, label, value, href, title) => {
            const tag = href ? 'a' : 'span';
            const hrefAttr = href ? ` href="${ArchiveBoxUI.escapeHtml(href)}"` : '';
            const titleAttr = title ? ` title="${ArchiveBoxUI.escapeHtml(title)}"` : '';
            return `<${tag} class="crawl-badge ${className}"${hrefAttr}${titleAttr}><strong>${ArchiveBoxUI.escapeHtml(label)}</strong>${ArchiveBoxUI.escapeHtml(value)}</${tag}>`;
        };
        const crawlId = (crawl.id || 'unknown').toString();
        const crawlShortId = crawlId === 'unknown' ? 'unknown' : crawlId.slice(-8);
        const startedDate = crawl.started ? crawl.started.slice(0, 10) : 'unknown date';
        const canCancel = crawl.status === 'queued' || crawl.status === 'started' || crawl.status === 'paused';
        const canPause = (crawl.status === 'queued' || crawl.status === 'started') && !crawl.is_paused;
        const canResume = crawl.status === 'paused' || crawl.is_paused;
        const pauseBtn = canPause
            ? `<button class="crawl-action-btn pause-item-btn" data-crawl-action="pause" data-crawl-id="${crawl.id}" data-label="Ⅱ" title="Pause crawl">Ⅱ</button>`
            : canResume
                ? `<button class="crawl-action-btn pause-item-btn" data-crawl-action="resume" data-crawl-id="${crawl.id}" data-label="▶" title="Resume crawl">▶</button>`
                : '';
        const cancelBtn = canCancel
            ? `<button class="cancel-item-btn" data-cancel-type="crawl" data-crawl-id="${crawl.id}" data-label="✕" title="Cancel crawl">✕</button>`
            : '';
        const crawlPidHtml = crawl.worker_pid ? `<span class="pid-label compact">pid ${crawl.worker_pid}</span>` : '';
        const crawlDurationHtml = renderDurationBadge(crawl.started);

        const snapshotsHtml = (crawl.active_snapshots || []).map(renderSnapshot).join('');
        const queuedSnapshotsHidden = Number(crawl.queued_snapshots_hidden || 0);
        const queuedSnapshotsNote = queuedSnapshotsHidden > 0
            ? `<div class="progress-overflow-note">${queuedSnapshotsHidden} more queued snapshot${queuedSnapshotsHidden === 1 ? '' : 's'} not shown</div>`
            : '';
        let setupHtml = '';
        if (crawl.setup_plugins && crawl.setup_plugins.length > 0) {
            setupHtml = `
                <div class="snapshot-item">
                    <div class="snapshot-header">
                        <div class="snapshot-header-link">
                            <span class="snapshot-icon">&#9881;</span>
                            <div class="snapshot-info">
                                <div class="snapshot-url">Crawl Setup</div>
                            </div>
                        </div>
                    </div>
                    ${renderExtractors(crawl.setup_plugins)}
                </div>
            `;
        }

        const urlPreview = crawl.urls_preview ? ` (${ArchiveBoxUI.escapeHtml(crawl.urls_preview)})` : '';
        const warnings = [
            [crawl.status === 'queued' && !crawl.can_start, 'error',
                `Crawl cannot start: ${crawl.urls_preview ? 'unknown error' : 'no URLs'}`],
            [crawl.is_paused, 'warning',
                'Crawl is paused. Resume it to continue processing queued snapshots.'],
            [crawl.status === 'queued' && crawl.retry_at_future, 'info',
                `Trying in ${crawl.seconds_until_retry || 0}s...${urlPreview}`],
            [crawl.status === 'queued' && crawl.total_snapshots === 0, 'warning',
                `Waiting for the runner to pick up...${urlPreview}`],
            [crawl.status === 'started' && crawl.worker_state === 'crashed', 'error',
                `Runner stopped with ${crawl.started_snapshots || 0} active and ${crawl.pending_snapshots || 0} pending snapshots. It will resume when the runner starts again.`],
            [crawl.worker_state === 'cancelled', 'cancelled',
                `Crawl was cancelled. ${crawl.cancelled_snapshots || 0} snapshot${(crawl.cancelled_snapshots || 0) === 1 ? '' : 's'} stopped before completion.`],
        ];
        const warning = warnings.find(([matches]) => matches);
        const warningHtml = warning ? `<div class="crawl-notice ${warning[1]}">${warning[2]}</div>` : '';

        // Show crawl-scale limits and sealed output sizes from DB metadata.
        const currentUrlCount = Math.max(crawl.total_snapshots || 0, crawl.urls_count || 0);
        const maxUrlsText = (crawl.max_urls || 0) > 0 ? crawl.max_urls : 'unlimited';
        const urlLimitText = `${currentUrlCount} / ${maxUrlsText}`;
        const crawlSizeLimitText = `${crawl.crawl_output_size_display || '0 B'} / ${crawl.max_crawl_size_display || 'unlimited'}`;
        const crawlTimeoutText = (crawl.crawl_timeout || 0) > 0 ? `${crawl.crawl_timeout}s` : 'unlimited';
        const snapshotSizeLimitText = `${crawl.avg_snapshot_size_display || '0 B'} / ${crawl.max_snapshot_size_display || 'unlimited'}`;
        const crawlBadges = [
            crawlBadge('persona', 'Persona Config', crawl.persona || 'Default', crawl.persona_admin_url, 'Edit persona config'),
            crawlBadge('limit', 'depth', crawl.max_depth || 0, adminFieldUrl('max_depth'), 'Edit crawl depth'),
            crawlBadge('limit', 'urls', urlLimitText, adminFieldUrl('max_urls'), 'Edit max URLs'),
            crawlBadge('size', 'crawl size', crawlSizeLimitText, adminFieldUrl('crawl_max_size'), 'Edit max crawl size'),
            crawlBadge('limit', 'time', crawlTimeoutText, adminFieldUrl('crawl_timeout'), 'Edit max crawl time'),
            crawlBadge('size', 'avg snap', snapshotSizeLimitText, adminFieldUrl('snapshot_max_size'), 'Edit max snapshot size'),
            ...(crawl.tags || []).map(tag => `<a class="crawl-badge tag" href="${ArchiveBoxUI.escapeHtml(adminFieldUrl('tags_editor'))}" title="Edit crawl tags">#${ArchiveBoxUI.escapeHtml(tag)}</a>`),
        ].join('');
        const statsHtml = [
            `<span class="crawl-badge count"><strong>done</strong>${crawl.completed_snapshots || 0}</span>`,
            `<span class="crawl-badge size"><strong>active</strong>${crawl.started_snapshots || 0}</span>`,
            `<span class="crawl-badge"><strong>pending</strong>${crawl.pending_snapshots || 0}</span>`,
            (crawl.cancelled_snapshots || 0) > 0 ? `<span class="crawl-badge"><strong>cancelled</strong>${crawl.cancelled_snapshots}</span>` : '',
        ].join('');

        return `
            <div class="crawl-item" data-crawl-id="${crawl.id || 'unknown'}">
                <div class="crawl-header">
                    <div class="crawl-header-link">
                        <div class="crawl-info">
                            <a class="crawl-label crawl-title-link" href="${ArchiveBoxUI.escapeHtml(adminUrl)}">Crawl #${ArchiveBoxUI.escapeHtml(crawlShortId)} ${ArchiveBoxUI.escapeHtml(startedDate)} started by ${ArchiveBoxUI.escapeHtml(crawl.created_by || 'unknown')}</a>
                            <div class="crawl-badges">${crawlBadges}</div>
                        </div>
                        <div class="crawl-stats">
                            ${statsHtml}
                        </div>
                        ${crawlPidHtml}
                        ${crawlDurationHtml}
                        <span class="status-badge ${crawl.status || 'unknown'}">${crawl.is_paused ? 'paused' : (crawl.status || 'unknown')}</span>
                    </div>
                    ${pauseBtn}
                    ${cancelBtn}
                </div>
                <div class="crawl-progress">
                    <div class="progress-bar-container">
                        <div class="progress-bar crawl ${crawl.status === 'started' && (crawl.progress || 0) === 0 ? 'indeterminate' : ''}"
                             style="width: ${crawl.progress || 0}%"></div>
                    </div>
                </div>
                ${warningHtml}
                <div class="crawl-body">
                    <div class="snapshot-list">
                        ${setupHtml}
                        ${snapshotsHtml}
                        ${queuedSnapshotsNote}
                    </div>
                </div>
            </div>
        `;
    }

    function setOrchestratorState(state, label) {
        const dot = document.getElementById('orchestrator-dot');
        dot.classList.remove('stopped', 'idle', 'running', 'error');
        dot.classList.add(state);
        document.getElementById('orchestrator-text').textContent = label;
        return dot;
    }

    function updateProgress(data) {
        idleMessage.style.color = '';
        function setCount(id, value) {
            const el = document.getElementById(id);
            if (el) el.textContent = Number(value || 0).toLocaleString();
        }
        function setActiveCount(id, value) {
            setCount(id, value);
            const segment = document.getElementById(`${id}-segment`);
            if (segment) segment.style.display = Number(value || 0) > 0 ? '' : 'none';
        }

        // Calculate if there's activity
        const hasActivity = data.active_crawls.length > 0 ||
                           data.crawls_queued > 0 || data.crawls_active > 0 ||
                           data.snapshots_queued > 0 || data.snapshots_active > 0 ||
                           data.archiveresults_queued > 0 || data.archiveresults_active > 0;
        if (hasActivity) {
            idleTicks = 0;
            if (pollDelayMs !== 1000) {
                setPollingDelay(1000);
            }
        } else {
            idleTicks += 1;
            if (idleTicks > 5 && pollDelayMs !== 10000) {
                setPollingDelay(10000);
            }
        }

        // Update orchestrator status - show "Running" only when there are active workers.
        const pidEl = document.getElementById('orchestrator-pid');
        const hasWorkers = data.total_workers > 0;
        let dot = null;

        if (hasWorkers) {
            dot = setOrchestratorState('running', 'Running');
        } else if (!data.orchestrator_running) {
            dot = setOrchestratorState('stopped', 'Runner stopped');
        } else if (hasActivity) {
            dot = setOrchestratorState('idle', 'Idle');
        } else {
            dot = setOrchestratorState('idle', 'Idle');
        }

        if (data.orchestrator_pid) {
            pidEl.textContent = `pid ${data.orchestrator_pid}`;
            pidEl.style.display = 'inline-flex';
        } else {
            pidEl.textContent = '';
            pidEl.style.display = 'none';
        }

        // Pulse the dot to show we got fresh data
        dot.classList.add('flash');
        setTimeout(() => dot.classList.remove('flash'), 300);

        [
            ['crawls-queued', data.crawls_queued],
            ['snapshots-queued', data.snapshots_queued],
            ['downloads-queued', data.downloads_queued],
            ['indexing-queued', data.indexing_queued],
        ].forEach(([id, value]) => setCount(id, value));
        [
            ['crawls-active', data.crawls_active],
            ['snapshots-active', data.snapshots_active],
            ['downloads-active', data.downloads_active],
            ['indexing-active', data.indexing_active],
        ].forEach(([id, value]) => setActiveCount(id, value));
        updateScreencastPanel(data);

        // Render crawl tree
        if (data.active_crawls.length > 0) {
            idleMessage.style.display = 'none';
            const queuedCrawlsHidden = Number(data.queued_crawls_hidden || 0);
            const queuedCrawlsNote = queuedCrawlsHidden > 0
                ? `<div class="progress-overflow-note">${queuedCrawlsHidden} more queued crawl${queuedCrawlsHidden === 1 ? '' : 's'} not shown</div>`
                : '';
            replaceCrawlTree(data.active_crawls.map(c => renderCrawl(c)).join('') + queuedCrawlsNote);
        } else if (hasActivity) {
            idleMessage.style.display = 'none';
            replaceCrawlTree(`
                <div class="idle-message">
                    ${data.snapshots_active || 0} snapshots processing, ${data.archiveresults_active || 0} extractors running
                </div>
            `);
        } else {
            idleMessage.style.display = '';
            // Build the URL for recent crawls (last 24 hours)
            var yesterday = new Date(Date.now() - 24*60*60*1000).toISOString().split('T')[0];
            var recentUrl = '/admin/crawls/crawl/?created_at__gte=' + yesterday + '&o=-1';
            idleMessage.innerHTML = `No active crawls (${data.crawls_queued || 0} pending, ${data.crawls_active || 0} started, <a href="${recentUrl}" style="color: #58a6ff;">${data.crawls_recent || 0} recent</a>)`;
            replaceCrawlTree('');
        }

        updateDurationBadges();
    }

    const progressEndpoint = monitor.dataset.progressEndpoint || '/progress.json';

    function fetchProgress() {
        fetch(progressEndpoint, { credentials: 'same-origin' })
            .then(response => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    console.error('Progress API error:', data.error, data.traceback);
                    setOrchestratorState('error', 'Backend not responding');
                    idleMessage.textContent = 'API Error: ' + data.error;
                    idleMessage.style.color = '#f85149';
                    return;
                }
                monitor.classList.toggle('is-guest', data.is_admin === false);
                updateProgress(data);
            })
            .catch(error => {
                console.error('Progress fetch error:', error);
                setOrchestratorState('error', 'Backend not responding');
                idleMessage.textContent = 'Fetch Error: ' + error.message;
                idleMessage.style.color = '#f85149';
            });
    }

    function startPolling() {
        if (pollInterval) return;
        fetchProgress();
        pollInterval = setInterval(fetchProgress, pollDelayMs);
    }

    function stopPolling() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    }

    function setPollingDelay(ms) {
        pollDelayMs = ms;
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = setInterval(fetchProgress, pollDelayMs);
        }
    }

    function setCollapsedState(collapsed) {
        isCollapsed = collapsed;
        if (isCollapsed) {
            monitor.classList.add('collapsed');
            collapseBtn.textContent = 'Details';
            collapseBtn.setAttribute('aria-expanded', 'false');
        } else {
            monitor.classList.remove('collapsed');
            collapseBtn.textContent = 'Hide';
            collapseBtn.setAttribute('aria-expanded', 'true');
        }
    }

    function setActionButtonState(btn, busy) {
        if (!btn) return;
        const label = btn.dataset.label || '✕';
        btn.disabled = !!busy;
        btn.classList.toggle('is-busy', !!busy);
        btn.textContent = busy ? '…' : label;
    }

    function patchProgressItem(url, action, btn, errorLabel) {
        if (!url || !action) return;
        setActionButtonState(btn, true);

        fetch(ArchiveBoxUI.apiUrl(url), {
            method: 'PATCH',
            headers: ArchiveBoxUI.apiHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify({ action: action }),
        })
        .then(response => response.json().then(data => ({response, data})))
        .then(({response, data}) => {
            if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
            if (data.error) console.error(`${errorLabel} error:`, data.error);
            fetchProgress();
        })
        .catch(error => {
            console.error(`${errorLabel} failed:`, error);
            setActionButtonState(btn, false);
        });
    }

    // Collapse toggle
    collapseBtn.addEventListener('click', function(event) {
        event.stopPropagation();
        setCollapsedState(!isCollapsed);
    });
    monitor.querySelector('.header-bar').addEventListener('click', function(event) {
        if (event.target.closest('button, a, input, select, textarea, [role="button"]')) return;
        if (isCollapsed) setCollapsedState(false);
    });

    crawlTree.addEventListener('click', function(event) {
        const actionBtn = event.target.closest('.crawl-action-btn');
        if (actionBtn) {
            event.preventDefault();
            event.stopPropagation();
            patchProgressItem(
                actionBtn.dataset.crawlId ? `/api/v1/crawls/crawl/${actionBtn.dataset.crawlId}` : '',
                actionBtn.dataset.crawlAction,
                actionBtn,
                'Crawl action',
            );
            return;
        }
        const btn = event.target.closest('.cancel-item-btn');
        if (!btn) return;
        event.preventDefault();
        event.stopPropagation();

        const cancelType = btn.dataset.cancelType;
        if (cancelType === 'crawl') {
            patchProgressItem(btn.dataset.crawlId ? `/api/v1/crawls/crawl/${btn.dataset.crawlId}` : '', 'cancel', btn, 'Cancel crawl');
        } else if (cancelType === 'snapshot') {
            patchProgressItem(btn.dataset.snapshotId ? `/api/v1/core/snapshot/${btn.dataset.snapshotId}` : '', 'cancel', btn, 'Cancel snapshot');
        }
    });

    // Apply initial state
    setCollapsedState(isCollapsed);

    // Start polling when page loads
    startPolling();
    setInterval(updateDurationBadges, 1000);

    // Pause polling when tab is hidden
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            stopPolling();
        } else {
            startPolling();
        }
    });
})();
