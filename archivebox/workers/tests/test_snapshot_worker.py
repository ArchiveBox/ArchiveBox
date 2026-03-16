from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from django.test import SimpleTestCase

from archivebox.workers.worker import SnapshotWorker


class TestSnapshotWorkerRetryForegroundHooks(SimpleTestCase):
    def _make_worker(self):
        worker = SnapshotWorker.__new__(SnapshotWorker)
        worker.pid = 12345
        cast(Any, worker).snapshot = SimpleNamespace(
            status='started',
            refresh_from_db=lambda: None,
        )
        worker._snapshot_exceeded_hard_timeout = lambda: False
        worker._seal_snapshot_due_to_timeout = lambda: None
        worker._run_hook = lambda *args, **kwargs: SimpleNamespace()
        worker._wait_for_hook = lambda process, ar: None
        return worker

    @patch('archivebox.workers.worker.log_worker_event')
    def test_retry_skips_successful_hook_with_only_inline_output(self, mock_log):
        worker = self._make_worker()
        archive_result = SimpleNamespace(
            status='succeeded',
            output_files={},
            output_str='scrolled 600px',
            output_json=None,
            refresh_from_db=lambda: None,
        )

        worker._retry_failed_empty_foreground_hooks(
            [(Path('/tmp/on_Snapshot__45_infiniscroll.js'), archive_result)],
            config={},
        )

        mock_log.assert_not_called()

    @patch('archivebox.workers.worker.log_worker_event')
    def test_retry_replays_failed_hook_with_no_outputs(self, mock_log):
        worker = self._make_worker()
        run_calls = []
        wait_calls = []

        def run_hook(*args, **kwargs):
            run_calls.append((args, kwargs))
            return SimpleNamespace()

        def wait_for_hook(process, ar):
            wait_calls.append((process, ar))
            ar.status = 'succeeded'
            ar.output_files = {'singlefile.html': {}}

        archive_result = SimpleNamespace(
            status='failed',
            output_files={},
            output_str='',
            output_json=None,
            refresh_from_db=lambda: None,
        )

        worker._run_hook = run_hook
        worker._wait_for_hook = wait_for_hook

        worker._retry_failed_empty_foreground_hooks(
            [(Path('/tmp/on_Snapshot__50_singlefile.py'), archive_result)],
            config={},
        )

        assert len(run_calls) == 1
        assert len(wait_calls) == 1
        mock_log.assert_called_once()
