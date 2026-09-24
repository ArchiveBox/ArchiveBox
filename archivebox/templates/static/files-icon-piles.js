(() => {
    const HIDE_DELAY_MS = 600;
    let activePopup = null;

    document.querySelectorAll('.files-icon-pile').forEach((pile) => {
        const popup = pile.querySelector('.files-icon-pile-popup[popover]');
        if (!popup) return;
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
    });
})();
