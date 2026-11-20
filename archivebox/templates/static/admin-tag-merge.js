(() => {
    const dialog = document.getElementById('tag-merge-dialog')
    const form = document.getElementById('changelist-form')
    const buttons = [...form.querySelectorAll('[data-tag-merge-open]')]
    const chooser = dialog.querySelector('form')
    const name = document.getElementById('tag-merge-name')
    const count = document.getElementById('tag-merge-count')
    const max = Number(dialog.dataset.maxTags)
    let confirmedIds = []

    function selectedIds() {
        if (form.querySelector('input.select-across')?.value === '1') return []
        return [...form.querySelectorAll('input.action-select:checked')].map(input => input.value).sort()
    }

    function refresh() {
        const selected = selectedIds().length
        for (const button of buttons) {
            button.disabled = selected < 2 || selected > max
            button.title = button.disabled ? `Select 2 to ${max} individual tags to merge` : ''
        }
    }

    document.addEventListener('click', () => queueMicrotask(refresh))
    form.addEventListener('change', () => queueMicrotask(refresh))
    refresh()
    for (const button of buttons) button.addEventListener('click', () => {
        confirmedIds = selectedIds()
        if (confirmedIds.length < 2 || confirmedIds.length > max) return
        count.textContent = String(confirmedIds.length)
        chooser.reset()
        dialog.showModal()
        name.focus()
    })
    dialog.querySelector('[data-tag-merge-cancel]').addEventListener('click', () => dialog.close())
    chooser.addEventListener('submit', (event) => {
        event.preventDefault()
        const finalName = name.value.trim()
        if (!finalName || confirmedIds.join(',') !== selectedIds().join(',')) return
        const action = form.querySelector('select[name=action]')
        const submit = form.querySelector('button[name=index]')
        if (!action || !submit) return
        for (const [key, value] of [['merge_tag_name', finalName], ['confirm_tag_merge', '1'], ['confirm_tag_merge_count', String(confirmedIds.length)]]) {
            const input = document.createElement('input')
            input.type = 'hidden'
            input.name = key
            input.value = value
            form.append(input)
        }
        action.value = 'merge_tags'
        dialog.close()
        form.requestSubmit(submit)
    })
})()
