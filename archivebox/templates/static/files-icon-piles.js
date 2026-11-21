(() => {
    const HIDE_DELAY_MS = 600;
    const initializedPiles = new WeakSet();
    let activePopup = null;

    function initializePile(pile) {
        if (initializedPiles.has(pile)) return;
        const popup = pile.querySelector('.files-icon-pile-popup[popover]');
        if (!popup) return;
        initializedPiles.add(pile);
        let hideTimer;
        let trackingPosition = false;

        function updatePosition() {
            const pileRect = pile.getBoundingClientRect();
            const pileStyle = window.getComputedStyle(pile);
            const popupWidth = Number.parseFloat(pileStyle.getPropertyValue('--files-icon-card-width')) || 116;
            const popupOffset = Number.parseFloat(pileStyle.getPropertyValue('--files-icon-popup-left')) || 0;
            const maxLeft = Math.max(4, window.innerWidth - popupWidth - 4);
            const left = Math.max(4, Math.min(maxLeft, pileRect.left + popupOffset));
            popup.style.left = `${left}px`;
            popup.style.top = `${pileRect.top + 20}px`;
            popup.style.setProperty('--files-icon-caret-x', `${Math.max(8, Math.min(popupWidth - 8, pileRect.left + pileRect.width / 2 - left))}px`);
        }

        function openPopup() {
            window.clearTimeout(hideTimer);
            if (activePopup && activePopup !== controller) activePopup.closeImmediately();
            activePopup = controller;
            pile.classList.add('is-open');
            updatePosition();
            if (!popup.matches(':popover-open')) popup.showPopover();
            if (!trackingPosition) {
                window.addEventListener('scroll', updatePosition, true);
                window.addEventListener('resize', updatePosition);
                trackingPosition = true;
            }
        }

        function closePopup() {
            if (popup.matches(':popover-open')) popup.hidePopover();
            if (trackingPosition) {
                window.removeEventListener('scroll', updatePosition, true);
                window.removeEventListener('resize', updatePosition);
                trackingPosition = false;
            }
            popup.style.removeProperty('left');
            popup.style.removeProperty('top');
            popup.style.removeProperty('--files-icon-caret-x');
            pile.classList.remove('is-open');
            if (activePopup === controller) activePopup = null;
        }

        function scheduleClose() {
            window.clearTimeout(hideTimer);
            hideTimer = window.setTimeout(() => {
                if (pile.matches(':hover') || popup.matches(':hover') || pile.contains(document.activeElement)) return;
                closePopup();
            }, HIDE_DELAY_MS);
        }

        const controller = {
            pile,
            closeImmediately() {
                window.clearTimeout(hideTimer);
                closePopup();
            },
        };

        popup.addEventListener('toggle', (event) => {
            if (event.newState === 'closed' && trackingPosition) {
                window.removeEventListener('scroll', updatePosition, true);
                window.removeEventListener('resize', updatePosition);
                trackingPosition = false;
                pile.classList.remove('is-open');
                if (activePopup === controller) activePopup = null;
            }
        });

        pile.addEventListener('pointerenter', openPopup);
        pile.addEventListener('pointerleave', scheduleClose);
        pile.addEventListener('focusin', openPopup);
        pile.addEventListener('focusout', scheduleClose);
        popup.addEventListener('pointerenter', openPopup);
        popup.addEventListener('pointerleave', scheduleClose);
    }

    window.archiveboxInitFilesIconPiles = () => {
        if (activePopup) activePopup.closeImmediately();
        document.querySelectorAll('.files-icon-pile').forEach(initializePile);
    };
    window.archiveboxInitFilesIconPiles();

    if (!document.querySelector('.cards')) return;

    const gridFiles = '.card-files[data-grid-files-url]';
    const loadingGridFiles = new WeakSet();
    const loadedGridFiles = new WeakSet();

    document.addEventListener('pointerover', event => {
        if (event.pointerType !== 'mouse') return;
        const disclosure = event.target.closest('summary')?.closest(gridFiles);
        if (disclosure && !disclosure.contains(event.relatedTarget)) disclosure.open = true;
    });
    document.addEventListener('pointerout', event => {
        if (event.pointerType !== 'mouse') return;
        const disclosure = event.target.closest(gridFiles);
        if (disclosure?.open && !disclosure.contains(event.relatedTarget) && !disclosure.matches(':focus-within')) {
            disclosure.open = false;
        }
    });
    document.addEventListener('keydown', event => {
        const disclosure = event.key === 'Escape' && event.target.closest(gridFiles);
        if (!disclosure?.open) return;
        event.preventDefault();
        disclosure.open = false;
        disclosure.querySelector('summary').focus();
    });
    // Native details also opens through ordinary touch and keyboard controls.
    document.addEventListener('toggle', async event => {
        const disclosure = event.target;
        if (!(disclosure instanceof HTMLDetailsElement) || !disclosure.matches(gridFiles)) return;
        if (!disclosure.open) {
            if (activePopup && disclosure.contains(activePopup.pile)) activePopup.closeImmediately();
            return;
        }
        if (loadedGridFiles.has(disclosure) || loadingGridFiles.has(disclosure)) return;

        const contents = disclosure.querySelector('.card-files-results');
        const url = new URL(disclosure.dataset.gridFilesUrl, location.href);
        if (url.origin !== location.origin) return;
        loadingGridFiles.add(disclosure);
        contents.setAttribute('aria-busy', 'true');
        contents.textContent = 'Loading saved files…';
        try {
            const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', redirect: 'error'});
            if (!response.ok) throw new Error('Could not load saved files');
            const {html} = await response.json();
            if (typeof html !== 'string') throw new Error('Invalid saved files response');
            if (html) {
                const fragment = document.createRange().createContextualFragment(html);
                // Shared SVG definitions must be available even when the card
                // that first fetched a plugin's icon subsequently closes.
                const sprite = fragment.firstElementChild;
                if (sprite?.localName === 'svg') {
                    for (const symbol of [...sprite.children]) {
                        if (document.getElementById(symbol.id)) symbol.remove();
                    }
                    if (sprite.firstElementChild) document.body.append(sprite);
                    else sprite.remove();
                }
                contents.replaceChildren(fragment);
                contents.querySelectorAll('.files-icon-pile').forEach(initializePile);
            } else {
                contents.textContent = 'No saved files';
            }
            loadedGridFiles.add(disclosure);
        } catch {
            contents.textContent = 'Could not load saved files';
        } finally {
            contents.removeAttribute('aria-busy');
            loadingGridFiles.delete(disclosure);
        }
    }, true);
})();
