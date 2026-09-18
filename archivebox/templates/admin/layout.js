{% load static tz core_tags %}
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
{% get_current_timezone as TIME_ZONE %}
window.TIME_ZONE = '{{TIME_ZONE}}'

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

// change the admin actions button from a dropdown to buttons across
function fix_actions() {
    const container = $('div.actions')
    if (container.find('.action-buttons').length) return

    // too many actions to turn into buttons
    if (container.find('select[name=action] option').length >= 11) return

    // hide the empty default option thats just a placeholder with no value
    container.find('label:nth-child(1), button[type=submit][name=index][value=0]').hide()

    const buttons = $('<div></div>')
        .insertAfter('div.actions button[type=submit]')
        .css('display', 'inline')
        .addClass('action-buttons');

    function flushPendingActionTags() {
        const tagContainer = document.querySelector('.actions-tags')
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

    const rearchiveActions = ['resnapshot_snapshot', 'update_snapshots', 'overwrite_snapshots']
    const rearchiveItems = {
        resnapshot_snapshot: ['➕', 'Create fresh snapshot(s)'],
        update_snapshots: ['▶️', 'Retry only failed subtasks'],
        overwrite_snapshots: ['♻️', 'Reset & retry from scratch'],
    }
    let rearchiveBuilt = false

    // for each action in the dropdown, turn it into a button instead
    container.find('select[name=action] option:gt(0)').each(function () {
        const action_type = this.value
        if (rearchiveActions.includes(action_type)) {
            if (rearchiveBuilt) return
            rearchiveBuilt = true
            const wrapper = $('<span></span>')
                .addClass('action-rearchive-wrapper')
                .appendTo(buttons)
            const select = $('<select></select>')
                .addClass('action-rearchive-select')
                .attr('aria-label', 'Re-Archive')
                .appendTo(wrapper)
            $('<span>')
                .attr('aria-hidden', 'true')
                .addClass('button')
                .html('Re-Archive <span aria-hidden="true">▾</span>')
                .appendTo(wrapper)
            $('<option></option>').attr('value', '').attr('hidden', true).appendTo(select)
            rearchiveActions.forEach(function (action_value) {
                const opt = container.find('select[name=action] option[value="' + action_value + '"]')[0]
                if (!opt) return
                const [icon, label] = rearchiveItems[action_value]
                $('<option></option>')
                    .attr('value', action_value)
                    .text(icon + ' ' + label)
                    .appendTo(select)
            })
            select.change(function () {
                const action_value = this.value
                if (!action_value) return
                const num_selected = (
                    document.querySelector('.action-selected-count')?.textContent.split('/')[0].trim()
                    || document.querySelector('.action-counter')?.textContent.split(' ')[0]
                    || '0'
                )
                if (action_value === 'overwrite_snapshots') {
                    const message = (
                        'Are you sure you want to re-archive (overwrite) ' + num_selected + ' Snapshots?\n\n' +
                        'This will delete all previously saved files from these Snapshots and re-archive them from scratch.\n\n'
                    )
                    if (!window.confirm(message)) {
                        this.value = ''
                        return
                    }
                }
                container.find('select[name=action]')
                    .val(action_value)
                    .trigger('change')
                $('#changelist-form button[name="index"]').click()
                document.querySelector('#logo').outerHTML = '<div class="loader"></div>'
            })
            return
        }
        if (action_type === 'set_crawl_permissions' || action_type === 'set_snapshot_permissions') {
            const wrapper = $('<span></span>')
                .addClass('action-permissions-wrapper')
                .appendTo(buttons)
            const select = $('<select></select>')
                .addClass('action-permissions-select')
                .attr('aria-label', 'Permissions')
                .appendTo(wrapper)
            $('<span>')
                .attr('aria-hidden', 'true')
                .attr('name', action_type)
                .addClass('button')
                .text(this.text)
                .appendTo(wrapper)
            $('<option></option>').attr('value', '').attr('hidden', true).appendTo(select)
            ;[
                ['public', '👥', 'Public'],
                ['unlisted', '🔗', 'Unlisted'],
                ['private', '🔒', 'Private'],
            ].forEach(function (choice) {
                $('<option></option>')
                    .attr('value', choice[0])
                    .text(choice[1] + ' ' + choice[2])
                    .appendTo(select)
            })
            select.change(function () {
                const permissions = this.value
                if (!permissions) return
                let permissionsInput = container.find('input[name=permissions]')
                if (!permissionsInput.length) {
                    permissionsInput = $('<input type="hidden" name="permissions">').appendTo(container)
                }
                permissionsInput.val(permissions)
                container.find('select[name=action]')
                    .val(action_type)
                    .trigger('change')
                $('#changelist-form button[name="index"]').click()
                document.querySelector('#logo').outerHTML = '<div class="loader"></div>'
            })
            return
        }
        $('<button>')
            .attr('type', 'button')
            .attr('name', action_type)
            .addClass('button')
            .text(this.text)
            .click(function (e) {
                e.preventDefault()
                e.stopPropagation()

                const num_selected = (
                    document.querySelector('.action-selected-count')?.textContent.split('/')[0].trim()
                    || document.querySelector('.action-counter')?.textContent.split(' ')[0]
                    || '0'
                )

                if (action_type === 'overwrite_snapshots') {
                    const message = (
                        'Are you sure you want to re-archive (overwrite) ' + num_selected + ' Snapshots?\n\n' +
                        'This will delete all previously saved files from these Snapshots and re-archive them from scratch.\n\n'
                    )
                    if (!window.confirm(message)) return false
                }
                if (action_type === 'delete_snapshots') {
                    const message = (
                        'Are you sure you want to permanently delete ' + num_selected + ' Snapshots?\n\n' +
                        'They will be removed from your index, and all their Snapshot content on disk will be permanently deleted.'
                    )
                    if (!window.confirm(message)) return false
                }
                if (action_type === 'add_tags' || action_type === 'remove_tags') {
                    flushPendingActionTags()
                }

                // select the action from the original Django admin dropdown
                container.find('select[name=action]')
                    .val(action_type)
                    .trigger('change')

                // click submit & replace the archivebox logo with a spinner
                $('#changelist-form button[name="index"]').click()
                document.querySelector('#logo').outerHTML = '<div class="loader"></div>'
                return false
            })
            .appendTo(buttons)
    })
    console.log('Converted', buttons.children().length, 'admin actions from dropdown to buttons')
    const tagContainer = document.querySelector('.actions-tags')
    if (tagContainer) {
        const tagButtons = buttons.find('button[name="add_tags"], button[name="remove_tags"]')
        if (tagButtons.length) {
            tagContainer.classList.add('actions-tags-with-buttons')
            tagButtons.appendTo(tagContainer)
        }
    }
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
        const match = counter?.textContent.match(/(\d+)\s+of\s+(\d+)\s+selected/)
        return match ? Number(match[1]) : document.querySelectorAll('#changelist-form input.action-select:checked').length
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
        if (selectAcross && resultCount > pageCount) {
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
        const match = counter.textContent.match(/(\d+)\s+of\s+(\d+)\s+selected/)
        const selectAcross = document.querySelector('div.actions input.select-across')?.value === '1'
        const selected = selectAcross
            ? Number(summary.dataset.resultCount || 0)
            : (match ? Number(match[1]) : document.querySelectorAll('#changelist-form input.action-select:checked').length)
        const pageCount = match ? Number(match[2]) : Number(summary.dataset.pageCount || 0)
        const selectedLimit = selectAcross ? Number(summary.dataset.resultCount || pageCount) : pageCount
        if (selectedCurrent && pageSelect) {
            selectedCurrent.textContent = formatter.format(selected)
            pageSelect.textContent = formatter.format(selectedLimit)
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
        search.querySelector('[name="snapshot_status"]')?.addEventListener('change', () => submitEmbeddedChangelistSearch(search))
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
    document.addEventListener('click', function(event) {
        const toggle = event.target.closest('.snapshot-permissions-button')
        const item = event.target.closest('.snapshot-permissions-menu-item')
        document.querySelectorAll('.snapshot-permissions-quick.is-open').forEach(function(openMenu) {
            if (!openMenu.contains(event.target)) {
                openMenu.classList.remove('is-open')
                openMenu.querySelector('.snapshot-permissions-button')?.setAttribute('aria-expanded', 'false')
                const menu = openMenu.querySelector('.snapshot-permissions-menu')
                if (menu) menu.hidden = true
            }
        })
        if (toggle) {
            event.preventDefault()
            const wrapper = toggle.closest('.snapshot-permissions-quick')
            const menu = wrapper?.querySelector('.snapshot-permissions-menu')
            if (!wrapper || !menu) return
            const isOpen = wrapper.classList.toggle('is-open')
            toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false')
            menu.hidden = !isOpen
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
            if (icon) {
                icon.textContent = data.icon
                icon.style.color = data.fg
                icon.style.background = data.bg
            }
            const toggle = wrapper.querySelector('.snapshot-permissions-button')
            if (toggle) {
                toggle.className = 'snapshot-permissions-button snapshot-permissions-' + data.permissions
                toggle.title = data.label
                toggle.setAttribute('aria-label', 'Change snapshot permissions: ' + data.label)
                toggle.setAttribute('aria-expanded', 'false')
            }
            wrapper.classList.remove('is-open')
            const menu = wrapper.querySelector('.snapshot-permissions-menu')
            if (menu) menu.hidden = true
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
        form.addEventListener('change', updateActionControlVisibility)
    }
}
function setupSnapshotCardSelection() {
    $('#changelist-form .card input:checkbox').change(function() {
        if ($(this).is(':checked'))
            $(this).parents('.card').addClass('selected-card')
        else
            $(this).parents('.card').removeClass('selected-card')
    })
};
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
    const destination = link.href
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
window.archiveboxInitAdminChangelist = function() {
    if (window.jQuery) {
        fix_actions()
        setupSnapshotCardSelection()
    }
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
