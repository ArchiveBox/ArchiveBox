window.archiveboxHandleZipClick = function(link, event) {
    if (!link || link.dataset.loading === '1') {
        if (event) event.preventDefault()
        return false
    }

    const resetZipButton = function(target) {
        if (!target) return
        target.dataset.loading = ''
        target.classList.remove('is-loading')
        target.removeAttribute('aria-busy')
        const targetLabel = target.querySelector('.archivebox-zip-label')
        const targetSpinner = target.querySelector('.archivebox-zip-spinner')
        if (targetLabel) {
            targetLabel.textContent = target.dataset.originalLabel || targetLabel.textContent
            targetLabel.style.opacity = ''
            targetLabel.style.display = ''
            targetLabel.style.visibility = ''
        }
        if (targetSpinner) {
            targetSpinner.style.display = ''
        }
        target.style.pointerEvents = ''
        target.style.opacity = ''
        target.style.width = target.dataset.originalWidth || ''
        target.style.minWidth = target.dataset.originalMinWidth || ''
        if (target._zipResetTimer) {
            window.clearTimeout(target._zipResetTimer)
            target._zipResetTimer = null
        }
    }

    if (event) event.preventDefault()
    const lockedWidth = Math.ceil(link.getBoundingClientRect().width)
    link.dataset.originalWidth = link.style.width || ""
    link.dataset.originalMinWidth = link.style.minWidth || ""
    link.style.width = lockedWidth + "px"
    link.style.minWidth = lockedWidth + "px"
    link.dataset.loading = '1'
    link.classList.add('is-loading')
    link.setAttribute('aria-busy', 'true')
    const label = link.querySelector('.archivebox-zip-label')
    const spinner = link.querySelector('.archivebox-zip-spinner')
    const loadingMode = link.dataset.loadingMode || 'label'
    if (label) {
        link.dataset.originalLabel = label.textContent || ''
        if (loadingMode !== 'spinner-only') {
            label.textContent = link.dataset.loadingLabel || 'Preparing...'
            label.style.opacity = '0.92'
        }
    }
    if (spinner) {
        spinner.style.display = 'inline-block'
    }
    link.style.pointerEvents = 'none'
    link.style.opacity = '0.96'
    const destination = new URL(link.dataset.zipPath, location.href)
    destination.searchParams.set('files', '1')
    destination.searchParams.set('download', 'zip')
    let iframe = document.getElementById('archivebox-zip-download-frame')
    if (!iframe) {
        iframe = document.createElement('iframe')
        iframe.id = 'archivebox-zip-download-frame'
        iframe.name = 'archivebox-zip-download-frame'
        iframe.hidden = true
        iframe.style.display = 'none'
        document.body.appendChild(iframe)
    }
    iframe.onload = function() {
        window.setTimeout(function() {
            resetZipButton(link)
        }, 250)
    }
    link._zipResetTimer = window.setTimeout(function() {
        resetZipButton(link)
    }, 12000)
    void link.offsetWidth
    requestAnimationFrame(function() {
        requestAnimationFrame(function() {
            iframe.src = destination
        })
    })
    return false
}
