const archiveboxAdminJQuery = (window.django && window.django.jQuery) || window.jQuery;
const $ = archiveboxAdminJQuery;
if ($) {
    window.$ = $;
    $.fn.reverse = [].reverse;
}

// hide images that fail to load
document.querySelector('body').addEventListener('error', function (e) {
    e.target.style.opacity = 0;
}, true)

// setup timezone
window.TIME_ZONE = document.body.dataset.timeZone

window.setCookie = function(name, value, days) {
    let expires = ""
    if (days) {
        const date = new Date()
        date.setTime(date.getTime() + (days*24*60*60*1000))
        expires = "; expires=" + date.toUTCString()
    }
    document.cookie = name + "=" + (value || "")  + expires + "; path=/"
}

function setTimeOffset() {
    if (window.GMT_OFFSET) return
    window.GMT_OFFSET = -(new Date).getTimezoneOffset()
    window.setCookie('GMT_OFFSET', window.GMT_OFFSET, 365)
}

// Controls are server-rendered; initialization only attaches their behavior.
function fix_actions(container) {
    if (!container.querySelector('.action-buttons') || container.dataset.actionsReady) return
    container.dataset.actionsReady = '1'

    function flushPendingActionTags() {
        const tagContainer = container.querySelector('.actions-tags')
        const input = tagContainer?.querySelector('.tag-inline-input')
        const hidden = tagContainer?.querySelector('input[type="hidden"][name="tags"]')
        const pending = (input?.value || '').trim()
        if (!pending || !hidden) return
        const seen = new Set()
        const tags = (hidden.value ? hidden.value.split(',') : [])
            .concat(pending.split(','))
            .map((tag) => tag.trim())
            .filter((tag) => {
                const key = tag.toLowerCase()
                if (!tag || seen.has(key)) return false
                seen.add(key)
                return true
            })
        hidden.value = tags.join(',')
        input.value = ''
        hidden.dispatchEvent(new Event('input', { bubbles: true }))
        hidden.dispatchEvent(new Event('change', { bubbles: true }))
    }

    function submitAction(action, control) {
        const num_selected = (
            document.querySelector('.action-selected-count')?.textContent.split('/')[0].trim()
            || document.querySelector('.action-counter')?.textContent.split(' ')[0]
            || '0'
        )
        let message
        if (action === 'overwrite_snapshots') {
            const scope = control.closest('[data-tagged-snapshot-actions]')
                ? 'snapshots matching the selected tags' : num_selected + ' Snapshots'
            message = 'Are you sure you want to re-archive (overwrite) ' + scope + '?\n\n' +
                'This will delete all previously saved files from these Snapshots and re-archive them from scratch.\n\n'
        } else if (action === 'delete_snapshots') {
            message = 'Are you sure you want to permanently delete ' + num_selected + ' Snapshots?\n\n' +
                'They will be removed from your index, and all their Snapshot content on disk will be permanently deleted.'
        }
        if (message && !window.confirm(message)) {
            if (control.tagName === 'SELECT') control.value = ''
            return
        }
        if (action === 'add_tags' || action === 'remove_tags') flushPendingActionTags()
        const actionInput = container.querySelector('select[name=action]')
        actionInput.value = action
        actionInput.dispatchEvent(new Event('change', { bubbles: true }))
        container.closest('form').querySelector('button[name="index"]').click()
        document.querySelector('#logo').outerHTML = '<div class="loader"></div>'
    }

    container.querySelectorAll('button[data-admin-action]').forEach(function(button) {
        button.addEventListener('click', function(event) {
            event.preventDefault()
            event.stopPropagation()
            submitAction(button.dataset.adminAction, button)
        })
    })
    container.addEventListener('change', function(event) {
        const control = event.target
        if (control.matches('.action-folder-select') && control.value !== '__choose__') {
            submitAction('move_to_folder', control)
        } else if (control.matches('.action-rearchive-select') && control.value) {
            submitAction(control.value, control)
        } else if (control.matches('.action-permissions-select') && control.value) {
            let permissionsInput = container.querySelector('input[name=permissions]')
            if (!permissionsInput) {
                permissionsInput = document.createElement('input')
                permissionsInput.type = 'hidden'
                permissionsInput.name = 'permissions'
                container.append(permissionsInput)
            }
            permissionsInput.value = control.value
            submitAction(control.dataset.adminAction, control)
        }
    })
    if (window.jQuery && window.jQuery.fn.select2) {
        window.jQuery('select[multiple]').select2();
    }
    updateActionControlVisibility()
}
function updateActionControlVisibility() {
    const selectAcross = document.querySelector('div.actions input.select-across')?.value === '1'
    const checked = selectAcross
        ? Number(document.querySelector('.action-summary')?.dataset.resultCount || 0)
        : document.querySelectorAll('#changelist-form input.action-select:checked').length
    document.querySelectorAll('.action-buttons, .actions-tags-with-buttons').forEach(function(el) {
        el.hidden = checked === 0
    })
    if (!checked) document.querySelectorAll('.action-folder-select').forEach(function(el) { el.value = '__choose__' })
}
function setupActionSummary() {
    const summary = document.querySelector('.action-summary')
    if (!summary || summary.dataset.summaryReady) return
    summary.dataset.summaryReady = '1'
    const selectedCount = summary.querySelector('.action-selected-count')
    const selectedCurrent = summary.querySelector('.action-selected-current')
    const pageSelect = summary.querySelector('.action-page-select')
    const counter = summary.querySelector('.action-counter')
    const formatter = new Intl.NumberFormat()
    const selectAllParam = '_archivebox_select_all'
    const getSelectedCount = function() {
        const selectAcross = document.querySelector('div.actions input.select-across')?.value === '1'
        if (selectAcross) {
            return Number(summary.dataset.resultCount || 0)
        }
        return document.querySelectorAll('#changelist-form input.action-select:checked').length
    }
    const selectCurrentResultsWithDjango = function() {
        const allToggle = document.getElementById('action-toggle')
        const questionLink = summary.querySelector('.question a')
        const selectAcross = document.querySelector('div.actions input.select-across')
        const pageCount = Number(summary.dataset.pageCount || 0)
        const resultCount = Number(summary.dataset.resultCount || pageCount)

        if (allToggle) {
            if (!allToggle.checked) {
                allToggle.click()
            }
            if (questionLink && resultCount > pageCount) {
                questionLink.click()
            }
            if (selectAcross) selectAcross.value = '1'
            return true
        }

        document.querySelectorAll('#changelist-form input.action-select').forEach(function(checkbox) {
            if (!checkbox.checked) {
                checkbox.checked = true
                checkbox.dispatchEvent(new Event('change', { bubbles: true }))
            }
            const card = checkbox.closest('.card')
            if (card) {
                card.classList.add('selected-card')
            }
        })
        if (selectAcross) {
            selectAcross.value = '1'
        }
        return false
    }
    const selectCurrentPageWithDjango = function() {
        const allToggle = document.getElementById('action-toggle')

        if (allToggle) {
            if (!allToggle.checked) {
                allToggle.click()
            }
            return true
        }

        const selectAcross = document.querySelector('div.actions input.select-across')
        if (selectAcross) selectAcross.value = '0'
        document.querySelectorAll('#changelist-form input.action-select').forEach(function(checkbox) {
            if (!checkbox.checked) {
                checkbox.checked = true
                checkbox.dispatchEvent(new Event('change', { bubbles: true }))
            }
            const card = checkbox.closest('.card')
            if (card) {
                card.classList.add('selected-card')
            }
        })
        return false
    }
    const selectAllRowsWithDjango = function() {
        const resultCount = Number(summary.dataset.resultCount || 0)
        const fullResultCount = Number(summary.dataset.fullResultCount || resultCount)
        if (fullResultCount > resultCount) {
            const url = new URL(window.location.href)
            url.search = '?' + selectAllParam + '=1'
            window.location.href = url.toString()
            return
        }
        selectCurrentResultsWithDjango()
    }
    const update = function() {
        if (!selectedCount || !counter) return
        const selectAcross = document.querySelector('div.actions input.select-across')?.value === '1'
        const selected = getSelectedCount()
        const pageCount = Number(summary.dataset.pageCount || 0)
        const selectedLimit = selectAcross ? Number(summary.dataset.resultCount || pageCount) : pageCount
        if (selectedCurrent && pageSelect) {
            selectedCurrent.textContent = selectAcross && summary.dataset.countExact === 'false' ? 'All' : formatter.format(selected)
            pageSelect.textContent = selectAcross && summary.dataset.countExact === 'false' ? 'matching' : formatter.format(selectedLimit)
        } else {
            selectedCount.textContent = formatter.format(selected) + ' / ' + formatter.format(selectedLimit) + ' selected'
        }
        summary.classList.toggle('action-summary-has-selection', selected > 0)
        summary.classList.toggle('action-summary-select-across', selectAcross)
        const totalCount = summary.querySelector('.action-total-count')
        if (totalCount) {
            totalCount.hidden = false
        }
        updateActionControlVisibility()
    }
    new MutationObserver(update).observe(counter, { childList: true, characterData: true, subtree: true })
    document.querySelector('#changelist-form')?.addEventListener('change', function() {
        window.setTimeout(update, 0)
    })
    summary.addEventListener('click', function(event) {
        const pageSelect = event.target.closest('.action-page-select')
        const explicitSelectAll = event.target.closest('.action-total-select, .action-total-count .question a')
        const totalReset = event.target.closest('.action-total-reset')
        if (pageSelect || explicitSelectAll || (totalReset && getSelectedCount() === 0)) {
            event.preventDefault()
            if (pageSelect) {
                selectCurrentPageWithDjango()
            } else if (totalReset) {
                selectAllRowsWithDjango()
            } else {
                selectCurrentResultsWithDjango()
            }
        }
        window.setTimeout(update, 0)
    })
    if (new URLSearchParams(window.location.search).get(selectAllParam) === '1') {
        const cleanUrl = new URL(window.location.href)
        cleanUrl.searchParams.delete(selectAllParam)
        window.history.replaceState(null, '', cleanUrl.toString())
        window.setTimeout(function() {
            selectAllRowsWithDjango()
            update()
        }, 0)
    }
    update()
}
function setupSearchModeSelect() {
    const storageKey = 'archivebox-admin-search-mode'
    const params = new URLSearchParams(window.location.search)
    document.querySelectorAll('.search-mode-select').forEach(function(select) {
        if (select.dataset.searchModeReady) return
        select.dataset.searchModeReady = '1'
        const values = Array.from(select.options).map(option => option.value)
        const stored = localStorage.getItem(storageKey)
        if (!params.has('search_mode') && values.includes(stored)) {
            select.value = stored
            if ((params.get('q') || '').trim()) {
                params.set('search_mode', stored)
                params.delete('p')
                window.location.replace(window.location.pathname + '?' + params.toString() + window.location.hash)
                return
            }
        }
        select.addEventListener('change', function() {
            localStorage.setItem(storageKey, select.value)
            const search = select.closest('#changelist-search')
            if (search && search.dataset.embeddedSearch === '1') {
                submitEmbeddedChangelistSearch(search)
                return
            }
            if (search && search.tagName === 'FORM' && document.activeElement === select) {
                search.requestSubmit()
            }
        })
    })
}
function submitEmbeddedChangelistSearch(search) {
    const params = new URLSearchParams(window.location.search)
    search.querySelectorAll('[name]').forEach(function(input) {
        const value = (input.value || '').trim()
        if (value) {
            params.set(input.name, value)
        } else {
            params.delete(input.name)
        }
    })
    params.delete('p')
    const query = params.toString()
    window.location.href = window.location.pathname + (query ? '?' + query : '') + window.location.hash
}
function setupEmbeddedChangelistSearch() {
    document.querySelectorAll('#changelist-search[data-embedded-search="1"]').forEach(function(search) {
        if (search.dataset.searchReady) return
        search.dataset.searchReady = '1'
        search.querySelector('.changelist-search-submit')?.addEventListener('click', function() {
            submitEmbeddedChangelistSearch(search)
        })
        search.querySelector('#searchbar')?.addEventListener('keydown', function(event) {
            if (event.key === 'Enter') {
                event.preventDefault()
                submitEmbeddedChangelistSearch(search)
            }
        })
    })
}
function setupSnapshotPermissionsQuickEdit() {
    if (document.body.dataset.snapshotPermissionsReady) return
    document.body.dataset.snapshotPermissionsReady = '1'
    function closeMenu(wrapper, restoreFocus) {
        wrapper.classList.remove('is-open')
        const toggle = wrapper.querySelector('.snapshot-permissions-button')
        toggle?.setAttribute('aria-expanded', 'false')
        const menu = wrapper.querySelector('.snapshot-permissions-menu')
        if (menu?.hasAttribute('data-snapshot-permissions-menu')) menu.remove()
        else if (menu) menu.hidden = true
        if (restoreFocus) toggle?.focus()
    }
    document.addEventListener('keydown', function(event) {
        const wrapper = event.target.closest('.snapshot-permissions-quick.is-open')
        if (!wrapper) return
        if (event.key === 'Escape') {
            event.preventDefault()
            closeMenu(wrapper, true)
            return
        }
        if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
        const menu = wrapper.querySelector('.snapshot-permissions-menu[data-snapshot-permissions-menu]')
        if (!menu) return
        event.preventDefault()
        const items = Array.from(menu.querySelectorAll('.snapshot-permissions-menu-item'))
        const index = items.indexOf(event.target)
        if (event.key === 'Home') items[0].focus()
        else if (event.key === 'End') items[items.length - 1].focus()
        else if (event.key === 'ArrowDown') items[(index + 1) % items.length].focus()
        else items[index > 0 ? index - 1 : items.length - 1].focus()
    })
    document.addEventListener('click', function(event) {
        const toggle = event.target.closest('.snapshot-permissions-button')
        const item = event.target.closest('.snapshot-permissions-menu-item')
        document.querySelectorAll('.snapshot-permissions-quick.is-open').forEach(function(openMenu) {
            if (!openMenu.contains(event.target)) closeMenu(openMenu)
        })
        if (toggle) {
            event.preventDefault()
            const wrapper = toggle.closest('.snapshot-permissions-quick')
            if (!wrapper) return
            if (wrapper.classList.contains('is-open')) {
                closeMenu(wrapper)
                return
            }
            let menu = wrapper.querySelector('.snapshot-permissions-menu')
            if (!menu) {
                // Resolve the current panel so streamed rows use its template too.
                const template = wrapper.closest('#changelist')?.querySelector(':scope > template[data-snapshot-permissions-menu]')
                menu = template?.content.firstElementChild?.cloneNode(true)
                if (!menu) return
                for (const button of menu.querySelectorAll('.snapshot-permissions-menu-item')) {
                    const selected = button.dataset.permissions === wrapper.dataset.currentPermissions
                    button.classList.toggle('is-active', selected)
                    button.setAttribute('aria-checked', selected)
                }
                wrapper.append(menu)
            }
            wrapper.classList.add('is-open')
            toggle.setAttribute('aria-expanded', 'true')
            menu.hidden = false
            if (!event.detail && menu.hasAttribute('data-snapshot-permissions-menu')) {
                (menu.querySelector('.is-active') || menu.firstElementChild).focus()
            }
            return
        }
        if (!item) return
        event.preventDefault()
        const wrapper = item.closest('.snapshot-permissions-quick')
        const permissions = item.dataset.permissions
        const csrf = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value
        if (!wrapper || !permissions || !csrf || wrapper.dataset.saving === '1') return
        wrapper.dataset.saving = '1'
        const body = new URLSearchParams({permissions: permissions, csrfmiddlewaretoken: csrf})
        fetch(wrapper.dataset.permissionsUrl, {
            method: 'POST',
            headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded'},
            body: body.toString(),
        }).then(function(response) {
            if (!response.ok) throw new Error('Failed to update permissions')
            return response.json()
        }).then(function(data) {
            wrapper.dataset.currentPermissions = data.permissions
            wrapper.querySelectorAll('.snapshot-permissions-menu-item').forEach(function(button) {
                button.classList.toggle('is-active', button.dataset.permissions === data.permissions)
            })
            const icon = wrapper.querySelector('.snapshot-permissions-icon')
            const selectedIcon = item.querySelector('svg')
            if (icon && selectedIcon) {
                icon.replaceChildren(selectedIcon.cloneNode(true))
            }
            const compactIcon = wrapper.closest('tr')?.querySelector('.snapshot-row-permission')
            if (compactIcon && selectedIcon) {
                compactIcon.replaceChildren(selectedIcon.cloneNode(true))
                compactIcon.title = data.label
                compactIcon.setAttribute('aria-label', data.label)
            }
            const toggle = wrapper.querySelector('.snapshot-permissions-button')
            if (toggle) {
                toggle.className = 'snapshot-permissions-button snapshot-permissions-' + data.permissions
                toggle.title = data.label
                toggle.setAttribute('aria-label', toggle.getAttribute('aria-label').split(':')[0] + ': ' + data.label)
            }
            const menu = wrapper.querySelector('.snapshot-permissions-menu')
            closeMenu(wrapper, menu?.contains(document.activeElement))
        }).catch(function(error) {
            window.alert(error.message)
        }).finally(function() {
            wrapper.dataset.saving = ''
        })
    })
}
function setupChangelistFormHandlers() {
    const form = document.querySelector('#changelist-form')
    if (form && !form.dataset.archiveboxActionsReady) {
        form.dataset.archiveboxActionsReady = '1'
        form.addEventListener('change', function(event) {
            const input = event.target
            if (input.matches('.card input[type="checkbox"]')) {
                input.closest('.card').classList.toggle('selected-card', input.checked)
                if (!input.checked) {
                    const selectAcross = form.querySelector('div.actions input.select-across')
                    if (selectAcross) selectAcross.value = '0'
                }
            }
            updateActionControlVisibility()
        })
    }
}
function fixInlineAddRow() {
    $('#id_snapshottag-MAX_NUM_FORMS').val('1000')
    $('.add-row').show()
}

function selectSnapshotIfHotlinked() {
    // if we arrive at the index with a url like ??id__startswith=...
    // we were hotlinked here with the intention of making it easy for the user to perform some
    // actions on the given snapshot. therefore we should preselect the snapshot to save them a click
    if (window.location.search.startsWith('?')) {
        const result_checkboxes = [...document.querySelectorAll('#result_list .action-checkbox input[type=checkbox]')]
        if (result_checkboxes.length === 1) {
            result_checkboxes[0].click()
        }
    }
}
window.archiveboxInitAdminChangelist = function() {
    if (window.archiveboxInitLibraryRows) window.archiveboxInitLibraryRows()
    window.archiveboxCloseFilesIconPile?.()
    document.querySelectorAll('div.actions').forEach(fix_actions)
    if ($) fixInlineAddRow()
    updateActionControlVisibility()
    setupActionSummary()
    setupSearchModeSelect()
    setupEmbeddedChangelistSearch()
    setupChangelistFormHandlers()
    selectSnapshotIfHotlinked()
}
if ($) {
    $(document).ready(function() {
        window.archiveboxInitAdminChangelist()
        setupSnapshotPermissionsQuickEdit()
        setTimeOffset()
    })
} else {
    document.addEventListener('DOMContentLoaded', function() {
        window.archiveboxInitAdminChangelist()
        setupSnapshotPermissionsQuickEdit()
        setTimeOffset()
    })
}
