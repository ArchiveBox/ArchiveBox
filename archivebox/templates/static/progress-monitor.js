(function() {
    const monitor = document.getElementById('progress-monitor');
    // Opening the files view can remove the panel before this deferred script runs.
    if (!monitor) return;
    const collapseBtn = document.getElementById('progress-collapse');
    const treeContainer = document.getElementById('tree-container');
    const crawlTree = document.getElementById('crawl-tree');
    const idleMessage = document.getElementById('idle-message');
    const screencastPanel = document.getElementById('screencast-panel');

    let pollInterval = null;
    let pollDelayMs = 1000;
    let latestMetrics = null;
    let latestCollection = null;
    let renderedMetricsSample = null;
    // Hook and capture timings come from the server's clock. Measure elapsed
    // time against it, not the browser's, which may run ahead or behind.
    let serverClockOffsetMs = 0;
    function serverNowMs() {
        return Date.now() + serverClockOffsetMs;
    }
    let idleTicks = 0;
    // The panel opens on every page as the viewer last left it; the page's own
    // default applies only until they first toggle it.
    const collapsedStorageKey = 'progress-monitor-collapsed';
    let isCollapsed = monitor.classList.contains('collapsed');
    function rememberCollapsed(collapsed) {
        try { localStorage.setItem(collapsedStorageKey, String(collapsed)); } catch (e) {}
    }
    const snapshotMedia = new Map();

    function getApiKey() {
        return (window.ARCHIVEBOX_API_KEY || '').trim();
    }

    function buildApiUrl(path) {
        const apiKey = getApiKey();
        if (!apiKey) return path;
        const sep = path.includes('?') ? '&' : '?';
        return `${path}${sep}api_key=${encodeURIComponent(apiKey)}`;
    }

    function buildApiHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const apiKey = getApiKey();
        if (apiKey) headers['X-ArchiveBox-API-Key'] = apiKey;
        const csrfToken = getCSRFToken();
        if (csrfToken) headers['X-CSRFToken'] = csrfToken;
        return headers;
    }
    function getCSRFToken() {
        const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input && input.value) return input.value;
        const cookie = document.cookie.split('; ').find(part => part.startsWith('csrftoken='));
        return cookie ? decodeURIComponent(cookie.slice('csrftoken='.length)) : '';
    }
    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
        }[char]));
    }
    function escapeAttr(value) {
        return escapeHtml(value).replace(/`/g, '&#96;');
    }
    function stableSnapshotMedia(snapshot) {
        // The progress endpoint can briefly omit media URLs while ArchiveResult
        // rows settle. Keep displaying the last *loaded* image while probing
        // new URLs offscreen: an output URL may 404 until its capture finishes.
        const snapshotId = String(snapshot.id || '');
        const media = snapshotMedia.get(snapshotId) || {};
        if (snapshot.favicon_url && snapshot.favicon_url !== media.favicon_url) {
            media.favicon_url = snapshot.favicon_url;
            media.favicon_next_probe = 0;
            media.favicon_retry_delay = 5000;
        }
        if (snapshot.preview_url) {
            if (snapshot.preview_url !== media.preview_url) {
                media.preview_url = snapshot.preview_url;
                media.preview_next_probe = 0;
                media.preview_retry_delay = 5000;
            }
            media.preview_link = snapshot.preview_link || media.preview_link;
        }
        if (snapshotId) snapshotMedia.set(snapshotId, media);
        probeSnapshotImage(media, 'favicon');
        probeSnapshotImage(media, 'preview');
        return media;
    }
    function probeSnapshotImage(media, kind) {
        const url = media[`${kind}_url`];
        if (!url || media[`${kind}_ready_url`] === url || media[`${kind}_probing`] === url || Date.now() < (media[`${kind}_next_probe`] || 0)) return;
        media[`${kind}_probing`] = url;
        const probe = new Image();
        probe.onload = function() {
            if (media[`${kind}_url`] !== url) return;
            media[`${kind}_ready_url`] = url;
            media[`${kind}_ready_src`] = probe.src;
            media[`${kind}_probing`] = '';
            media[`${kind}_retry_delay`] = 5000;
        };
        probe.onerror = function() {
            if (media[`${kind}_url`] !== url) return;
            media[`${kind}_probing`] = '';
            const delay = media[`${kind}_retry_delay`] || 5000;
            media[`${kind}_next_probe`] = Date.now() + delay;
            media[`${kind}_retry_delay`] = Math.min(delay * 2, 30000);
        };
        // A previous 404 may be cached. Bust only the background probe URL;
        // the visible card keeps its loaded image or fixed-size placeholder.
        const probeUrl = new URL(url, window.location.href);
        probeUrl.searchParams.set('progress_retry', String(Date.now()));
        probe.src = probeUrl.href;
    }
    function sameProgressNode(current, next) {
        if (current.nodeType !== next.nodeType) return false;
        if (current.nodeType !== Node.ELEMENT_NODE) return true;
        if (current.tagName !== next.tagName) return false;
        for (const key of ['crawlId', 'snapshotId', 'hookKey', 'stableMedia']) {
            if ((current.dataset[key] || next.dataset[key]) && current.dataset[key] !== next.dataset[key]) return false;
        }
        return (current.className || '').split(' ')[0] === (next.className || '').split(' ')[0];
    }
    function reconcileProgressNode(current, next) {
        if (current.nodeType === Node.TEXT_NODE) {
            if (current.textContent !== next.textContent) current.textContent = next.textContent;
            return;
        }
        if (current.nodeType !== Node.ELEMENT_NODE) return;
        // Never detach a loaded image on a poll. Its URL only changes when the
        // progress API reports a new output; keep a successful fallback too.
        if (current.dataset.stableMedia && current.dataset.mediaUrl === next.dataset.mediaUrl) {
            if (current.tagName === 'A' && current.getAttribute('href') !== next.getAttribute('href')) {
                current.setAttribute('href', next.getAttribute('href'));
            }
            return;
        }
        for (const attr of Array.from(current.attributes)) {
            if (!next.hasAttribute(attr.name)) current.removeAttribute(attr.name);
        }
        for (const attr of Array.from(next.attributes)) {
            if (current.getAttribute(attr.name) !== attr.value) current.setAttribute(attr.name, attr.value);
        }
        reconcileProgressChildren(current, next);
    }
    function reconcileProgressChildren(current, next) {
        let position = 0;
        const nextNodes = Array.from(next.childNodes);
        while (position < nextNodes.length) {
            const nextChild = nextNodes[position];
            const child = current.childNodes[position];
            if (!child) {
                current.appendChild(nextChild);
            } else if (sameProgressNode(child, nextChild)) {
                reconcileProgressNode(child, nextChild);
            } else {
                const laterNext = nextNodes.slice(position + 1);
                const neededLater = laterNext.some(node => sameProgressNode(child, node));
                const separator = child.nodeType === Node.TEXT_NODE && !child.textContent.trim();
                const hasLaterMatch = (!neededLater || separator)
                    && Array.from(current.childNodes).slice(position + 1).some(node => sameProgressNode(node, nextChild));
                if (neededLater && !hasLaterMatch) {
                    // A new optional node (such as a favicon) precedes the old
                    // one. Insert it without detaching the old loaded image.
                    current.insertBefore(nextChild, child);
                } else if (hasLaterMatch) {
                    // Remove the obsolete node and retry this position. Whitespace
                    // or another keyed row may still precede the matching node.
                    child.remove();
                    continue;
                } else {
                    child.replaceWith(nextChild);
                }
            }
            position += 1;
        }
        while (current.childNodes.length > position) current.lastChild.remove();
    }
    function replaceCrawlTree(html) {
        const template = document.createElement('template');
        template.innerHTML = html;
        reconcileProgressChildren(crawlTree, template.content);
    }
    window.failedProgressImage = function(img) {
        const snapshotId = img.closest('.snapshot-item')?.dataset.snapshotId;
        const media = snapshotMedia.get(snapshotId);
        if (media) {
            for (const kind of ['favicon', 'preview']) {
                if (media[`${kind}_ready_src`] === img.src) {
                    media[`${kind}_ready_url`] = '';
                    media[`${kind}_ready_src`] = '';
                    media[`${kind}_next_probe`] = 0;
                }
            }
        }
        const preview = img.closest('.snapshot-preview');
        if (preview) {
            preview.classList.add('placeholder');
            preview.innerHTML = '<span>▤</span>';
        } else img.remove();
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

    let badgeIcons = new Map();

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
        return formatDuration((serverNowMs() - startedMs) / 1000);
    }

    function renderDurationBadge(startedAt) {
        const text = durationText(startedAt);
        if (!text) return '';
        return `<span class="duration-badge" data-started-at="${escapeAttr(startedAt)}" title="Duration">${escapeHtml(text)}</span>`;
    }

    // Hooks run from under a second to many minutes. A log scale keeps both
    // ends distinguishable; anything past five minutes simply hits the cap.
    const hookScaleMaxSeconds = 300;
    function hookWidthScale(seconds) {
        return Math.min(1, Math.log1p(Math.max(0, seconds)) / Math.log1p(hookScaleMaxSeconds));
    }

    // One identity per hook within its snapshot or crawl setup, the same whether
    // its row came from the Process or the ArchiveResult, so each hook keeps one
    // badge node across polls and never inherits another hook's cell.
    function hookKeyFor(scopeId, extractor) {
        return `${scopeId}|${extractor.plugin || ''}|${extractor.label || extractor.hook_name || ''}`;
    }

    // A hook's duration only ever grows. Running hooks are extrapolated between
    // polls, so a finish is seen up to a poll late and its recorded span is a
    // little shorter than what was already shown: keep the longest shown.
    const hookSeconds = new Map();
    function shownHookSeconds(hookKey, seconds) {
        const shown = Math.max(hookSeconds.get(hookKey) || 0, seconds);
        hookSeconds.set(hookKey, shown);
        return shown;
    }

    // Badges keep the slot they first appeared in: unseen hooks are appended in
    // execution order (hook names start with their run priority), never inserted.
    const hookOrder = new Map();
    let nextHookOrder = 0;
    function orderedHooks(scopeId, extractors) {
        const keyed = extractors.map((extractor) => ({extractor, key: hookKeyFor(scopeId, extractor)}));
        keyed.filter(({key}) => !hookOrder.has(key))
            .sort((a, b) => (a.extractor.hook_name || a.extractor.plugin || '').localeCompare(b.extractor.hook_name || b.extractor.plugin || ''))
            .forEach(({key}) => hookOrder.set(key, nextHookOrder++));
        return keyed.sort((a, b) => hookOrder.get(a.key) - hookOrder.get(b.key));
    }

    function pruneHookState() {
        const scopes = new Set(Array.from(crawlTree.querySelectorAll('.extractor-list[data-hook-scope]'), (list) => list.dataset.hookScope));
        for (const state of [hookSeconds, hookOrder]) {
            for (const hookKey of state.keys()) {
                if (!scopes.has(hookKey.split('|')[0])) state.delete(hookKey);
            }
        }
    }

    function hookSecondsText(seconds) {
        // formatDuration floors to whole seconds; most hooks finish in less.
        return seconds < 10 ? `${Math.max(0, seconds).toFixed(1)}s` : formatDuration(seconds);
    }

    // While running, count whole seconds so the tick reads steadily.
    function hookCellTime(seconds, running) {
        return running && seconds < 10 ? `${Math.floor(seconds)}s` : hookSecondsText(seconds);
    }

    function hookTimingTitle(baseTitle, seconds, running, timeout) {
        if (running) return `${baseTitle}\nrunning ${hookSecondsText(seconds)}${timeout ? ` of ${timeout}s timeout` : ''}`;
        return `${baseTitle}\ntook ${hookSecondsText(seconds)}`;
    }

    function updateDurationBadges() {
        document.querySelectorAll('#progress-monitor .duration-badge[data-started-at]').forEach((badge) => {
            const text = durationText(badge.dataset.startedAt);
            if (text) badge.textContent = text;
        });
        // Running hooks grow every tick from their start time, between polls.
        document.querySelectorAll('#progress-monitor .extractor-badge[data-started-at]').forEach((badge) => {
            const startedMs = Date.parse(badge.dataset.startedAt);
            if (!Number.isFinite(startedMs)) return;
            const seconds = shownHookSeconds(badge.dataset.hookKey, (serverNowMs() - startedMs) / 1000);
            badge.style.setProperty('--hook-scale', hookWidthScale(seconds).toFixed(3));
            const time = badge.querySelector('.badge-time');
            if (time) time.textContent = hookCellTime(seconds, true);
            badge.title = hookTimingTitle(badge.dataset.hookTitle || '', seconds, true, Number(badge.dataset.timeout) || 0);
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
        // Only a live snapshot target (set below) keeps the frame timer running.
        delete screencastPanel.dataset.desiredFrameKey;
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
                <a class="screencast-frame" href="${escapeAttr(crawlUrl)}" title="Open crawl admin">
                    <span class="screencast-placeholder ${escapeAttr(target.state)}">
                        <span class="screencast-placeholder-icon">${escapeHtml(target.icon)}</span>
                        <span class="screencast-placeholder-title">${escapeHtml(target.title)}</span>
                        <span class="screencast-placeholder-subtitle">${escapeHtml(target.subtitle)}</span>
                    </span>
                </a>
                <a class="screencast-caption" href="${escapeAttr(crawlUrl)}" title="Open crawl admin">
                    <span class="screencast-dot ${escapeAttr(target.state)}"></span>
                    <span class="screencast-text">
                        <span class="screencast-title">${escapeHtml(target.title)}</span>
                        <span class="screencast-url">Crawl setup</span>
                    </span>
                </a>
            `;
            return;
        }
        // Give the preview a layout box before the first image is requested;
        // otherwise a panel below the visible tree could keep fetching frames.
        screencastPanel.classList.add('visible');
        if (!frameOnScreen) return;
        const snapshot = target.snapshot;
        const adminUrl = snapshot.admin_url || `/admin/core/snapshot/${snapshot.id || 'unknown'}/change/`;
        const linkUrl = snapshot.screencast_link || snapshot.view_url || adminUrl;
        const titleText = snapshot.title || formatUrl(snapshot.full_url || snapshot.url);
        const urlText = snapshot.full_url || snapshot.url || '';
        const newUrl = snapshot.screencast_url;
        const snapshotKey = `${target.crawl?.id || ''}|${snapshot.id || ''}`;
        screencastPanel.dataset.desiredFrameKey = snapshotKey;
        screencastPanel.dataset.frameUrl = newUrl;

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
                    if (!detailsVisible() || !frameOnScreen || screencastPanel.dataset.desiredFrameKey !== snapshotKey) return;
                    screencastPanel.dataset.mode = 'frame';
                    screencastPanel.dataset.key = '';
                    screencastPanel.dataset.currentFrameSrc = newUrl;
                    screencastPanel.dataset.currentFrameKey = snapshotKey;
                    screencastPanel.innerHTML = `
                        <a class="screencast-frame" href="${escapeAttr(linkUrl)}" title="Open active snapshot">
                            <img src="${escapeAttr(newUrl)}" alt="" decoding="async" loading="eager">
                        </a>
                        <a class="screencast-caption" href="${escapeAttr(adminUrl)}" title="Open snapshot admin">
                            <span class="screencast-dot"></span>
                            <span class="screencast-text">
                                <span class="screencast-title">${escapeHtml(titleText)}</span>
                                <span class="screencast-url">${escapeHtml(urlText)}</span>
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
        if (screencastPanel.dataset.currentFrameKey !== snapshotKey) loadScreencastFrame(newUrl, snapshotKey);
    }

    // Swap in the next frame only once it has decoded, so the panel never flashes.
    function loadScreencastFrame(newUrl, snapshotKey) {
        if (screencastPanel.dataset.currentFrameSrc === newUrl || screencastPanel.dataset.pendingFrameSrc) return;
        screencastPanel.dataset.pendingFrameSrc = newUrl;
        screencastPanel.dataset.pendingFrameKey = snapshotKey;
        const nextFrame = new Image();
        nextFrame.decoding = 'async';
        nextFrame.onload = () => {
            (nextFrame.decode ? nextFrame.decode() : Promise.resolve()).catch(() => {}).finally(() => {
                if (screencastPanel.dataset.pendingFrameSrc !== newUrl) return;
                delete screencastPanel.dataset.pendingFrameSrc;
                delete screencastPanel.dataset.pendingFrameKey;
                if (!detailsVisible() || !frameOnScreen || screencastPanel.dataset.desiredFrameKey !== snapshotKey) return;
                const currentImg = screencastPanel.querySelector('.screencast-frame img');
                if (!currentImg) return;
                nextFrame.alt = '';
                nextFrame.loading = 'eager';
                nextFrame.style.opacity = '1';
                currentImg.replaceWith(nextFrame);
                screencastPanel.dataset.currentFrameSrc = newUrl;
                screencastPanel.dataset.currentFrameKey = snapshotKey;
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

    function renderExtractor(extractor, hookKey) {
        const status = extractor.status || 'queued';
        // Result rows name the hook without its extension (…daemon.bg), process rows with it.
        const background = /\.bg(\.|$)/.test(extractor.hook_name || '');
        // A running hook's icon is a CSS spinner; every glyph fits one fixed slot.
        const icon = status === 'started' ? '' :
                    status === 'succeeded' ? '✓' :
                    status === 'failed' ? '✕' :
                    status === 'backoff' ? '↻' :
                    status === 'skipped' ? '–' :
                    status === 'noresults' ? '∅' : (badgeIcons.get(extractor.plugin) || '•');
        const href = extractor.output_url || extractor.admin_url || '';
        const hrefAttr = href ? ` href="${escapeAttr(href)}"` : '';
        const baseTitle = (extractor.output_path
            ? `${extractor.plugin || 'output'}: ${extractor.output_path}`
            : `${extractor.plugin || 'hook'}${extractor.hook_name ? `: ${extractor.hook_name}` : ''}`)
            + (status === 'started' && extractor.pid ? `\npid ${extractor.pid}` : '');
        const startedMs = status === 'started' ? Date.parse(extractor.started_at || '') : NaN;
        const running = Number.isFinite(startedMs);
        const rawSeconds = running ? (serverNowMs() - startedMs) / 1000 : extractor.elapsed;
        const timed = typeof rawSeconds === 'number';
        const seconds = timed ? shownHookSeconds(hookKey, rawSeconds) : null;
        const title = timed ? hookTimingTitle(baseTitle, seconds, running, extractor.timeout) : baseTitle;
        const timingAttrs = (timed ? ` style="--hook-scale: ${hookWidthScale(seconds).toFixed(3)};"` : '')
            + (running ? ` data-started-at="${escapeAttr(extractor.started_at)}" data-hook-title="${escapeAttr(baseTitle)}" data-timeout="${escapeAttr(extractor.timeout || '')}"` : '');

        // Always an <a> (a plain one without href) so a hook's node is never
        // swapped for another element when its output link appears.
        return `<a class="extractor-badge ${status}${background ? ' bg' : ''}" data-hook-key="${escapeAttr(hookKey)}"${hrefAttr} title="${escapeAttr(title)}"${timingAttrs}><span class="badge-icon">${icon}</span><span class="badge-label">${escapeHtml(extractor.label || extractor.plugin || 'unknown')}</span><span class="badge-time">${timed ? hookCellTime(seconds, running) : ''}</span><span class="badge-bar"></span></a>`;
    }

    function renderExtractorList(scopeId, extractors) {
        return `<div class="extractor-list" data-hook-scope="${escapeAttr(scopeId)}">${orderedHooks(scopeId, extractors).map(({extractor, key}) => renderExtractor(extractor, key)).join('')}</div>`;
    }

    function renderSnapshot(snapshot, crawlId) {
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
        // Started captures can be cancelled too: sealing them makes the
        // runner's next lease renewal fail and stop that capture.
        const canCancel = snapshot.status === 'queued' || snapshot.status === 'started';
        const cancelBtn = canCancel
            ? `<button class="cancel-item-btn" data-cancel-type="snapshot" data-snapshot-id="${snapshot.id}" data-label="✕" title="Cancel snapshot">✕</button>`
            : '';
        // Queued snapshots with nothing to report yet render as one compact
        // line; the status badge and cancel button already convey the state.
        const isIdleQueued = snapshot.status === 'queued'
            && !((snapshot.total_plugins || 0) > 0)
            && !['crashed', 'stalled', 'cancelled'].includes(snapshot.worker_state);
        // A STARTED capture with no live hook and no lease is not running: it
        // starts over from scratch when its crawl runs again. Show it with the
        // queue, not as an active capture with stale hook badges.
        const isInterruptedWaiting = snapshot.status === 'started' && snapshot.worker_state === 'interrupted';
        if (isIdleQueued || isInterruptedWaiting) {
            const queuedUrl = snapshot.full_url || snapshot.url || '(no URL)';
            const queuedTooltip = (snapshot.title && snapshot.title !== queuedUrl ? `${snapshot.title}\n${queuedUrl}` : queuedUrl)
                + (isInterruptedWaiting ? '\nInterrupted: will be captured again from scratch when its crawl runs' : '');
            const queuedBadge = isInterruptedWaiting ? 'interrupted' : 'queued';
            return `
            <div class="snapshot-item queued-compact" data-snapshot-id="${escapeAttr(snapshot.id || '')}">
                <div class="snapshot-header">
                    <a class="snapshot-header-link" href="${adminUrl}" title="${escapeAttr(queuedTooltip)}">
                        <span class="snapshot-queued-icon"></span>
                        <span class="snapshot-queued-label">${escapeHtml(queuedUrl)}</span>
                        <span class="status-badge ${queuedBadge}">${queuedBadge}</span>
                    </a>
                    ${cancelBtn}
                </div>
            </div>
        `;
        }
        const snapshotPidHtml = snapshot.worker_pid ? `<span class="pid-label compact">pid ${snapshot.worker_pid}</span>` : '';
        const snapshotDurationHtml = renderDurationBadge(snapshot.started);
        const titleText = snapshot.title || formatUrl(snapshot.full_url || snapshot.url);
        const urlText = snapshot.full_url || snapshot.url || '';
        const media = stableSnapshotMedia(snapshot);
        const faviconHtml = media.favicon_ready_src
            ? `<img class="snapshot-favicon" data-stable-media="favicon" data-media-url="${escapeAttr(media.favicon_ready_url)}" src="${escapeAttr(media.favicon_ready_src)}" alt="" decoding="async" loading="lazy" onload="this.dataset.loaded='1'" onerror="failedProgressImage(this)">`
            : '';
        const previewSrc = media.preview_ready_src || media.favicon_ready_src;
        const previewMediaUrl = media.preview_ready_src ? media.preview_ready_url : media.favicon_ready_url;
        const previewHtml = previewSrc
            ? `<a class="snapshot-preview" data-stable-media="preview" data-media-url="${escapeAttr(previewMediaUrl)}" href="${escapeAttr(media.preview_link || snapshot.view_url || adminUrl)}" title="Open snapshot output"><img src="${escapeAttr(previewSrc)}" alt="" decoding="async" loading="lazy" onload="this.dataset.loaded='1'" onerror="failedProgressImage(this)"><span class="snapshot-preview-loading">▤</span></a>`
            : `<a class="snapshot-preview placeholder" href="${escapeAttr(snapshot.view_url || adminUrl)}" title="Open snapshot"><span>${statusIcon}</span></a>`;

        let extractorHtml = '';
        if (snapshot.all_plugins && snapshot.all_plugins.length > 0) {
            extractorHtml = renderExtractorList(String(snapshot.id), snapshot.all_plugins);
        }

        const hasProcessEntries = (snapshot.all_plugins || []).some(extractor => extractor.source === 'process');
        const hasArchiveResults = (snapshot.all_plugins || []).some(extractor => extractor.source === 'archiveresult');
        const processOnly = hasProcessEntries && !hasArchiveResults;
        const runningProcessCount = (snapshot.all_plugins || []).filter(extractor => extractor.source === 'process' && extractor.status === 'started').length;
        const failedProcessCount = (snapshot.all_plugins || []).filter(extractor => extractor.source === 'process' && extractor.status === 'failed').length;
        // A STARTED row with no live hook and no runner lease was interrupted;
        // it is captured again from scratch, so nothing is counting up.
        const isInterrupted = snapshot.worker_state === 'interrupted';
        const snapshotBadge = isInterrupted ? 'interrupted' : (snapshot.status || 'unknown');
        const snapshotMeta = isInterrupted
            ? '<span style="color:#d29922">Interrupted, waiting to be captured again from scratch</span>'
            : (snapshot.total_plugins || 0) > 0
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
            <div class="snapshot-item" data-snapshot-id="${escapeAttr(snapshot.id || '')}">
                <div class="snapshot-header">
                    ${previewHtml}
                    <a class="snapshot-header-link" href="${adminUrl}">
                        <div class="snapshot-info">
                            <div class="snapshot-title-line">
                                ${faviconHtml}
                                <span class="snapshot-title">${escapeHtml(titleText)}</span>
                            </div>
                            <div class="snapshot-url">${escapeHtml(urlText)}</div>
                            <div class="snapshot-meta">
                                ${snapshotMeta}
                            </div>
                        </div>
                        ${snapshotPidHtml}
                        ${snapshotDurationHtml}
                        <span class="status-badge ${snapshotBadge}">${snapshotBadge}</span>
                    </a>
                    ${cancelBtn}
                </div>
                <div class="snapshot-progress">
                    <div class="progress-bar-container">
                        <div class="progress-bar snapshot ${((processOnly && runningProcessCount > 0) || (snapshot.status === 'started' && !isInterrupted && (snapshot.progress || 0) === 0)) ? 'indeterminate' : ''}"
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
            const hrefAttr = href ? ` href="${escapeAttr(href)}"` : '';
            const titleAttr = title ? ` title="${escapeAttr(title)}"` : '';
            return `<${tag} class="crawl-badge ${className}"${hrefAttr}${titleAttr}><strong>${escapeHtml(label)}</strong>${escapeHtml(value)}</${tag}>`;
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

        let snapshotsHtml = '';
        if (crawl.active_snapshots && crawl.active_snapshots.length > 0) {
            snapshotsHtml = crawl.active_snapshots.map(s => renderSnapshot(s, crawl.id)).join('');
        }
        const queuedSnapshotsNote = renderOverflowNotes(crawl.hidden_snapshots, 'snapshot', crawlId);
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
                    ${renderExtractorList(`setup-${crawl.id}`, crawl.setup_plugins)}
                </div>
            `;
        }

        // Show warning if crawl is stuck (queued but can't start)
        let warningHtml = '';
        if (crawl.status === 'queued' && !crawl.can_start) {
            warningHtml = `
                <div style="padding: 8px 14px; background: rgba(248, 81, 73, 0.1); border-top: 1px solid #f85149; color: #f85149; font-size: 11px;">
                    Crawl cannot start: ${crawl.urls_preview ? 'unknown error' : 'no URLs'}
                </div>
            `;
        } else if (crawl.is_paused) {
            warningHtml = `
                <div style="padding: 8px 14px; background: rgba(210, 153, 34, 0.1); border-top: 1px solid #d29922; color: #d29922; font-size: 11px;">
                    Crawl is paused. Resume it to continue processing queued snapshots.
                </div>
            `;
        } else if (crawl.status === 'queued' && crawl.retry_at_future) {
            // Queued but retry_at is in future (was claimed by worker, will retry)
            warningHtml = `
                <div style="padding: 8px 14px; background: rgba(88, 166, 255, 0.1); border-top: 1px solid #58a6ff; color: #58a6ff; font-size: 11px;">
                    Trying in ${crawl.seconds_until_retry || 0}s...${crawl.urls_preview ? ` (${escapeHtml(crawl.urls_preview)})` : ''}
                </div>
            `;
        } else if (crawl.status === 'queued' && crawl.total_snapshots === 0) {
            // Queued and waiting to be picked up by worker
            warningHtml = `
                <div style="padding: 8px 14px; background: rgba(210, 153, 34, 0.1); border-top: 1px solid #d29922; color: #d29922; font-size: 11px;">
                    Waiting for the runner to pick up...${crawl.urls_preview ? ` (${escapeHtml(crawl.urls_preview)})` : ''}
                </div>
            `;
        } else if (crawl.status === 'started' && crawl.worker_state === 'crashed') {
            warningHtml = `
                <div style="padding: 8px 14px; background: rgba(248, 81, 73, 0.1); border-top: 1px solid #f85149; color: #f85149; font-size: 11px;">
                    Runner stopped with ${crawl.started_snapshots || 0} active and ${crawl.pending_snapshots || 0} pending snapshots. It will resume when the runner starts again.
                </div>
            `;
        } else if (crawl.worker_state === 'cancelled') {
            warningHtml = `
                <div style="padding: 8px 14px; background: rgba(139, 148, 158, 0.1); border-top: 1px solid #6e7681; color: #8b949e; font-size: 11px;">
                    Crawl was cancelled. ${crawl.cancelled_snapshots || 0} snapshot${(crawl.cancelled_snapshots || 0) === 1 ? '' : 's'} stopped before completion.
                </div>
            `;
        }

        // Show crawl-scale limits and sealed output sizes from DB metadata.
        const currentUrlCount = Math.max(crawl.total_snapshots || 0, crawl.urls_count || 0);
        const maxUrlsText = (crawl.max_urls || 0) > 0 ? crawl.max_urls : 'unlimited';
        const urlLimitText = `${currentUrlCount} / ${maxUrlsText}`;
        const crawlSizeLimitText = `${crawl.crawl_output_size_display || '0 B'} / ${crawl.max_crawl_size_display || 'unlimited'}`;
        const crawlTimeoutText = (crawl.crawl_timeout || 0) > 0 ? `${crawl.crawl_timeout}s` : 'unlimited';
        const snapshotSizeLimitText = `${crawl.avg_snapshot_size_display || '0 B'} / ${crawl.max_snapshot_size_display || 'unlimited'}`;
        const crawlBadges = [
            // Public snapshot viewers get no persona: it names a private login.
            crawl.persona ? crawlBadge('persona', 'Persona Config', crawl.persona, crawl.persona_admin_url, 'Edit persona config') : '',
            crawlBadge('limit', 'depth', crawl.max_depth || 0, adminFieldUrl('max_depth'), 'Edit crawl depth'),
            crawlBadge('limit', 'urls', urlLimitText, adminFieldUrl('max_urls'), 'Edit max URLs'),
            crawlBadge('size', 'crawl size', crawlSizeLimitText, adminFieldUrl('crawl_max_size'), 'Edit max crawl size'),
            crawlBadge('limit', 'time', crawlTimeoutText, adminFieldUrl('crawl_timeout'), 'Edit max crawl time'),
            crawlBadge('size', 'avg snap', snapshotSizeLimitText, adminFieldUrl('snapshot_max_size'), 'Edit max snapshot size'),
            ...(crawl.tags || []).map(tag => `<a class="crawl-badge tag" href="${escapeAttr(adminFieldUrl('tags_editor'))}" title="Edit crawl tags">#${escapeHtml(tag)}</a>`),
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
                            <a class="crawl-label crawl-title-link" href="${escapeAttr(adminUrl)}">Crawl #${escapeHtml(crawlShortId)} ${escapeHtml(startedDate)} started by ${escapeHtml(crawl.created_by || 'unknown')}</a>
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

    // Each truncated section links to the admin list holding the rest.
    function renderOverflowNotes(hidden, noun, crawlId = '') {
        return (hidden || []).map(item => {
            const count = Number(item.count || 0);
            const bucket = crawlId ? `${crawlId.replaceAll('-', '')}:${item.status}` : '';
            const expand = bucket && bucket !== expandedSnapshotBucket
                ? ` data-expand-progress-snapshots="${escapeAttr(bucket)}"` : '';
            const verb = expand || noun !== 'snapshot' ? 'Show' : 'View';
            const suffix = !expand && noun === 'snapshot' ? ' in Snapshots' : '';
            return `<div class="progress-overflow-note"><a href="${escapeAttr(item.url)}"${expand}>${verb} ${count.toLocaleString()} more ${escapeHtml(item.status)} ${noun}${count === 1 ? '' : 's'}${suffix}</a></div>`;
        }).join('');
    }

    function setOrchestratorState(state, label) {
        const dot = document.getElementById('orchestrator-dot');
        dot.classList.remove('stopped', 'idle', 'running', 'error');
        dot.classList.add(state);
        document.getElementById('orchestrator-text').textContent = label;
        return dot;
    }

    function metricBadge(name, text, tooltip, stale = false, sampleTimes = []) {
        const el = document.getElementById(`metric-${name}`);
        if (!el) return;
        el.querySelector('.metric-text').textContent = text;
        el.title = tooltip;
        el.setAttribute('aria-label', `${text}. ${tooltip}`);
        el.classList.toggle('stale', stale);
        if (sampleTimes.some(Boolean)) el.dataset.sampleTimes = JSON.stringify(sampleTimes.filter(Boolean));
    }

    function updateSampleAge(event) {
        const badge = event.target.closest('.metric-badge');
        if (!badge?.dataset.sampleTimes) return;
        const times = JSON.parse(badge.dataset.sampleTimes);
        let index = 0;
        badge.title = badge.title.replace(/Sampled \d+ seconds ago/g, () => `Sampled ${Math.max(0, Math.round(serverNowMs() / 1000 - times[index++]))} seconds ago`);
        badge.setAttribute('aria-label', `${badge.querySelector('.metric-text').textContent}. ${badge.title}`);
    }
    monitor.addEventListener('pointerover', updateSampleAge);
    monitor.addEventListener('focusin', updateSampleAge);

    function updateMetrics(data) {
        const telemetry = document.getElementById('progress-telemetry');
        telemetry.hidden = !data.is_admin;
        if (!data.is_admin) return;
        const metrics = data.metrics;
        const age = ts => ts ? Math.max(0, Math.round(serverNowMs() / 1000 - ts)) : null;
        const stale = !metrics || age(metrics.sampled_at) > 180;
        const system = metrics?.system || {};
        const systemStale = !system.sampled_at || age(system.sampled_at) > 180;
        const sample = [metrics?.sampled_at, system.sampled_at, data.collection?.sampled_at, stale, systemStale].join(':');
        // Samples change about once a minute. Keep their DOM and formatting
        // between capture polls; refresh relative age when a badge is inspected.
        if (sample === renderedMetricsSample) return;
        renderedMetricsSample = sample;
        const shortNumber = value => Number(value.toFixed(1)).toLocaleString();
        const gb = (value, compact = false) => value == null ? '—' : value >= 1e12 ? `${shortNumber(value / 1e12)} TB` : `${Number((value / 1e9).toFixed(compact ? (value < 10e9 ? 1 : 0) : 2))} GB`;
        const sampled = ts => ts ? `Sampled ${age(ts)} seconds ago; refreshes about once a minute.` : 'Waiting for a background sample.';
        const rate = metrics?.throughput;
        metricBadge('throughput', rate ? `${rate.last_hour} URLs/hr${rate.last_hour ? ` ~${shortNumber(60 / rate.last_hour)}min/ea` : ''}` : 'URLs/hr —',
            rate ? `${rate.last_30_minutes} finished in the last 30 minutes. Rolling hour for this view; minutes/snapshot is the completion interval, not individual capture duration. Partial captures count; cancelled snapshots without a completion time do not. ${sampled(metrics.sampled_at)}` : sampled(null), stale, [metrics?.sampled_at]);
        const available = system.container_memory_available_bytes == null ? system.memory_available_bytes : Math.min(system.memory_available_bytes, system.container_memory_available_bytes);
        metricBadge('resources', `${system.load_avg && system.cpu_count > 0 ? `${Math.round(100 * system.load_avg[0] / system.cpu_count)}%` : '—'} · RAM ${gb(available, true)}`,
            `${system.load_avg ? `Host load averages (1 / 5 / 15 minutes): ${system.load_avg.map(n => n.toFixed(2)).join(' / ')} across ${system.cpu_count} CPUs. Percentage is 1-minute load / core count, not CPU utilization; 100% means load equals the number of cores. ` : ''}Available host RAM: ${gb(system.memory_available_bytes)} / ${gb(system.memory_total_bytes)}.${system.container_memory_limit_bytes != null ? ` Container headroom: ${gb(system.container_memory_available_bytes)} / ${gb(system.container_memory_limit_bytes)} limit.` : ''} Swap: ${gb(system.swap_free_bytes)} free / ${gb(system.swap_total_bytes)} total. ${sampled(system.sampled_at)}`, systemStale, [system.sampled_at]);
        const io = system.io;
        metricBadge('io', io ? `I/O ${Math.round(io.operations_per_second).toLocaleString()}/s${io.mean_io_ms == null ? '' : ` · ${shortNumber(io.mean_io_ms)}ms`}` : 'I/O —',
            io ? `Host read + write IOPS, ${(io.bytes_per_second / 1e6).toFixed(1)} MB/s. Mean OS-reported device I/O time per operation (not a network/B2 latency probe). CPU I/O wait: ${io.wait_percent == null ? 'unavailable' : `${io.wait_percent.toFixed(1)}%`}. Averages between samples. ${sampled(system.sampled_at)}` : `I/O rates need two OS samples; unsupported counters remain unavailable. ${sampled(system.sampled_at)}`, systemStale, [system.sampled_at]);
        const archiveBytes = data.collection?.bytes;
        const archiveUnit = archiveBytes > 0 ? Math.min(4, Math.floor(Math.log(archiveBytes) / Math.log(1024))) : 0;
        const archiveSize = archiveBytes == null ? '' : `${shortNumber(archiveBytes / 1024 ** archiveUnit)} ${['B', 'KB', 'MB', 'GB', 'TB'][archiveUnit]}`;
        const freeSpace = `(${gb(system.disk_free_bytes, true)} free)`;
        metricBadge('storage', `${archiveSize || '—'} ${freeSpace}`,
            `Estimated archive size from recorded snapshot sizes visible to your account. ${sampled(data.collection?.sampled_at)} Free space on the collection database filesystem, not remote bucket capacity. ${sampled(system.sampled_at)}`, systemStale, [data.collection?.sampled_at, system.sampled_at]);
        const freeSpaceLabel = document.createElement('small');
        freeSpaceLabel.textContent = freeSpace;
        document.querySelector('#metric-storage .metric-text').replaceChildren(`${archiveSize || '—'} `, freeSpaceLabel);
    }

    function updateProgress(data) {
        const serverMs = Date.parse(data.server_time || '');
        if (Number.isFinite(serverMs)) serverClockOffsetMs = serverMs - Date.now();
        if (data.is_admin) {
            latestMetrics = data.metrics || latestMetrics;
            latestCollection = data.collection || latestCollection;
            data.metrics = latestMetrics;
            data.collection = latestCollection;
        } else {
            latestMetrics = latestCollection = renderedMetricsSample = null;
        }
        updateMetrics(data);
        if (pollMode === 'summary' && data.is_admin) {
            // On a cold server the first request starts the shared sampler.
            // Pick up that first sample promptly, then use the slower cadence.
            if (firstSampleRetries > 0 && (!data.metrics || !data.collection)) {
                firstSampleRetries--;
                setPollingDelay(2000);
            } else {
                firstSampleRetries = 0;
                setPollingDelay(progressEndpoint.searchParams.has('snapshot_id') ? 2000 : 5000);
            }
        }
        idleMessage.style.color = '';

        // Calculate if there's activity
        const hasActivity = (data.active_crawls || []).length > 0 ||
                           data.crawls_queued > 0 || data.crawls_active > 0 ||
                           data.snapshots_queued > 0 || data.snapshots_active > 0 ||
                           data.archiveresults_queued > 0 || data.archiveresults_active > 0;
        if (data.active_crawls && detailsVisible()) {
            idleTicks = hasActivity ? 0 : idleTicks + 1;
            setPollingDelay(idleTicks > 5 ? 10000 : 2000);
        }
        // A passive poll can have fresh runner status without a queue sample.
        const status = document.getElementById('metric-status');
        if (data.snapshots_queued == null) {
            setOrchestratorState(data.orchestrator_running ? 'idle' : 'stopped', data.orchestrator_running ? 'Runner online' : 'Runner stopped');
            status.title = 'Runner status from the latest background check.';
            status.setAttribute('aria-label', status.textContent.trim());
            return;
        }

        // Reuse the existing progress counts; no additional polling or queries.
        const hasWorkers = data.total_workers > 0;
        document.getElementById('metric-throughput').hidden = !hasWorkers;

        if (hasWorkers) {
            setOrchestratorState('running', 'Running');
        } else if (!data.orchestrator_running) {
            setOrchestratorState('stopped', 'Runner stopped');
        } else {
            setOrchestratorState('idle', 'Idle');
        }

        const count = value => value == null ? '—' : Number(value).toLocaleString();
        const hourlyRate = data.metrics?.throughput?.last_hour;
        let queueEta = '';
        if (data.snapshots_queued > 0 && Number.isFinite(hourlyRate) && hourlyRate > 0
            && Date.now() / 1000 - data.metrics.sampled_at <= 180) {
            const minutes = Math.ceil(data.snapshots_queued * 60 / hourlyRate);
            const parts = [
                [Math.floor(minutes / 1440), 'd'],
                [Math.floor(minutes % 1440 / 60), 'hr'],
                [minutes % 60, 'min'],
            ].filter(([value]) => value > 0).map(([value, unit]) => `${value}${unit}`);
            queueEta = ` (~${parts.join(' ')})`;
        }
        document.getElementById('orchestrator-text').textContent = `${count(data.snapshots_active)} - ${count(data.snapshots_queued)} queued${queueEta}`;
        status.title = `${hasWorkers ? 'Running' : data.orchestrator_running ? 'Idle' : 'Runner stopped'}. Snapshots: ${count(data.snapshots_active)} active, ${count(data.snapshots_queued)} queued. Crawl Jobs: ${count(data.crawls_active)} active, ${count(data.crawls_queued)} queued. Downloads: ${count(data.downloads_active)} active, ${count(data.downloads_queued)} queued.${data.orchestrator_pid ? ` Runner PID ${data.orchestrator_pid}.` : ''}`;
        if (data.total_workers == null) {
            status.title = `${data.orchestrator_running ? 'Runner online' : 'Runner stopped'}. ${count(data.snapshots_queued)} queued. Expand for live worker counts.`;
        }
        status.setAttribute('aria-label', `${status.textContent.trim()}. ${status.title}`);
        metricBadge('indexing', `Indexing ${count(data.indexing_active)}${data.indexing_queued ? ` · ${count(data.indexing_queued)} queued` : ''}`,
            `Indexing: ${count(data.indexing_active)} active, ${count(data.indexing_queued)} queued.`);
        document.getElementById('metric-indexing').hidden = !(data.indexing_active || data.indexing_queued);

        // Collapsed polls omit the tree (tree=0); keep the hidden DOM as-is.
        if (!data.active_crawls || !detailsVisible()) return;

        badgeIcons = new Map(Object.entries(data.badge_icons || {}));
        updateScreencastPanel(data);

        // Render crawl tree
        if (data.active_crawls.length > 0) {
            idleMessage.style.display = 'none';
            const queuedCrawlsNote = renderOverflowNotes(data.hidden_crawls, 'crawl');
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

        pruneHookState();
        updateDurationBadges();
    }

    const progressEndpoint = new URL(monitor.dataset.progressEndpoint || '/progress.json', window.location.href);
    progressEndpoint.searchParams.set('poll', '1');
    const detailPanel = monitor.querySelector('.progress-content');
    let onScreen = false;
    let detailOnScreen = false;
    let pollMode;
    let frameOnScreen = false;
    let awayTimer = null;
    let backgroundPolling = false;
    let firstSampleRetries = 2;
    function detailsVisible() {
        return onScreen && detailOnScreen && !isCollapsed && !document.hidden;
    }
    let progressRequestInFlight = false;
    let expandedSnapshotBucket = '';
    let expansionFocus = null;

    function fetchProgress() {
        // Opening a replay replaces the queued snapshot's progress panel.
        // Its interval and already-running fetch must stop using that old DOM.
        if (!monitor.isConnected) {
            stopPolling();
            return;
        }
        // Slow responses must not let the one-second timer queue more work
        // against the same endpoint. Release after errors too so polling recovers.
        if (progressRequestInFlight || (pollMode === 'away' && !backgroundPolling)) return;
        progressRequestInFlight = true;
        const requestStarted = performance.now();
        let httpStatus = null;
        // Bypass the browser cache before transmission: identical live polls in
        // other tabs can otherwise wait on its entry lock despite no-store responses.
        const omittedTree = !detailsVisible();
        const requestedBucket = expandedSnapshotBucket;
        const requestUrl = new URL(progressEndpoint);
        const sampledAt = Math.min(latestMetrics?.sampled_at || 0, latestCollection?.sampled_at || 0);
        if (!sampledAt || serverNowMs() / 1000 - sampledAt >= 60) requestUrl.searchParams.set('metrics', '1');
        if (backgroundPolling) requestUrl.searchParams.set('background', '1');
        if (omittedTree) requestUrl.searchParams.set('tree', '0');
        else if (requestedBucket) requestUrl.searchParams.set('more_snapshots', requestedBucket);
        fetch(requestUrl, { credentials: 'same-origin', cache: 'no-store' })
            .then(response => {
                httpStatus = response.status;
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then(data => {
                if (!monitor.isConnected) {
                    stopPolling();
                    return;
                }
                const responseMs = Math.round(performance.now() - requestStarted);
                metricBadge('web', data.error ? 'Web error' : `${responseMs}ms`, `Last progress request: HTTP ${httpStatus}, ${responseMs} ms including network and JSON transfer. Not total page-load time. Measured ${new Date().toLocaleTimeString()}.`, Boolean(data.error));
                if (data.error) {
                    console.error('Progress API error:', data.error, data.traceback);
                    setOrchestratorState('error', 'Backend not responding');
                    idleMessage.textContent = 'API Error: ' + data.error;
                    idleMessage.style.color = '#f85149';
                    return;
                }
                monitor.classList.toggle('is-guest', data.is_admin === false);
                // An empty live snapshot has no cards to update. Load its final
                // server-rendered results once, without interrupting opened files.
                const emptySnapshot = document.getElementById('snapshot-empty-state');
                // A background heartbeat may see completion too. Wait for the
                // first visible poll before navigating and loading replay outputs.
                if (pollMode !== 'away' && !document.hidden && emptySnapshot && ['queued', 'started', 'paused'].includes(emptySnapshot.dataset.snapshotState)
                    && data.scope?.snapshot_status === 'sealed'
                    && data.scope.snapshot_id.replace(/-/g, '') === progressEndpoint.searchParams.get('snapshot_id')?.replace(/-/g, '')) {
                    stopPolling();
                    window.location.reload();
                    return;
                }
                if (!omittedTree && requestedBucket !== expandedSnapshotBucket) return;
                const restoreExpansionFocus = expansionFocus && document.activeElement === expansionFocus.link;
                updateProgress(data);
                if (expansionFocus?.bucket === requestedBucket && !omittedTree) {
                    if (restoreExpansionFocus && !expansionFocus.link.isConnected) {
                        const crawl = [...crawlTree.querySelectorAll('.crawl-item')].find(item => item.dataset.crawlId.replaceAll('-', '') === requestedBucket.split(':')[0]);
                        const row = [...crawl?.querySelectorAll('.snapshot-item[data-snapshot-id]') || []]
                            .find(item => !expansionFocus.visible.has(item.dataset.snapshotId));
                        row?.querySelector('a')?.focus({ preventScroll: true });
                    }
                    expansionFocus = null;
                }
            })
            .catch(error => {
                if (!monitor.isConnected) {
                    stopPolling();
                    return;
                }
                console.error('Progress fetch error:', error);
                metricBadge('web', httpStatus ? `Web HTTP ${httpStatus}` : 'Web unavailable', `Last progress request failed after ${Math.round(performance.now() - requestStarted)} ms. ${new Date().toLocaleTimeString()}.`, true);
                setOrchestratorState('error', 'Backend not responding');
                idleMessage.textContent = 'Fetch Error: ' + error.message;
                idleMessage.style.color = '#f85149';
            })
            .finally(() => {
                progressRequestInFlight = false;
                // Expanded while a tree-less poll was in flight: load the tree now.
                if (detailsVisible() && pollInterval && (omittedTree || requestedBucket !== expandedSnapshotBucket)) fetchProgress();
            });
    }

    // CDP frames arrive faster than the JSON poll. Refresh the visible frame
    // on its own cheap timer (one local file read per request), never while
    // collapsed, hidden, or still waiting on the previous frame.
    const screencastFrameMs = 1000;
    const screencastFrameInterval = setInterval(() => {
        if (!monitor.isConnected) {
            clearInterval(screencastFrameInterval);
            return;
        }
        if (!detailsVisible() || !frameOnScreen || screencastPanel.dataset.mode !== 'frame') return;
        const currentSrc = screencastPanel.dataset.frameUrl;
        if (!currentSrc || screencastPanel.dataset.currentFrameKey !== screencastPanel.dataset.desiredFrameKey) return;
        const nextUrl = new URL(currentSrc, window.location.href);
        nextUrl.searchParams.set('v', Date.now().toString());
        loadScreencastFrame(nextUrl.toString(), screencastPanel.dataset.desiredFrameKey);
    }, screencastFrameMs);

    function startPolling() {
        if (pollInterval || !monitor.isConnected) return;
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
        if (pollDelayMs === ms) return;
        pollDelayMs = ms;
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = setInterval(fetchProgress, pollDelayMs);
        }
    }

    const metricStrip = monitor.querySelector('.metric-strip');
    const metricBadges = metricStrip.querySelectorAll('.metric-badge');
    function fitMetricBadges() {
        if (!isCollapsed) return;
        // Keep overflow badges in layout so a shorter live value or a wider
        // viewport can reveal them again. Visibility also removes their tab stops.
        const strip = metricStrip.getBoundingClientRect();
        const overflow = Array.from(metricBadges, badge => {
            const box = badge.getBoundingClientRect();
            return box.right > strip.right || box.left < strip.left;
        });
        metricBadges.forEach((badge, index) => badge.classList.toggle('overflows-strip', overflow[index]));
    }
    const badgeObserver = new ResizeObserver(fitMetricBadges);
    badgeObserver.observe(metricStrip);
    metricBadges.forEach(badge => badgeObserver.observe(badge));

    function setCollapsedState(collapsed) {
        isCollapsed = collapsed;
        if (isCollapsed) {
            monitor.classList.add('collapsed');
            collapseBtn.textContent = 'Details';
            collapseBtn.setAttribute('aria-expanded', 'false');
            fitMetricBadges();
        } else {
            monitor.classList.remove('collapsed');
            collapseBtn.textContent = 'Hide';
            collapseBtn.setAttribute('aria-expanded', 'true');
        }
        visibilityChanged();
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

        fetch(buildApiUrl(url), {
            method: 'PATCH',
            headers: buildApiHeaders(),
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

    function toggleDetails() {
        rememberCollapsed(!isCollapsed);
        setCollapsedState(!isCollapsed);
    }
    collapseBtn.addEventListener('click', toggleDetails);
    monitor.addEventListener('click', function(event) {
        // Only blank surfaces toggle. Badges retain their tooltips and the
        // crawl tree, preview and action buttons handle their own interactions.
        if (event.target.matches('.progress-content, .tree-container, #crawl-tree, .idle-message, #progress-monitor')
            && collapseBtn.getClientRects().length) toggleDetails();
    });

    crawlTree.addEventListener('click', function(event) {
        const expansion = event.target.closest('a[data-expand-progress-snapshots]');
        if (expansion && event.button === 0 && !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
            event.preventDefault();
            expandedSnapshotBucket = expansion.dataset.expandProgressSnapshots;
            expansionFocus = {
                link: expansion, bucket: expandedSnapshotBucket,
                visible: new Set(Array.from(expansion.closest('.crawl-item').querySelectorAll('.snapshot-item[data-snapshot-id]'), item => item.dataset.snapshotId)),
            };
            fetchProgress();
            return;
        }
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

    // The template restores the saved geometry before paint. The initial
    // ResizeObserver notification measures all badges after layout.
    visibilityChanged();

    function resumeVisiblePolling() {
        clearTimeout(awayTimer);
        awayTimer = null;
        backgroundPolling = false;
        idleTicks = 0;
        stopPolling();
        // A replay waiting on its snapshot needs prompt completion updates even
        // with details closed. Its status is one authorized primary-key lookup.
        pollDelayMs = detailsVisible() || progressEndpoint.searchParams.has('snapshot_id') ? 2000 : 5000;
        startPolling();
    }

    function visibilityChanged() {
        const mode = detailsVisible() ? 'detail' : onScreen && isCollapsed && !document.hidden ? 'summary' : 'away';
        if (mode === pollMode) return;
        pollMode = mode;
        if (mode !== 'detail') delete screencastPanel.dataset.desiredFrameKey;
        if (mode !== 'away') {
            resumeVisiblePolling();
        } else if (!awayTimer && !backgroundPolling) {
            // Stop detail work immediately. Brief scrolls/tab switches need
            // no replacement request; sustained absences get a cheap heartbeat.
            stopPolling();
            awayTimer = setTimeout(() => {
                awayTimer = null;
                backgroundPolling = true;
                pollDelayMs = 30000;
                startPolling();
            }, 5000);
        }
    }

    const viewportObserver = new IntersectionObserver(entries => {
        for (const entry of entries) {
            const visible = entry.isIntersecting && entry.intersectionRect.width > 0 && entry.intersectionRect.height > 0;
            if (entry.target === screencastPanel) frameOnScreen = visible;
            else if (entry.target === detailPanel) detailOnScreen = visible;
            else onScreen = visible;
        }
        visibilityChanged();
    }, { threshold: [0, 0.001] });
    viewportObserver.observe(monitor);
    viewportObserver.observe(detailPanel);
    viewportObserver.observe(screencastPanel);
    document.addEventListener('visibilitychange', visibilityChanged);
    const durationInterval = setInterval(() => {
        if (!monitor.isConnected) {
            badgeObserver.disconnect();
            viewportObserver.disconnect();
            document.removeEventListener('visibilitychange', visibilityChanged);
            clearTimeout(awayTimer);
            stopPolling();
            clearInterval(durationInterval);
            return;
        }
        if (detailsVisible()) updateDurationBadges();
    }, 1000);
})();
