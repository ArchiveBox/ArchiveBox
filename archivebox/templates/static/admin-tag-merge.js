(() => {
    function mount(button, editor, prepare, submit) {
        const input = editor.querySelector('[data-tag-merge-input]');
        function close(focus = false) {
            editor.hidden = true;
            button.hidden = false;
            input.value = '';
            input.list.replaceChildren();
            if (focus) button.focus();
        }
        button.addEventListener('click', () => {
            if (!prepare()) return;
            button.hidden = true;
            editor.hidden = false;
            input.focus();
        });
        input.addEventListener('keydown', (event) => {
            if (event.isComposing || !['Enter', 'Escape'].includes(event.key)) return;
            event.preventDefault();
            event.stopPropagation();
            if (event.key === 'Escape') close(true);
            else if (input.value.trim()) submit();
        });
        return close;
    }

    const menu = document.getElementById('library-entry-menu');
    const sidebarForm = menu?.querySelector('[data-sidebar-tag-merge-form]');
    if (sidebarForm) {
        const button = menu.querySelector('[data-sidebar-tag-merge]');
        const close = mount(button, sidebarForm, () => {
            sidebarForm.querySelector('[data-merge-source]').value = menu.dataset.entryValue;
            return Boolean(menu.dataset.entryValue);
        }, () => sidebarForm.requestSubmit());
        menu.addEventListener('beforetoggle', (event) => {
            if (event.newState === 'closed') close();
        });
    }

    const form = document.getElementById('changelist-form');
    const mergeActions = form?.querySelectorAll('[data-tag-merge-max]') || [];
    for (const group of mergeActions) {
        const button = group.querySelector('[data-tag-merge-open]');
        const editor = group.querySelector('[data-tag-merge-editor]');
        const max = Number(group.dataset.tagMergeMax);
        const actions = group.closest('.actions');
        let confirmedIds = '';
        function selectedIds() {
            if (form.querySelector('input.select-across')?.value === '1') return [];
            return [...form.querySelectorAll('input.action-select:checked')].map(input => input.value).sort();
        }
        const close = mount(button, editor, () => {
            const ids = selectedIds();
            confirmedIds = ids.join(',');
            return ids.length >= 2 && ids.length <= max;
        }, () => {
            const ids = selectedIds();
            if (ids.join(',') !== confirmedIds) return;
            const action = actions.querySelector('select[name=action]');
            const submit = actions.querySelector('button[name=index]');
            if (!action || !submit) return;
            for (const [key, value] of [['confirm_tag_merge', '1'], ['confirm_tag_merge_count', String(ids.length)]]) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = key;
                input.value = value;
                form.append(input);
            }
            action.value = 'merge_tags';
            form.requestSubmit(submit);
        });
        function refresh() {
            const ids = selectedIds();
            button.disabled = ids.length < 2 || ids.length > max;
            button.title = button.disabled ? `Select 2 to ${max} individual tags to merge` : '';
            if (!editor.hidden && ids.join(',') !== confirmedIds) close();
        }
        document.addEventListener('click', () => queueMicrotask(refresh));
        form.addEventListener('change', () => queueMicrotask(refresh));
        refresh();
    }
})();
