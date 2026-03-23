"""
Unit tests for machine module models: Machine, NetworkInterface, Binary, Process.

Tests cover:
1. Machine model creation and current() method
2. NetworkInterface model and network detection
3. Binary model lifecycle and state machine
4. Process model lifecycle, hierarchy, and state machine
5. JSONL serialization/deserialization
6. Manager methods
7. Process tracking methods (replacing pid_utils)
"""

import os
from datetime import timedelta
from typing import cast
from unittest.mock import Mock, patch

import pytest
from django.test import TestCase
from django.utils import timezone

from archivebox.machine.models import (
    BinaryManager,
    Machine,
    NetworkInterface,
    Binary,
    Process,
    BinaryMachine,
    ProcessMachine,
    MACHINE_RECHECK_INTERVAL,
    PID_REUSE_WINDOW,
    PROCESS_TIMEOUT_GRACE,
)


class TestMachineModel(TestCase):
    """Test the Machine model."""

    def setUp(self):
        """Reset cached machine between tests."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None

    def test_machine_current_creates_machine(self):
        """Machine.current() should create a machine if none exists."""
        machine = Machine.current()

        self.assertIsNotNone(machine)
        self.assertIsNotNone(machine.id)
        self.assertIsNotNone(machine.guid)
        self.assertEqual(machine.hostname, os.uname().nodename)
        self.assertIn(machine.os_family, ["linux", "darwin", "windows", "freebsd"])

    def test_machine_current_returns_cached(self):
        """Machine.current() should return cached machine within recheck interval."""
        machine1 = Machine.current()
        machine2 = Machine.current()

        self.assertEqual(machine1.id, machine2.id)

    def test_machine_current_refreshes_after_interval(self):
        """Machine.current() should refresh after recheck interval."""
        import archivebox.machine.models as models

        machine1 = Machine.current()

        # Manually expire the cache by modifying modified_at
        machine1.modified_at = timezone.now() - timedelta(seconds=MACHINE_RECHECK_INTERVAL + 1)
        machine1.save()
        models._CURRENT_MACHINE = machine1

        machine2 = Machine.current()

        # Should have fetched/updated the machine (same GUID)
        self.assertEqual(machine1.guid, machine2.guid)

    def test_machine_from_jsonl_update(self):
        """Machine.from_json() should update machine config."""
        Machine.current()  # Ensure machine exists
        record = {
            "config": {
                "WGET_BINARY": "/usr/bin/wget",
            },
        }

        result = Machine.from_json(record)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.config.get("WGET_BINARY"), "/usr/bin/wget")

    def test_machine_from_jsonl_strips_legacy_chromium_version(self):
        """Machine.from_json() should ignore legacy browser version keys."""
        Machine.current()  # Ensure machine exists
        record = {
            "config": {
                "WGET_BINARY": "/usr/bin/wget",
                "CHROMIUM_VERSION": "123.4.5",
            },
        }

        result = Machine.from_json(record)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.config.get("WGET_BINARY"), "/usr/bin/wget")
        self.assertNotIn("CHROMIUM_VERSION", result.config)

    def test_machine_from_jsonl_invalid(self):
        """Machine.from_json() should return None for invalid records."""
        result = Machine.from_json({"invalid": "record"})
        self.assertIsNone(result)

    def test_machine_current_strips_legacy_chromium_version(self):
        """Machine.current() should clean legacy browser version keys from persisted config."""
        import archivebox.machine.models as models

        machine = Machine.current()
        machine.config = {
            "CHROME_BINARY": "/tmp/chromium",
            "CHROMIUM_VERSION": "123.4.5",
        }
        machine.save(update_fields=["config"])
        models._CURRENT_MACHINE = machine

        refreshed = Machine.current()

        self.assertEqual(refreshed.config.get("CHROME_BINARY"), "/tmp/chromium")
        self.assertNotIn("CHROMIUM_VERSION", refreshed.config)

    def test_machine_manager_current(self):
        """Machine.objects.current() should return current machine."""
        machine = Machine.current()
        self.assertIsNotNone(machine)
        self.assertEqual(machine.id, Machine.current().id)


class TestNetworkInterfaceModel(TestCase):
    """Test the NetworkInterface model."""

    def setUp(self):
        """Reset cached interface between tests."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None
        models._CURRENT_INTERFACE = None

    def test_networkinterface_current_creates_interface(self):
        """NetworkInterface.current() should create an interface if none exists."""
        interface = NetworkInterface.current()

        self.assertIsNotNone(interface)
        self.assertIsNotNone(interface.id)
        self.assertIsNotNone(interface.machine)
        self.assertIsNotNone(interface.ip_local)

    def test_networkinterface_current_returns_cached(self):
        """NetworkInterface.current() should return cached interface within recheck interval."""
        interface1 = NetworkInterface.current()
        interface2 = NetworkInterface.current()

        self.assertEqual(interface1.id, interface2.id)

    def test_networkinterface_manager_current(self):
        """NetworkInterface.objects.current() should return current interface."""
        interface = NetworkInterface.current()
        self.assertIsNotNone(interface)

    def test_networkinterface_current_refresh_creates_new_interface_when_properties_change(self):
        """Refreshing should persist a new NetworkInterface row when the host network fingerprint changes."""
        import archivebox.machine.models as models

        first = {
            "mac_address": "aa:bb:cc:dd:ee:01",
            "ip_public": "1.1.1.1",
            "ip_local": "192.168.1.10",
            "dns_server": "8.8.8.8",
            "hostname": "host-a",
            "iface": "en0",
            "isp": "ISP A",
            "city": "City",
            "region": "Region",
            "country": "Country",
        }
        second = {
            **first,
            "ip_public": "2.2.2.2",
            "ip_local": "10.0.0.5",
        }

        with patch.object(models, "get_host_network", side_effect=[first, second]):
            interface1 = NetworkInterface.current(refresh=True)
            interface2 = NetworkInterface.current(refresh=True)

        self.assertNotEqual(interface1.id, interface2.id)
        self.assertEqual(interface1.machine_id, interface2.machine_id)
        self.assertEqual(NetworkInterface.objects.filter(machine=interface1.machine).count(), 2)


class TestBinaryModel(TestCase):
    """Test the Binary model."""

    def setUp(self):
        """Reset cached binaries and create a machine."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None
        models._CURRENT_BINARIES = {}
        self.machine = Machine.current()

    def test_binary_creation(self):
        """Binary should be created with default values."""
        binary = Binary.objects.create(
            machine=self.machine,
            name="wget",
            binproviders="apt,brew,env",
        )

        self.assertIsNotNone(binary.id)
        self.assertEqual(binary.name, "wget")
        self.assertEqual(binary.status, Binary.StatusChoices.QUEUED)
        self.assertFalse(binary.is_valid)

    def test_binary_is_valid(self):
        """Binary.is_valid should be True for installed binaries with a resolved path."""
        binary = Binary.objects.create(
            machine=self.machine,
            name="wget",
            abspath="/usr/bin/wget",
            version="1.21",
            status=Binary.StatusChoices.INSTALLED,
        )

        self.assertTrue(binary.is_valid)

    def test_binary_manager_get_valid_binary(self):
        """BinaryManager.get_valid_binary() should find valid binaries."""
        # Create invalid binary (no abspath)
        Binary.objects.create(machine=self.machine, name="wget")

        # Create valid binary
        Binary.objects.create(
            machine=self.machine,
            name="wget",
            abspath="/usr/bin/wget",
            version="1.21",
            status=Binary.StatusChoices.INSTALLED,
        )

        result = cast(BinaryManager, Binary.objects).get_valid_binary("wget")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.abspath, "/usr/bin/wget")

    def test_binary_update_and_requeue(self):
        """Binary.update_and_requeue() should update fields and save."""
        binary = Binary.objects.create(machine=self.machine, name="test")
        old_modified = binary.modified_at

        binary.update_and_requeue(
            status=Binary.StatusChoices.QUEUED,
            retry_at=timezone.now() + timedelta(seconds=60),
        )

        binary.refresh_from_db()
        self.assertEqual(binary.status, Binary.StatusChoices.QUEUED)
        self.assertGreater(binary.modified_at, old_modified)

    def test_binary_from_json_preserves_install_args_overrides(self):
        """Binary.from_json() should persist canonical install_args overrides unchanged."""
        overrides = {
            "apt": {"install_args": ["chromium"]},
            "npm": {"install_args": "puppeteer"},
            "custom": {"install_args": ["bash", "-lc", "echo ok"]},
        }

        binary = Binary.from_json(
            {
                "name": "chrome",
                "binproviders": "apt,npm,custom",
                "overrides": overrides,
            },
        )

        self.assertIsNotNone(binary)
        assert binary is not None
        self.assertEqual(binary.overrides, overrides)

    def test_binary_from_json_does_not_coerce_legacy_override_shapes(self):
        """Binary.from_json() should no longer translate legacy non-dict provider overrides."""
        overrides = {
            "apt": ["chromium"],
            "npm": "puppeteer",
        }

        binary = Binary.from_json(
            {
                "name": "chrome",
                "binproviders": "apt,npm",
                "overrides": overrides,
            },
        )

        self.assertIsNotNone(binary)
        assert binary is not None
        self.assertEqual(binary.overrides, overrides)

    def test_binary_from_json_prefers_published_readability_package(self):
        """Binary.from_json() should rewrite readability's npm git URL to the published package."""
        binary = Binary.from_json(
            {
                "name": "readability-extractor",
                "binproviders": "env,npm",
                "overrides": {
                    "npm": {
                        "install_args": ["https://github.com/ArchiveBox/readability-extractor"],
                    },
                },
            },
        )

        self.assertIsNotNone(binary)
        assert binary is not None
        self.assertEqual(
            binary.overrides,
            {
                "npm": {
                    "install_args": ["readability-extractor"],
                },
            },
        )


class TestBinaryStateMachine(TestCase):
    """Test the BinaryMachine state machine."""

    def setUp(self):
        """Create a machine and binary for state machine tests."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None
        self.machine = Machine.current()
        self.binary = Binary.objects.create(
            machine=self.machine,
            name="test-binary",
            binproviders="env",
        )

    def test_binary_state_machine_initial_state(self):
        """BinaryMachine should start in queued state."""
        sm = BinaryMachine(self.binary)
        self.assertEqual(sm.current_state_value, Binary.StatusChoices.QUEUED)

    def test_binary_state_machine_can_start(self):
        """BinaryMachine.can_start() should check name and binproviders."""
        sm = BinaryMachine(self.binary)
        self.assertTrue(sm.can_install())

        self.binary.binproviders = ""
        self.binary.save()
        sm = BinaryMachine(self.binary)
        self.assertFalse(sm.can_install())


class TestProcessModel(TestCase):
    """Test the Process model."""

    def setUp(self):
        """Create a machine for process tests."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None
        models._CURRENT_PROCESS = None
        self.machine = Machine.current()

    def test_process_creation(self):
        """Process should be created with default values."""
        process = Process.objects.create(
            machine=self.machine,
            cmd=["echo", "hello"],
            pwd="/tmp",
        )

        self.assertIsNotNone(process.id)
        self.assertEqual(process.cmd, ["echo", "hello"])
        self.assertEqual(process.status, Process.StatusChoices.QUEUED)
        self.assertIsNone(process.pid)
        self.assertIsNone(process.exit_code)

    def test_process_to_jsonl(self):
        """Process.to_json() should serialize correctly."""
        process = Process.objects.create(
            machine=self.machine,
            cmd=["echo", "hello"],
            pwd="/tmp",
            timeout=60,
        )
        json_data = process.to_json()

        self.assertEqual(json_data["type"], "Process")
        self.assertEqual(json_data["cmd"], ["echo", "hello"])
        self.assertEqual(json_data["pwd"], "/tmp")
        self.assertEqual(json_data["timeout"], 60)

    def test_process_update_and_requeue(self):
        """Process.update_and_requeue() should update fields and save."""
        process = Process.objects.create(machine=self.machine, cmd=["test"])

        process.update_and_requeue(
            status=Process.StatusChoices.RUNNING,
            pid=12345,
            started_at=timezone.now(),
        )

        process.refresh_from_db()
        self.assertEqual(process.status, Process.StatusChoices.RUNNING)
        self.assertEqual(process.pid, 12345)
        self.assertIsNotNone(process.started_at)


class TestProcessCurrent(TestCase):
    """Test Process.current() method."""

    def setUp(self):
        """Reset caches."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None
        models._CURRENT_PROCESS = None

    def test_process_current_creates_record(self):
        """Process.current() should create a Process for current PID."""
        proc = Process.current()

        self.assertIsNotNone(proc)
        self.assertEqual(proc.pid, os.getpid())
        self.assertEqual(proc.status, Process.StatusChoices.RUNNING)
        self.assertIsNotNone(proc.machine)
        self.assertIsNotNone(proc.iface)
        self.assertEqual(proc.iface.machine_id, proc.machine_id)
        self.assertIsNotNone(proc.started_at)

    def test_process_current_caches(self):
        """Process.current() should cache the result."""
        proc1 = Process.current()
        proc2 = Process.current()

        self.assertEqual(proc1.id, proc2.id)

    def test_process_detect_type_runner(self):
        """_detect_process_type should detect the background runner command."""
        with patch("sys.argv", ["archivebox", "run", "--daemon"]):
            result = Process._detect_process_type()
            self.assertEqual(result, Process.TypeChoices.ORCHESTRATOR)

    def test_process_detect_type_runner_watch(self):
        """runner_watch should be classified as a worker, not the orchestrator itself."""
        with patch("sys.argv", ["archivebox", "manage", "runner_watch", "--pidfile=/tmp/runserver.pid"]):
            result = Process._detect_process_type()
            self.assertEqual(result, Process.TypeChoices.WORKER)

    def test_process_detect_type_cli(self):
        """_detect_process_type should detect CLI commands."""
        with patch("sys.argv", ["archivebox", "add", "http://example.com"]):
            result = Process._detect_process_type()
            self.assertEqual(result, Process.TypeChoices.CLI)

    def test_process_detect_type_binary(self):
        """_detect_process_type should detect non-ArchiveBox subprocesses as binary processes."""
        with patch("sys.argv", ["/usr/bin/wget", "https://example.com"]):
            result = Process._detect_process_type()
            self.assertEqual(result, Process.TypeChoices.BINARY)

    def test_process_proc_allows_interpreter_wrapped_script(self):
        """Process.proc should accept a script recorded in DB when wrapped by an interpreter in psutil."""
        proc = Process.objects.create(
            machine=Machine.current(),
            cmd=["/tmp/on_Crawl__90_chrome_launch.daemon.bg.js", "--url=https://example.com/"],
            pid=12345,
            status=Process.StatusChoices.RUNNING,
            started_at=timezone.now(),
        )

        os_proc = Mock()
        os_proc.create_time.return_value = proc.started_at.timestamp()
        os_proc.cmdline.return_value = [
            "node",
            "/tmp/on_Crawl__90_chrome_launch.daemon.bg.js",
            "--url=https://example.com/",
        ]

        with patch("archivebox.machine.models.psutil.Process", return_value=os_proc):
            self.assertIs(proc.proc, os_proc)


class TestProcessHierarchy(TestCase):
    """Test Process parent/child relationships."""

    def setUp(self):
        """Create machine."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None
        self.machine = Machine.current()

    def test_process_parent_child(self):
        """Process should track parent/child relationships."""
        parent = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.CLI,
            status=Process.StatusChoices.RUNNING,
            pid=1,
            started_at=timezone.now(),
        )

        child = Process.objects.create(
            machine=self.machine,
            parent=parent,
            process_type=Process.TypeChoices.WORKER,
            status=Process.StatusChoices.RUNNING,
            pid=2,
            started_at=timezone.now(),
        )

        self.assertEqual(child.parent, parent)
        self.assertIn(child, parent.children.all())

    def test_process_root(self):
        """Process.root should return the root of the hierarchy."""
        root = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.CLI,
            status=Process.StatusChoices.RUNNING,
            started_at=timezone.now(),
        )
        child = Process.objects.create(
            machine=self.machine,
            parent=root,
            status=Process.StatusChoices.RUNNING,
            started_at=timezone.now(),
        )
        grandchild = Process.objects.create(
            machine=self.machine,
            parent=child,
            status=Process.StatusChoices.RUNNING,
            started_at=timezone.now(),
        )

        self.assertEqual(grandchild.root, root)
        self.assertEqual(child.root, root)
        self.assertEqual(root.root, root)

    def test_process_depth(self):
        """Process.depth should return depth in tree."""
        root = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            started_at=timezone.now(),
        )
        child = Process.objects.create(
            machine=self.machine,
            parent=root,
            status=Process.StatusChoices.RUNNING,
            started_at=timezone.now(),
        )

        self.assertEqual(root.depth, 0)
        self.assertEqual(child.depth, 1)


class TestProcessLifecycle(TestCase):
    """Test Process lifecycle methods."""

    def setUp(self):
        """Create machine."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None
        self.machine = Machine.current()

    def test_process_is_running_current_pid(self):
        """is_running should be True for current PID."""
        import psutil
        from datetime import datetime

        proc_start = datetime.fromtimestamp(psutil.Process(os.getpid()).create_time(), tz=timezone.get_current_timezone())
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=proc_start,
        )

        self.assertTrue(proc.is_running)

    def test_process_is_running_fake_pid(self):
        """is_running should be False for non-existent PID."""
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now(),
        )

        self.assertFalse(proc.is_running)

    def test_process_poll_detects_exit(self):
        """poll() should detect exited process."""
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now(),
        )

        exit_code = proc.poll()

        self.assertIsNotNone(exit_code)
        proc.refresh_from_db()
        self.assertEqual(proc.status, Process.StatusChoices.EXITED)

    def test_process_poll_normalizes_negative_exit_code(self):
        """poll() should normalize -1 exit codes to 137."""
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.EXITED,
            pid=999999,
            exit_code=-1,
            started_at=timezone.now(),
        )

        exit_code = proc.poll()

        self.assertEqual(exit_code, 137)
        proc.refresh_from_db()
        self.assertEqual(proc.exit_code, 137)

    def test_process_terminate_dead_process(self):
        """terminate() should handle already-dead process."""
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now(),
        )

        result = proc.terminate()

        self.assertFalse(result)
        proc.refresh_from_db()
        self.assertEqual(proc.status, Process.StatusChoices.EXITED)


class TestProcessClassMethods(TestCase):
    """Test Process class methods for querying."""

    def setUp(self):
        """Create machine."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None
        self.machine = Machine.current()

    def test_get_running(self):
        """get_running should return running processes."""
        proc = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=99999,
            started_at=timezone.now(),
        )

        running = Process.get_running(process_type=Process.TypeChoices.HOOK)

        self.assertIn(proc, running)

    def test_get_running_count(self):
        """get_running_count should count running processes."""
        for i in range(3):
            Process.objects.create(
                machine=self.machine,
                process_type=Process.TypeChoices.HOOK,
                status=Process.StatusChoices.RUNNING,
                pid=99900 + i,
                started_at=timezone.now(),
            )

        count = Process.get_running_count(process_type=Process.TypeChoices.HOOK)
        self.assertGreaterEqual(count, 3)

    def test_cleanup_stale_running(self):
        """cleanup_stale_running should mark stale processes as exited."""
        stale = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now() - PID_REUSE_WINDOW - timedelta(hours=1),
        )

        cleaned = Process.cleanup_stale_running()

        self.assertGreaterEqual(cleaned, 1)
        stale.refresh_from_db()
        self.assertEqual(stale.status, Process.StatusChoices.EXITED)

    def test_cleanup_stale_running_marks_timed_out_rows_exited(self):
        """cleanup_stale_running should retire RUNNING rows that exceed timeout + grace."""
        stale = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999998,
            timeout=5,
            started_at=timezone.now() - PROCESS_TIMEOUT_GRACE - timedelta(seconds=10),
        )

        cleaned = Process.cleanup_stale_running()

        self.assertGreaterEqual(cleaned, 1)
        stale.refresh_from_db()
        self.assertEqual(stale.status, Process.StatusChoices.EXITED)

    def test_cleanup_stale_running_marks_timed_out_live_hooks_exited(self):
        """Timed-out live hook rows should be retired in the DB without trying to kill the process."""
        stale = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            timeout=5,
            started_at=timezone.now() - PROCESS_TIMEOUT_GRACE - timedelta(seconds=10),
        )

        with (
            patch.object(Process, "poll", return_value=None),
            patch.object(Process, "kill_tree") as kill_tree,
            patch.object(Process, "terminate") as terminate,
        ):
            cleaned = Process.cleanup_stale_running()

        self.assertGreaterEqual(cleaned, 1)
        stale.refresh_from_db()
        self.assertEqual(stale.status, Process.StatusChoices.EXITED)
        kill_tree.assert_not_called()
        terminate.assert_not_called()

    def test_cleanup_orphaned_workers_marks_dead_root_children_exited(self):
        """cleanup_orphaned_workers should retire rows whose CLI/orchestrator root is gone."""
        import psutil
        from datetime import datetime

        started_at = datetime.fromtimestamp(psutil.Process(os.getpid()).create_time(), tz=timezone.get_current_timezone())
        parent = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.CLI,
            status=Process.StatusChoices.RUNNING,
            pid=999997,
            started_at=timezone.now() - timedelta(minutes=5),
        )
        child = Process.objects.create(
            machine=self.machine,
            parent=parent,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=started_at,
        )

        with patch.object(Process, "kill_tree") as kill_tree, patch.object(Process, "terminate") as terminate:
            cleaned = Process.cleanup_orphaned_workers()

        self.assertEqual(cleaned, 1)
        child.refresh_from_db()
        self.assertEqual(child.status, Process.StatusChoices.EXITED)
        kill_tree.assert_not_called()
        terminate.assert_not_called()


class TestProcessStateMachine(TestCase):
    """Test the ProcessMachine state machine."""

    def setUp(self):
        """Create a machine and process for state machine tests."""
        import archivebox.machine.models as models

        models._CURRENT_MACHINE = None
        self.machine = Machine.current()
        self.process = Process.objects.create(
            machine=self.machine,
            cmd=["echo", "test"],
            pwd="/tmp",
        )

    def test_process_state_machine_initial_state(self):
        """ProcessMachine should start in queued state."""
        sm = ProcessMachine(self.process)
        self.assertEqual(sm.current_state_value, Process.StatusChoices.QUEUED)

    def test_process_state_machine_can_start(self):
        """ProcessMachine.can_start() should check cmd and machine."""
        sm = ProcessMachine(self.process)
        self.assertTrue(sm.can_start())

        self.process.cmd = []
        self.process.save()
        sm = ProcessMachine(self.process)
        self.assertFalse(sm.can_start())

    def test_process_state_machine_is_exited(self):
        """ProcessMachine.is_exited() should check exit_code."""
        sm = ProcessMachine(self.process)
        self.assertFalse(sm.is_exited())

        self.process.exit_code = 0
        self.process.save()
        sm = ProcessMachine(self.process)
        self.assertTrue(sm.is_exited())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
