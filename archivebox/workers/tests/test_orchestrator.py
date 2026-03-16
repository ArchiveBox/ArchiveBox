"""
Unit tests for the Orchestrator and Worker classes.

Tests cover:
1. Orchestrator lifecycle (startup, shutdown)
2. Queue polling and worker spawning
3. Idle detection and exit logic
4. Worker registration and management
5. Process model methods (replacing old pid_utils)
"""

import os
import tempfile
import time
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch, MagicMock

import pytest
from django.test import TestCase
from django.utils import timezone

from archivebox.workers.orchestrator import Orchestrator


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


class TestOrchestratorWithProcess(TestCase):
    """Test Orchestrator using Process model for tracking."""

    def setUp(self):
        """Reset process cache."""
        import archivebox.machine.models as models
        models._CURRENT_MACHINE = None
        models._CURRENT_PROCESS = None

    def test_is_running_no_orchestrator(self):
        """is_running should return False when no orchestrator process exists."""
        from archivebox.machine.models import Process

        # Clean up any stale processes first
        Process.cleanup_stale_running()

        # Mark any running orchestrators as exited for clean test state
        Process.objects.filter(
            process_type=Process.TypeChoices.ORCHESTRATOR,
            status=Process.StatusChoices.RUNNING
        ).update(status=Process.StatusChoices.EXITED)

        self.assertFalse(Orchestrator.is_running())

    def test_is_running_with_orchestrator_process(self):
        """is_running should return True when orchestrator Process exists."""
        from archivebox.machine.models import Process, Machine

        machine = Machine.current()

        # Create an orchestrator Process record
        proc = Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.ORCHESTRATOR,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),  # Use current PID so it appears alive
            started_at=timezone.now(),
            cmd=['archivebox', 'manage', 'orchestrator'],
        )

        try:
            # Should detect running orchestrator
            self.assertTrue(Orchestrator.is_running())
        finally:
            # Clean up
            proc.status = Process.StatusChoices.EXITED
            proc.save()

    def test_orchestrator_uses_process_for_is_running(self):
        """Orchestrator.is_running should use Process.get_running_count."""
        from archivebox.machine.models import Process

        # Verify is_running uses Process model, not pid files
        with patch.object(Process, 'get_running_count') as mock_count:
            mock_count.return_value = 1

            result = Orchestrator.is_running()

            # Should have called Process.get_running_count with orchestrator type
            mock_count.assert_called()
            self.assertTrue(result)

    def test_orchestrator_scoped_worker_count(self):
        """Orchestrator with crawl_id should count only descendant workers."""
        import time
        from archivebox.machine.models import Process, Machine

        machine = Machine.current()
        orchestrator = Orchestrator(exit_on_idle=True, crawl_id='test-crawl')

        orchestrator.db_process = Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.ORCHESTRATOR,
            status=Process.StatusChoices.RUNNING,
            pid=12345,
            started_at=timezone.now(),
        )

        # Prevent cleanup from marking fake PIDs as exited
        orchestrator._last_cleanup_time = time.time()

        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.WORKER,
            worker_type='crawl',
            status=Process.StatusChoices.RUNNING,
            pid=12346,
            parent=orchestrator.db_process,
            started_at=timezone.now(),
        )

        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.WORKER,
            worker_type='crawl',
            status=Process.StatusChoices.RUNNING,
            pid=12347,
            started_at=timezone.now(),
        )

        self.assertEqual(orchestrator.get_total_worker_count(), 1)


class TestProcessBasedWorkerTracking(TestCase):
    """Test Process model methods that replace pid_utils functionality."""

    def setUp(self):
        """Reset caches."""
        import archivebox.machine.models as models
        models._CURRENT_MACHINE = None
        models._CURRENT_PROCESS = None

    def test_process_current_creates_record(self):
        """Process.current() should create a Process record for current PID."""
        from archivebox.machine.models import Process

        proc = Process.current()

        self.assertIsNotNone(proc)
        self.assertEqual(proc.pid, os.getpid())
        self.assertEqual(proc.status, Process.StatusChoices.RUNNING)
        self.assertIsNotNone(proc.machine)
        self.assertIsNotNone(proc.started_at)

    def test_process_current_caches_result(self):
        """Process.current() should return cached Process within interval."""
        from archivebox.machine.models import Process

        proc1 = Process.current()
        proc2 = Process.current()

        self.assertEqual(proc1.id, proc2.id)

    def test_process_get_running_count(self):
        """Process.get_running_count should count running processes by type."""
        from archivebox.machine.models import Process, Machine

        machine = Machine.current()

        # Create some worker processes
        for i in range(3):
            Process.objects.create(
                machine=machine,
                process_type=Process.TypeChoices.WORKER,
                status=Process.StatusChoices.RUNNING,
                pid=99990 + i,  # Fake PIDs
                started_at=timezone.now(),
            )

        count = Process.get_running_count(process_type=Process.TypeChoices.WORKER)
        self.assertGreaterEqual(count, 3)

    def test_process_get_next_worker_id(self):
        """Process.get_next_worker_id should return count of running workers."""
        from archivebox.machine.models import Process, Machine

        machine = Machine.current()

        # Create 2 worker processes
        for i in range(2):
            Process.objects.create(
                machine=machine,
                process_type=Process.TypeChoices.WORKER,
                status=Process.StatusChoices.RUNNING,
                pid=99980 + i,
                started_at=timezone.now(),
            )

        next_id = Process.get_next_worker_id(process_type=Process.TypeChoices.WORKER)
        self.assertGreaterEqual(next_id, 2)

    def test_process_cleanup_stale_running(self):
        """Process.cleanup_stale_running should mark stale processes as exited."""
        from archivebox.machine.models import Process, Machine, PID_REUSE_WINDOW

        machine = Machine.current()

        # Create a stale process (old started_at, fake PID)
        stale_proc = Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.WORKER,
            status=Process.StatusChoices.RUNNING,
            pid=999999,  # Fake PID that doesn't exist
            started_at=timezone.now() - PID_REUSE_WINDOW - timedelta(hours=1),
        )

        cleaned = Process.cleanup_stale_running()

        self.assertGreaterEqual(cleaned, 1)

        stale_proc.refresh_from_db()
        self.assertEqual(stale_proc.status, Process.StatusChoices.EXITED)

    def test_process_get_running(self):
        """Process.get_running should return queryset of running processes."""
        from archivebox.machine.models import Process, Machine

        machine = Machine.current()

        # Create a running process
        proc = Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=99970,
            started_at=timezone.now(),
        )

        running = Process.get_running(process_type=Process.TypeChoices.HOOK)

        self.assertIn(proc, running)

    def test_process_type_detection(self):
        """Process._detect_process_type should detect process type from argv."""
        from archivebox.machine.models import Process

        # Test detection logic
        with patch('sys.argv', ['archivebox', 'manage', 'orchestrator']):
            result = Process._detect_process_type()
            self.assertEqual(result, Process.TypeChoices.ORCHESTRATOR)

        with patch('sys.argv', ['archivebox', 'add', 'http://example.com']):
            result = Process._detect_process_type()
            self.assertEqual(result, Process.TypeChoices.CLI)

        with patch('sys.argv', ['supervisord', '-c', 'config.ini']):
            result = Process._detect_process_type()
            self.assertEqual(result, Process.TypeChoices.SUPERVISORD)


class TestProcessLifecycle(TestCase):
    """Test Process model lifecycle methods."""

    def setUp(self):
        """Reset caches and create a machine."""
        import archivebox.machine.models as models
        models._CURRENT_MACHINE = None
        models._CURRENT_PROCESS = None
        self.machine = models.Machine.current()

    def test_process_is_running_property(self):
        """Process.is_running should check actual OS process."""
        from archivebox.machine.models import Process

        # Create a process with current PID (should be running)
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=timezone.now(),
        )

        # Should be running (current process exists)
        self.assertTrue(proc.is_running)

        # Create a process with fake PID
        fake_proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now(),
        )

        # Should not be running (PID doesn't exist)
        self.assertFalse(fake_proc.is_running)

    def test_process_poll(self):
        """Process.poll should check and update exit status."""
        from archivebox.machine.models import Process

        # Create a process with fake PID (already exited)
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now(),
        )

        exit_code = proc.poll()

        # Should have detected exit and updated status
        self.assertIsNotNone(exit_code)
        proc.refresh_from_db()
        self.assertEqual(proc.status, Process.StatusChoices.EXITED)

    def test_process_terminate_already_dead(self):
        """Process.terminate should handle already-dead processes."""
        from archivebox.machine.models import Process

        # Create a process with fake PID
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now(),
        )

        result = proc.terminate()

        # Should return False (was already dead)
        self.assertFalse(result)

        proc.refresh_from_db()
        self.assertEqual(proc.status, Process.StatusChoices.EXITED)

    def test_process_tree_traversal(self):
        """Process parent/children relationships should work."""
        from archivebox.machine.models import Process

        # Create parent process
        parent = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.CLI,
            status=Process.StatusChoices.RUNNING,
            pid=1,
            started_at=timezone.now(),
        )

        # Create child process
        child = Process.objects.create(
            machine=self.machine,
            parent=parent,
            process_type=Process.TypeChoices.WORKER,
            status=Process.StatusChoices.RUNNING,
            pid=2,
            started_at=timezone.now(),
        )

        # Test relationships
        self.assertEqual(child.parent, parent)
        self.assertIn(child, parent.children.all())
        self.assertEqual(child.root, parent)
        self.assertEqual(child.depth, 1)
        self.assertEqual(parent.depth, 0)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
