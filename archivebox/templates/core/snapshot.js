{% load static core_tags %}
const snapshotBaseUrl = "{% snapshot_base_url snapshot %}";
const snapshotFilesUrl = "{% if STATIC_EXPORT %}{% snapshot_url snapshot 'index.jsonl' %}{% else %}{% snapshot_base_url snapshot %}/?files=1{% endif %}";

function tryCenterImageFrame(frame) {
    try {
        const doc = frame.contentDocument || frame.contentWindow.document
        if (!doc || !doc.body || !doc.images || doc.images.length !== 1) {
            return
        }
        const img = doc.images[0]
        doc.documentElement.style.height = '100%'
        doc.body.style.height = '100%'
        doc.documentElement.style.width = '100%'
        doc.body.style.width = '100%'
        doc.body.style.minWidth = '100%'
        doc.body.style.margin = '0'
        doc.body.style.display = 'flex'
        doc.body.style.flexDirection = 'column'
        doc.body.style.alignItems = 'center'
        doc.body.style.justifyContent = 'flex-start'
        doc.body.style.overflowX = 'auto'
        doc.body.style.background = '#fff'
        img.style.maxWidth = '100%'
        img.style.width = 'auto'
        img.style.height = 'auto'
        img.style.maxHeight = 'none'
        img.style.display = 'block'
        img.style.margin = '0 auto'
    } catch (err) {}
}

function resetPreviewFrameSize(frame) {
    const wrapper = document.getElementById('main-frame-wrapper')
    if (!wrapper || !frame) return
    wrapper.style.height = ''
    wrapper.style.overflow = ''
    frame.style.height = ''
}

function fitPreviewFrameToContent(frame) {
    const wrapper = document.getElementById('main-frame-wrapper')
    if (!wrapper || !frame || frame.src.includes('.pdf')) return
    try {
        const doc = frame.contentDocument || frame.contentWindow.document
        if (!doc || !doc.documentElement) return
        const candidates = [
            doc.documentElement,
            doc.body,
            ...doc.querySelectorAll('main, [role="main"], #doc, .ui-content, .markdown-body'),
        ].filter(Boolean)
        const contentHeight = Math.ceil(Math.max(...candidates.map((element) => element.scrollHeight || 0)))
        const minimumHeight = Math.max(window.innerHeight - wrapper.getBoundingClientRect().top, 320)
        if (!Number.isFinite(contentHeight) || contentHeight <= minimumHeight + 4) {
            resetPreviewFrameSize(frame)
            return
        }
        wrapper.style.height = `${contentHeight}px`
        wrapper.style.overflow = 'visible'
        frame.style.height = `${contentHeight}px`
    } catch (err) {
        resetPreviewFrameSize(frame)
    }
}

function attachPreviewFrameHandlers(frame) {
    resetPreviewFrameSize(frame)
    if (new URL(frame.src || 'about:blank', window.location.href).pathname.endsWith('.pdf')) {
        frame.removeAttribute('sandbox')
        frame.src = frame.src + '#toolbar=0'
    }
    frame.onload = function() {
        if (new URL(this.src || 'about:blank', window.location.href).pathname.endsWith('.pdf')) {
            this.removeAttribute('sandbox')
        }
        tryCenterImageFrame(this)
        try {
            // doesnt work if frame origin rules prevent accessing its DOM via JS
            this.contentWindow.scrollTo(0, 0);
        } catch(err) {}
        requestAnimationFrame(() => {
            fitPreviewFrameToContent(this)
            try {
                if (this._archiveboxResizeObserver) this._archiveboxResizeObserver.disconnect()
                this._archiveboxResizeObserver = new ResizeObserver(() => fitPreviewFrameToContent(this))
                this._archiveboxResizeObserver.observe(this.contentDocument.documentElement)
            } catch (err) {}
        })
    }
}

function setPreviewResourcePriority(root, highPriority=false) {
    for (const iframe of root.querySelectorAll('iframe')) {
        iframe.loading = highPriority ? 'eager' : 'lazy'
        iframe.setAttribute('fetchpriority', highPriority ? 'high' : 'low')
        attachPreviewFrameHandlers(iframe)
    }
    for (const img of root.querySelectorAll('img')) {
        img.loading = highPriority ? 'eager' : 'lazy'
        img.decoding = highPriority ? 'sync' : 'async'
        img.setAttribute('fetchpriority', highPriority ? 'high' : 'low')
    }
    for (const video of root.querySelectorAll('video')) {
        video.loading = highPriority ? 'eager' : 'lazy'
        video.setAttribute('preload', highPriority ? 'metadata' : 'none')
    }
}

function prioritizeCardThumbnail(card, highPriority=false) {
    if (!card) {
        return
    }
    setPreviewResourcePriority(card, highPriority)
}

function prepareThumbnailPriorities() {
    const cards = [...document.querySelectorAll('.thumb-card')]
    cards.forEach((card) => prioritizeCardThumbnail(card, card.classList.contains('selected-card')))
}

// un-sandbox iframes showing pdfs (required to display pdf viewer)
document.querySelectorAll('iframe').forEach((frame) => attachPreviewFrameHandlers(frame))

function getPreviewHashValueFromHref(href, normalize=false) {
    if (href == './') {
        return 'all'
    }
    if (!href) {
        return ''
    }
    try {
        const url = new URL(href, window.location.href)
        let path = url.pathname || ''
        if (snapshotBaseUrl) {
            const baseUrl = new URL(snapshotBaseUrl, window.location.href)
            const basePath = (baseUrl.pathname || '').replace(/\/+$/, '')
            if (url.origin === baseUrl.origin && basePath && path.startsWith(`${basePath}/`)) {
                path = path.slice(basePath.length + 1)
            } else {
                path = path.replace(/^\/+/, '')
            }
        } else {
            path = path.replace(/^\/+/, '')
        }
        const searchParams = new URLSearchParams(url.search || '')
        searchParams.delete('preview')
        const search = searchParams.toString()
        const suffix = `${search ? `?${search}` : ''}${url.hash || ''}`
        const value = `${path}${suffix}`.replace(/^\/+/, '')
        return normalize ? value.toLowerCase() : value
    } catch (err) {
        const value = href.replace(/^https?:\/\/[^/]+\/?/, '').replace(/^\/+/, '')
        return normalize ? value.toLowerCase() : value
    }
}

function getPreviewHashValue(link) {
    return getPreviewHashValueFromHref((link && link.getAttribute('href')) || '', true)
}

function resolvePreviewUrl(raw) {
    if (!raw) return ''
    if (raw.startsWith('http://') || raw.startsWith('https://')) return raw
    if (raw.startsWith('//')) return window.location.protocol + raw
    if (!snapshotBaseUrl) return raw
    return snapshotBaseUrl + (raw.startsWith('/') ? raw : `/${raw}`)
}

function isSnapshotRootPreview(urlValue) {
    if (!urlValue || !snapshotBaseUrl) {
        return false
    }
    try {
        const target = new URL(urlValue, window.location.href)
        const base = new URL(snapshotBaseUrl, window.location.href)
        if (target.origin !== base.origin) {
            return false
        }
        const basePath = (base.pathname || '').replace(/\/+$/, '')
        const targetPath = (target.pathname || '').replace(/\/+$/, '')
        return (
            target.search !== "{% if STATIC_EXPORT %}{% else %}?files=1{% endif %}"
            && (
                targetPath === basePath
                || targetPath === `${basePath}/index.html`
                || targetPath === `${basePath}/index.json`
            )
        )
    } catch (err) {
        return false
    }
}

function createMainFrame(previousFrame) {
    const frame = document.createElement('iframe')
    frame.id = 'main-frame'
    frame.name = 'preview'
    frame.className = 'full-page-iframe'
    frame.sandbox = "allow-same-origin allow-top-navigation-by-user-activation allow-scripts allow-forms"
    frame.loading = 'eager'
    frame.setAttribute('fetchpriority', 'high')
    attachPreviewFrameHandlers(frame)
    return frame
}

function ensureMainFrame(forceReplace=false) {
    let frame = document.getElementById('main-frame')
    const wrapper = document.getElementById('main-frame-wrapper')
    if (wrapper && wrapper.querySelector('#snapshot-empty-state')) {
        return null
    }
    if (!frame || forceReplace) {
        const previousFrame = frame
        frame = createMainFrame(previousFrame)
        if (previousFrame && previousFrame.parentNode) {
            try {
                previousFrame.src = 'about:blank'
            } catch (err) {}
            previousFrame.parentNode.replaceChild(frame, previousFrame)
        } else if (wrapper) {
            wrapper.innerHTML = ''
            wrapper.appendChild(frame)
            wrapper.classList.remove('full-page-wrapper')
        }
    }
    const pluginWrapper = document.getElementById('plugin-full-wrapper')
    if (pluginWrapper) {
        pluginWrapper.classList.add('preview-hidden')
    }
    frame.classList.remove('preview-hidden')
    return frame
}

function activateCardPreview(card, link, updateHash=true) {
    if (!card) {
        return false
    }
    prioritizeCardThumbnail(card, true)
    const previewUrl = card.dataset.previewUrl
    const rawTarget = previewUrl || (link ? link.getAttribute('href') : '') || ''
    const target = resolvePreviewUrl(rawTarget)
    if (!target || target.endsWith('#')) {
        return false
    }

    document.querySelectorAll('.selected-card').forEach((selected) => selected.classList.remove('selected-card'))
    card.closest('.thumb-card').classList.add('selected-card')

    const nextSrc = isSnapshotRootPreview(target) ? snapshotFilesUrl : target
    const existingFrame = document.getElementById('main-frame')
    let currentSrc = ''
    try {
        currentSrc = existingFrame ? new URL(existingFrame.getAttribute('src') || existingFrame.src || '', window.location.href).href : ''
    } catch (err) {}
    let nextSrcAbs = nextSrc
    try {
        nextSrcAbs = new URL(nextSrc, window.location.href).href
    } catch (err) {}
    const iframe_elem = ensureMainFrame(currentSrc !== nextSrcAbs)
    // Preview wrappers retain the .pdf path but add ?preview=1.
    // The native PDF renderer must be allowed before navigation,
    // not after a failed sandboxed load has already completed.
    if (new URL(target, window.location.href).pathname.endsWith('.pdf')) {
        iframe_elem.removeAttribute('sandbox')
    } else {
        iframe_elem.sandbox = "allow-same-origin allow-top-navigation-by-user-activation allow-scripts allow-forms"
    }
    if (rawTarget && updateHash) {
        window.location.hash = getPreviewHashValueFromHref(rawTarget)
    }

    if (currentSrc !== nextSrcAbs) {
        iframe_elem.src = nextSrc
    }
    return false
}

function handleCardClick(card, event) {
    if (!event || event.defaultPrevented) {
        return false
    }
    const targetEl = event.target.nodeType === Node.ELEMENT_NODE ? event.target : event.target.parentElement
    if (targetEl && targetEl.closest('[data-no-preview]')) {
        return true
    }
    const link = (targetEl && targetEl.closest('a[target=preview]')) || card.querySelector('a[target=preview]') || card.querySelector('a')
    event.preventDefault()
    if (typeof event.stopPropagation === 'function') {
        event.stopPropagation()
    }
    if (typeof event.stopImmediatePropagation === 'function') {
        event.stopImmediatePropagation()
    }
    return activateCardPreview(card, link)
}

function findPreviewLinkForHash(hashValue) {
    if (!hashValue) {
        return null
    }
    const previewLinks = [...document.querySelectorAll('a[target=preview]')]
    const pathMatch = previewLinks.find((link) => getPreviewHashValue(link) == hashValue)
    if (pathMatch) {
        return pathMatch
    }
    const pluginCard = [...document.querySelectorAll('.thumb-card[data-plugin-name]')].find(
        (card) => (card.dataset.pluginName || '').toLowerCase() == hashValue,
    )
    return pluginCard && pluginCard.querySelector('a[target=preview]')
}

function selectInitialPreview() {
    const selectedPreviewHash = window.location.hash ? decodeURIComponent(window.location.hash.slice(1)).toLowerCase() : ''
    const matchingLink = findPreviewLinkForHash(selectedPreviewHash)
    if (matchingLink) {
        return activateCardPreview(matchingLink.closest('.thumb-card'), matchingLink, false)
    }

    const selectedCard = document.querySelector('.thumb-card.selected-card') || document.querySelector('.thumb-card')
    const selectedLink = selectedCard && (selectedCard.querySelector('a[target=preview]') || selectedCard.querySelector('a'))
    if (selectedCard && selectedLink) {
        return activateCardPreview(selectedCard, selectedLink, false)
    }

    const frame = ensureMainFrame(false)
    const defaultSrc = frame && frame.dataset.defaultSrc
    if (frame && defaultSrc && (!frame.src || frame.src === 'about:blank')) {
        frame.src = defaultSrc
    }
    return false
}

for (const card of [...document.querySelectorAll('.thumb-card')]) {
    card.addEventListener('click', function(event) {
        if (event.target && event.target.closest('a')) {
            return
        }
        handleCardClick(card, event)
    })
    for (const link of card.querySelectorAll('a')) {
        link.addEventListener('click', function(event) {
            handleCardClick(card, event)
        })
    }
}

function hideSnapshotHeader() {
    console.log('Collapsing Snapshot header...')
    document.querySelectorAll('.header-toggle').forEach((toggle) => { toggle.textContent = '▸' })
    document.querySelectorAll('.header-bottom').forEach((header) => { header.hidden = true })
    try {
        localStorage.setItem("archivebox-snapshot-header-visible", "false")
    } catch (e) {
        console.log('Could not use localStorage to persist header collapse state', e)
    }
}
function showSnapshotHeader() {
    console.log('Expanding Snapshot header...')
    document.querySelectorAll('.header-toggle').forEach((toggle) => { toggle.textContent = '▾' })
    document.querySelectorAll('.header-bottom').forEach((header) => { header.hidden = false })
    try {
        localStorage.setItem("archivebox-snapshot-header-visible", "true")
    } catch (e) {
        console.log('Could not use localStorage to persist header collapse state', e)
    }
}
function loadSnapshotHeaderState() {
    // collapse snapshot header if user has previously hidden it
    let snapshotHeaderIsExpanded = 'false'
    try {
        snapshotHeaderIsExpanded = localStorage.getItem("archivebox-snapshot-header-visible") || 'false'
    } catch (e) {
        console.log('Could not use localStorage to get header collapse state', e)
    }
    if (snapshotHeaderIsExpanded === 'false') {
        hideSnapshotHeader()
    }
}
function handleSnapshotHeaderToggle(event) {
    event.preventDefault()
    if ([...document.querySelectorAll('.header-toggle')].some((toggle) => toggle.textContent.includes('▾'))) {
        hideSnapshotHeader()
    } else {
        showSnapshotHeader()
    }
    return true
}

// Hide or show the header once when its title row or collapse icon is clicked.
document.querySelectorAll('.header-toggle-trigger').forEach((trigger) => trigger.addEventListener('click', handleSnapshotHeaderToggle))

// check URL for hash e.g. #git and load relevant preview
selectInitialPreview()
prepareThumbnailPriorities()
loadSnapshotHeaderState()



// hide all preview iframes on small screens
// if (window.innerWidth < 1091) {
//     jQuery('.card a[target=preview]').attr('target', '_self')
// }
