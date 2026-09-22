(function() {
    document.addEventListener('click', function(event) {
        var button = event.target.closest('.crawl-resume-row, .crawl-pause-row');
        if (!button) return;

        var form = document.getElementById('changelist-form');
        var actionSelect = form ? form.querySelector('select[name="action"]') : null;
        if (!form || !actionSelect) return;

        form.querySelectorAll('input[name="_selected_action"]').forEach(function(checkbox) {
            checkbox.checked = checkbox.value === button.getAttribute('data-crawl-id');
        });
        actionSelect.value = button.classList.contains('crawl-pause-row') ? 'pause_selected_crawls' : 'resume_selected_crawls';
        form.submit();
    });
})();
