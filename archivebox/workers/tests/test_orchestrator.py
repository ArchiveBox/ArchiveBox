"""
Unit tests for the Orchestrator and Worker classes.

Tests cover:
1. Orchestrator lifecycle (startup, shutdown)
2. Queue polling and worker spawning
3. Idle detection and exit logic
4. Worker registration and management
5. PID file utilities
"""

import os
import tempfile
import time
import signal
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from django.test import TestCase, override_settings

from archivebox.workers.pid_utils import (
    get_pid_dir,
    write_pid_file,
    read_pid_file,
    remove_pid_file,
    is_process_alive,
    get_all_pid_files,
    get_all_worker_pids,
    cleanup_stale_pid_files,
    get_running_worker_count,
    get_next_worker_id,
    stop_worker,
)
from archivebox.workers.orchestrator import Orchestrator


class TestPidUtils(TestCase):
    """Test PID file utility functions."""

    def setUp(self):
        """Create a temporary directory for PID files."""
        self.temp_dir = tempfile.mkdtemp()
        self.pid_dir_patch = patch(
            'archivebox.workers.pid_utils.get_pid_dir',
            return_value=Path(self.temp_dir)
        )
        self.pid_dir_patch.start()

    def tearDown(self):
        """Clean up temporary directory."""
        self.pid_dir_patch.stop()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_write_pid_file_orchestrator(self):
        """write_pid_file should create orchestrator.pid for orchestrator."""
        pid_file = write_pid_file('orchestrator')

        self.assertTrue(pid_file.exists())
        self.assertEqual(pid_file.name, 'orchestrator.pid')

        content = pid_file.read_text().strip().split('\n')
        self.assertEqual(int(content[0]), os.getpid())
        self.assertEqual(content[1], 'orchestrator')

    def test_write_pid_file_worker(self):
        """write_pid_file should create numbered pid file for workers."""
        pid_file = write_pid_file('snapshot', worker_id=3)

        self.assertTrue(pid_file.exists())
        self.assertEqual(pid_file.name, 'snapshot_worker_3.pid')

    def test_write_pid_file_with_extractor(self):
        """write_pid_file should include extractor in content."""
        pid_file = write_pid_file('archiveresult', worker_id=0, extractor='singlefile')

        content = pid_file.read_text().strip().split('\n')
        self.assertEqual(content[2], 'singlefile')

    def test_read_pid_file_valid(self):
        """read_pid_file should parse valid PID files."""
        pid_file = write_pid_file('snapshot', worker_id=1)
        info = read_pid_file(pid_file)

        self.assertIsNotNone(info)
        self.assertEqual(info['pid'], os.getpid())
        self.assertEqual(info['worker_type'], 'snapshot')
        self.assertEqual(info['pid_file'], pid_file)
        self.assertIsNotNone(info['started_at'])

    def test_read_pid_file_invalid(self):
        """read_pid_file should return None for invalid files."""
        invalid_file = Path(self.temp_dir) / 'invalid.pid'
        invalid_file.write_text('not valid')

        info = read_pid_file(invalid_file)
        self.assertIsNone(info)

    def test_read_pid_file_nonexistent(self):
        """read_pid_file should return None for nonexistent files."""
        info = read_pid_file(Path(self.temp_dir) / 'nonexistent.pid')
        self.assertIsNone(info)

    def test_remove_pid_file(self):
        """remove_pid_file should delete the file."""
        pid_file = write_pid_file('test', worker_id=0)
        self.assertTrue(pid_file.exists())

        remove_pid_file(pid_file)
        self.assertFalse(pid_file.exists())

    def test_remove_pid_file_nonexistent(self):
        """remove_pid_file should not raise for nonexistent files."""
        # Should not raise
        remove_pid_file(Path(self.temp_dir) / 'nonexistent.pid')

    def test_is_process_alive_current(self):
        """is_process_alive should return True for current process."""
        self.assertTrue(is_process_alive(os.getpid()))

    def test_is_process_alive_dead(self):
        """is_process_alive should return False for dead processes."""
        # PID 999999 is unlikely to exist
        self.assertFalse(is_process_alive(999999))

    def test_get_all_pid_files(self):
        """get_all_pid_files should return all .pid files."""
        write_pid_file('orchestrator')
        write_pid_file('snapshot', worker_id=0)
        write_pid_file('crawl', worker_id=1)

        files = get_all_pid_files()
        self.assertEqual(len(files), 3)

    def test_get_all_worker_pids(self):
        """get_all_worker_pids should return info for live workers."""
        write_pid_file('snapshot', worker_id=0)
        write_pid_file('crawl', worker_id=1)

        workers = get_all_worker_pids()
        # All should be alive since they're current process PID
        self.assertEqual(len(workers), 2)

    def test_get_all_worker_pids_filtered(self):
        """get_all_worker_pids should filter by worker type."""
        write_pid_file('snapshot', worker_id=0)
        write_pid_file('snapshot', worker_id=1)
        write_pid_file('crawl', worker_id=0)

        snapshot_workers = get_all_worker_pids('snapshot')
        self.assertEqual(len(snapshot_workers), 2)

        crawl_workers = get_all_worker_pids('crawl')
        self.assertEqual(len(crawl_workers), 1)

    def test_cleanup_stale_pid_files(self):
        """cleanup_stale_pid_files should remove files for dead processes."""
        # Create a PID file with a dead PID
        stale_file = Path(self.temp_dir) / 'stale_worker_0.pid'
        stale_file.write_text('999999\nstale\n\n2024-01-01T00:00:00+00:00\n')

        # Create a valid PID file (current process)
        write_pid_file('valid', worker_id=0)

        removed = cleanup_stale_pid_files()

        self.assertEqual(removed, 1)
        self.assertFalse(stale_file.exists())

    def test_get_running_worker_count(self):
        """get_running_worker_count should count workers of a type."""
        write_pid_file('snapshot', worker_id=0)
        write_pid_file('snapshot', worker_id=1)
        write_pid_file('crawl', worker_id=0)

        self.assertEqual(get_running_worker_count('snapshot'), 2)
        self.assertEqual(get_running_worker_count('crawl'), 1)
        self.assertEqual(get_running_worker_count('archiveresult'), 0)

    def test_get_next_worker_id(self):
        """get_next_worker_id should find lowest unused ID."""
        write_pid_file('snapshot', worker_id=0)
        write_pid_file('snapshot', worker_id=1)
        write_pid_file('snapshot', worker_id=3)  # Skip 2

        next_id = get_next_worker_id('snapshot')
        self.assertEqual(next_id, 2)

    def test_get_next_worker_id_empty(self):
        """get_next_worker_id should return 0 if no workers exist."""
        next_id = get_next_worker_id('snapshot')
        self.assertEqual(next_id, 0)


class TestOrchestratorUnit(TestCase):
    """Unit tests for Orchestrator class (mocked dependencies)."""

    def test_orchestrator_creation(self):
        """Orchestrator should initialize with correct defaults."""
        orchestrator = Orchestrator(exit_on_idle=True)

        self.assertTrue(orchestrator.exit_on_idle)
        self.assertEqual(orchestrator.idle_count, 0)
        self.assertIsNone(orchestrator.pid_file)

    def test_orchestrator_repr(self):
        """Orchestrator __repr__ should include PID."""
        orchestrator = Orchestrator()
        repr_str = repr(orchestrator)

        self.assertIn('Orchestrator', repr_str)
        self.assertIn(str(os.getpid()), repr_str)

    def test_has_pending_work(self):
        """has_pending_work should check if any queue has items."""
        orchestrator = Orchestrator()

        self.assertFalse(orchestrator.has_pending_work({'crawl': 0, 'snapshot': 0}))
        self.assertTrue(orchestrator.has_pending_work({'crawl': 0, 'snapshot': 5}))
        self.assertTrue(orchestrator.has_pending_work({'crawl': 10, 'snapshot': 0}))

    def test_should_exit_not_exit_on_idle(self):
        """should_exit should return False when exit_on_idle is False."""
        orchestrator = Orchestrator(exit_on_idle=False)
        orchestrator.idle_count = 100

        self.assertFalse(orchestrator.should_exit({'crawl': 0}))

    def test_should_exit_pending_work(self):
        """should_exit should return False when there's pending work."""
        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.idle_count = 100

        self.assertFalse(orchestrator.should_exit({'crawl': 5}))

    @patch.object(Orchestrator, 'has_running_workers')
    def test_should_exit_running_workers(self, mock_has_workers):
        """should_exit should return False when workers are running."""
        mock_has_workers.return_value = True
        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.idle_count = 100

        self.assertFalse(orchestrator.should_exit({'crawl': 0}))

    @patch.object(Orchestrator, 'has_running_workers')
    @patch.object(Orchestrator, 'has_future_work')
    def test_should_exit_idle_timeout(self, mock_future, mock_workers):
        """should_exit should return True after idle timeout with no work."""
        mock_workers.return_value = False
        mock_future.return_value = False

        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.idle_count = orchestrator.IDLE_TIMEOUT

        self.assertTrue(orchestrator.should_exit({'crawl': 0, 'snapshot': 0}))

    @patch.object(Orchestrator, 'has_running_workers')
    @patch.object(Orchestrator, 'has_future_work')
    def test_should_exit_below_idle_timeout(self, mock_future, mock_workers):
        """should_exit should return False below idle timeout."""
        mock_workers.return_value = False
        mock_future.return_value = False

        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.idle_count = orchestrator.IDLE_TIMEOUT - 1

        self.assertFalse(orchestrator.should_exit({'crawl': 0}))

    def test_should_spawn_worker_no_queue(self):
        """should_spawn_worker should return False when queue is empty."""
        orchestrator = Orchestrator()

        # Create a mock worker class
        mock_worker = MagicMock()
        mock_worker.get_running_workers.return_value = []

        self.assertFalse(orchestrator.should_spawn_worker(mock_worker, 0))

    def test_should_spawn_worker_at_limit(self):
        """should_spawn_worker should return False when at per-type limit."""
        orchestrator = Orchestrator()

        mock_worker = MagicMock()
        mock_worker.get_running_workers.return_value = [{}] * orchestrator.MAX_WORKERS_PER_TYPE

        self.assertFalse(orchestrator.should_spawn_worker(mock_worker, 10))

    @patch.object(Orchestrator, 'get_total_worker_count')
    def test_should_spawn_worker_at_total_limit(self, mock_total):
        """should_spawn_worker should return False when at total limit."""
        orchestrator = Orchestrator()
        mock_total.return_value = orchestrator.MAX_TOTAL_WORKERS

        mock_worker = MagicMock()
        mock_worker.get_running_workers.return_value = []

        self.assertFalse(orchestrator.should_spawn_worker(mock_worker, 10))

    @patch.object(Orchestrator, 'get_total_worker_count')
    def test_should_spawn_worker_success(self, mock_total):
        """should_spawn_worker should return True when conditions are met."""
        orchestrator = Orchestrator()
        mock_total.return_value = 0

        mock_worker = MagicMock()
        mock_worker.get_running_workers.return_value = []
        mock_worker.MAX_CONCURRENT_TASKS = 5

        self.assertTrue(orchestrator.should_spawn_worker(mock_worker, 10))

    @patch.object(Orchestrator, 'get_total_worker_count')
    def test_should_spawn_worker_enough_workers(self, mock_total):
        """should_spawn_worker should return False when enough workers for queue."""
        orchestrator = Orchestrator()
        mock_total.return_value = 2

        mock_worker = MagicMock()
        mock_worker.get_running_workers.return_value = [{}]  # 1 worker running
        mock_worker.MAX_CONCURRENT_TASKS = 5  # Can handle 5 items

        # Queue size (3) <= running_workers (1) * MAX_CONCURRENT_TASKS (5)
        self.assertFalse(orchestrator.should_spawn_worker(mock_worker, 3))


class TestOrchestratorIsRunning(TestCase):
    """Test Orchestrator.is_running() class method."""

    def setUp(self):
        """Create a temporary directory for PID files."""
        self.temp_dir = tempfile.mkdtemp()
        self.pid_dir_patch = patch(
            'archivebox.workers.pid_utils.get_pid_dir',
            return_value=Path(self.temp_dir)
        )
        self.pid_dir_patch.start()

    def tearDown(self):
        """Clean up."""
        self.pid_dir_patch.stop()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_is_running_no_pid_file(self):
        """is_running should return False when no orchestrator PID file."""
        self.assertFalse(Orchestrator.is_running())

    def test_is_running_with_live_orchestrator(self):
        """is_running should return True when orchestrator PID file exists."""
        write_pid_file('orchestrator')
        self.assertTrue(Orchestrator.is_running())

    def test_is_running_with_dead_orchestrator(self):
        """is_running should return False when orchestrator process is dead."""
        # Create a PID file with a dead PID
        pid_file = Path(self.temp_dir) / 'orchestrator.pid'
        pid_file.write_text('999999\norchestrator\n\n2024-01-01T00:00:00+00:00\n')

        # The get_all_worker_pids filters out dead processes
        self.assertFalse(Orchestrator.is_running())


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
