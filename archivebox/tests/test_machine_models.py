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
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from django.db import transaction
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

pytestmark = pytest.mark.django_db


def _reset_machine_model_caches():
    import archivebox.machine.models as models

    models._CURRENT_MACHINE = None
    models._CURRENT_INTERFACE = None
    models._CURRENT_PROCESS = None
    models._CURRENT_BINARIES = {}


@pytest.fixture(autouse=True)
def reset_machine_model_caches():
    _reset_machine_model_caches()
    yield
    _reset_machine_model_caches()


@pytest.fixture
def machine():
    return Machine.current()


@pytest.fixture
def binary(machine):
    return Binary.objects.create(
        machine=machine,
        name="test-binary",
        binproviders="env",
    )


@pytest.fixture
def process(machine):
    return Process.objects.create(
        machine=machine,
        cmd=["echo", "test"],
        pwd="/tmp",
    )


@pytest.fixture
def cleanup_paths():
    paths: list[Path] = []
    yield paths
    for path in reversed(paths):
        path.unlink(missing_ok=True)


class TestMachineModel:
    """Test the Machine model."""

    def test_machine_config_save_heals_json_encoded_string_values(self, machine):
        machine.config = {
            "EXTRA_CONTEXT": 'prefix "inner" suffix',
            "USER_AGENT": '"ArchiveBox \\"Quoted\\" Agent"',
        }
        machine.save(update_fields=["config"])

        machine.refresh_from_db()

        assert machine.config["EXTRA_CONTEXT"] == 'prefix "inner" suffix'
        assert machine.config["USER_AGENT"] == 'ArchiveBox "Quoted" Agent'

    def test_machine_current_creates_machine(self):
        """Machine.current() should create a machine if none exists."""
        machine = Machine.current()

        assert machine is not None
        assert machine.id is not None
        assert machine.guid is not None
        assert machine.hostname == os.uname().nodename
        assert machine.os_family in ["linux", "darwin", "windows", "freebsd"]

    def test_machine_current_returns_cached(self):
        """Machine.current() should return cached machine within recheck interval."""
        machine1 = Machine.current()
        machine2 = Machine.current()

        assert machine1.id == machine2.id

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
        assert machine1.guid == machine2.guid

    def test_machine_current_recreates_stale_cached_row(self):
        """Machine.current() should recreate the cached machine if the row was deleted."""
        import archivebox.machine.models as models

        machine1 = Machine.current()
        machine1_id = machine1.id
        machine1_guid = machine1.guid

        machine1.delete()
        models._CURRENT_MACHINE = machine1

        machine2 = Machine.current()

        assert machine1_id != machine2.id
        assert machine1_guid == machine2.guid

    def test_machine_from_jsonl_update(self, cleanup_paths):
        """Machine.from_json() should update machine config."""
        from archivebox.config.constants import CONSTANTS

        Machine.current()  # Ensure machine exists
        wget_path = CONSTANTS.DEFAULT_LIB_DIR / "wget"
        wget_path.parent.mkdir(parents=True, exist_ok=True)
        wget_path.write_text("#!/bin/sh\n")
        cleanup_paths.append(wget_path)
        record = {
            "config": {
                "WGET_BINARY": str(wget_path),
            },
        }

        result = Machine.from_json(record)

        assert result is not None
        assert result.config.get("WGET_BINARY") == str(wget_path)

    def test_machine_from_jsonl_drops_invalid_binary_paths_keeps_mirror(self, cleanup_paths):
        """Machine.from_json() drops invalid binary paths but mirrors other keys.

        ``Machine.config`` mirrors ``ArchiveBox.conf`` (non-binary user config
        keys live alongside derived binary state), so non-binary keys in the
        import survive. Only ``_BINARY`` paths get validated/dropped on import.
        """
        from archivebox.config.constants import CONSTANTS

        Machine.current()  # Ensure machine exists
        wget_path = CONSTANTS.DEFAULT_LIB_DIR / "wget"
        wget_path.parent.mkdir(parents=True, exist_ok=True)
        wget_path.write_text("#!/bin/sh\n")
        cleanup_paths.append(wget_path)
        record = {
            "config": {
                "WGET_BINARY": str(wget_path),
                "CHROMIUM_VERSION": "123.4.5",
                "YTDLP_BINARY": "/tmp/archivebox-test-missing-yt-dlp",
            },
        }

        result = Machine.from_json(record)

        assert result is not None
        assert result.config.get("WGET_BINARY") == str(wget_path)
        assert result.config.get("CHROMIUM_VERSION") == "123.4.5"
        assert "YTDLP_BINARY" not in result.config

    def test_machine_from_jsonl_invalid(self):
        """Machine.from_json() should return None for invalid records."""
        result = Machine.from_json({"invalid": "record"})
        assert result is None

    def test_machine_current_drops_invalid_binary_paths_keeps_mirror(self, cleanup_paths):
        """Machine.current() mirrors ArchiveBox.conf, only drops invalid binaries.

        ``Machine.config`` is the file ↔ DB mirror of ``ArchiveBox.conf``, so
        non-binary keys (``CHROME_ISOLATION``, ``CHROMIUM_VERSION``, etc.) are
        preserved on read. Only ``_BINARY`` paths get validated against
        ``LIB_DIR`` and dropped when stale/missing.
        """
        import archivebox.machine.models as models
        from archivebox.config.constants import CONSTANTS

        active_lib_dir = CONSTANTS.DEFAULT_LIB_DIR
        active_lib_dir.mkdir(parents=True, exist_ok=True)
        chrome_path = active_lib_dir / "chromium"
        node_path = active_lib_dir / "node"
        chrome_path.write_text("#!/bin/sh\n")
        node_path.write_text("#!/bin/sh\n")
        external_path = Path("/tmp/archivebox-test-external-node")
        external_path.touch()
        cleanup_paths.extend([chrome_path, node_path, external_path])
        machine = Machine.current()
        machine.config = {
            "CHROME_BINARY": str(chrome_path),
            "NODE_BINARY": str(node_path),
            "ABX_INSTALL_CACHE": {"wget": "2026-03-24T00:00:00+00:00"},
            "CHROME_ISOLATION": "snapshot",
            "CHROME_USER_DATA_DIR": "/tmp/profile",
            "CHROMIUM_VERSION": "123.4.5",
            "YTDLP_BINARY": str(external_path),
            "WGET_BINARY": "/tmp/archivebox-test-missing-wget",
        }
        machine.save(update_fields=["config"])
        models._CURRENT_MACHINE = machine

        refreshed = Machine.current(refresh=True)

        # Valid binary paths inside LIB_DIR survive.
        assert refreshed.config.get("CHROME_BINARY") == str(chrome_path)
        assert refreshed.config.get("NODE_BINARY") == str(node_path)
        # Non-binary mirror keys survive — they belong to ArchiveBox.conf.
        assert refreshed.config.get("ABX_INSTALL_CACHE") == {"wget": "2026-03-24T00:00:00+00:00"}
        assert refreshed.config.get("CHROME_ISOLATION") == "snapshot"
        assert refreshed.config.get("CHROME_USER_DATA_DIR") == "/tmp/profile"
        assert refreshed.config.get("CHROMIUM_VERSION") == "123.4.5"
        # Stale binary paths get dropped: YTDLP_BINARY outside LIB_DIR,
        # WGET_BINARY path doesn't exist.
        assert "YTDLP_BINARY" not in refreshed.config
        assert "WGET_BINARY" not in refreshed.config

    def test_get_config_auto_applies_current_machine_config(self, cleanup_paths):
        """get_config() applies the full Machine.config mirror as scope overrides.

        ``Machine.config`` mirrors ``ArchiveBox.conf``, so non-binary user keys
        like ``CHROME_ISOLATION`` flow through into the merged ``get_config()``
        result alongside validated binary paths.
        """
        import archivebox.machine.models as models
        from archivebox.config.common import get_config

        lib_dir = get_config(include_machine=False).LIB_DIR
        chrome_path = lib_dir / "chromium"
        chrome_path.parent.mkdir(parents=True, exist_ok=True)
        chrome_path.write_text("#!/bin/sh\n")
        cleanup_paths.append(chrome_path)
        machine = Machine.current()
        machine.config = {
            "CHROME_BINARY": str(chrome_path),
            "ABX_INSTALL_CACHE": {"chrome": "2026-03-24T00:00:00+00:00"},
            "CHROME_ISOLATION": "snapshot",
        }
        machine.save(update_fields=["config"])
        models._CURRENT_MACHINE = machine

        config = get_config()

        assert config.CHROME_BINARY == str(chrome_path)
        assert config.CHROME_ISOLATION == "snapshot"

    def test_machine_manager_current(self):
        """Machine.objects.current() should return current machine."""
        machine = Machine.current()
        assert machine is not None
        assert machine.id == Machine.current().id


class TestNetworkInterfaceModel:
    """Test the NetworkInterface model."""

    def test_networkinterface_current_creates_interface(self):
        """NetworkInterface.current() should create an interface if none exists."""
        interface = NetworkInterface.current()

        assert interface is not None
        assert interface.id is not None
        assert interface.machine is not None
        assert interface.ip_local is not None

    def test_networkinterface_current_returns_cached(self):
        """NetworkInterface.current() should return cached interface within recheck interval."""
        interface1 = NetworkInterface.current()
        interface2 = NetworkInterface.current()

        assert interface1.id == interface2.id

    def test_networkinterface_manager_current(self):
        """NetworkInterface.objects.current() should return current interface."""
        interface = NetworkInterface.current()
        assert interface is not None


class TestBinaryModel:
    """Test the Binary model."""

    @pytest.fixture(autouse=True)
    def setup_machine(self, machine):
        self.machine = machine

    def test_binary_creation(self):
        """Binary should be created with default values."""
        binary = Binary.objects.create(
            machine=self.machine,
            name="wget",
            binproviders="apt,brew,env",
        )

        assert binary.id is not None
        assert binary.name == "wget"
        assert binary.status == Binary.StatusChoices.QUEUED
        assert not binary.is_valid

    def test_binary_is_valid(self):
        """Binary.is_valid should be True for installed binaries with a resolved path."""
        binary = Binary.objects.create(
            machine=self.machine,
            name="wget",
            abspath="/usr/bin/wget",
            version="1.21",
            status=Binary.StatusChoices.INSTALLED,
        )

        assert binary.is_valid

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

        assert result is not None
        assert result.abspath == "/usr/bin/wget"

    def test_binary_update_and_requeue(self):
        """Binary.update_and_requeue() should update fields and save."""
        binary = Binary.objects.create(machine=self.machine, name="test")
        old_modified = binary.modified_at

        binary.update_and_requeue(
            status=Binary.StatusChoices.QUEUED,
            retry_at=timezone.now() + timedelta(seconds=60),
        )

        binary.refresh_from_db()
        assert binary.status == Binary.StatusChoices.QUEUED
        assert binary.modified_at > old_modified

    def test_binary_from_json_preserves_provider_overrides(self):
        """Binary.from_json() should persist provider overrides unchanged."""
        overrides = {
            "apt": {"install_args": ["chromium"]},
            "pnpm": {"install_args": "puppeteer"},
            "custom": {"install": "bash -lc 'echo ok'"},
        }

        binary = Binary.from_json(
            {
                "name": "chrome",
                "binproviders": "apt,pnpm,custom",
                "overrides": overrides,
            },
        )

        assert binary is not None
        assert binary.overrides == overrides

    def test_binary_from_json_canonicalizes_path_like_names(self):
        """Binary.from_json() should store command names, not path cache values."""
        binary = Binary.from_json(
            {
                "name": "/tmp/old-lib/pip/venv/bin/trafilatura",
                "binproviders": "env,pip",
                "overrides": {"pip": {"install_args": ["trafilatura"]}},
            },
        )

        assert binary is not None
        assert binary.name == "trafilatura"

    def test_binary_from_json_does_not_coerce_legacy_override_shapes(self):
        """Binary.from_json() should no longer translate legacy non-dict provider overrides."""
        overrides = {
            "apt": ["chromium"],
            "pnpm": "puppeteer",
        }

        binary = Binary.from_json(
            {
                "name": "chrome",
                "binproviders": "apt,pnpm",
                "overrides": overrides,
            },
        )

        assert binary is not None
        assert binary.overrides == overrides

    def test_binary_from_json_preserves_readability_package_metadata(self):
        """Binary.from_json() should preserve readability's pnpm package metadata."""
        binary = Binary.from_json(
            {
                "name": "readability-extractor",
                "binproviders": "env,pnpm",
                "overrides": {
                    "pnpm": {
                        "install_args": ["readability-extractor"],
                    },
                },
            },
        )

        assert binary is not None
        assert binary.overrides == {
            "pnpm": {
                "install_args": ["readability-extractor"],
            },
        }

    @pytest.mark.django_db(transaction=True)
    def test_binary_lib_bin_symlink_waits_for_outer_transaction_commit(self, tmp_path):
        """Binary DB projection writes can be direct, but LIB_BIN_DIR writes must run after commit."""
        source = tmp_path / "provider" / "bin" / "abx-test-binary"
        source.parent.mkdir(parents=True)
        source.write_text("#!/bin/sh\nexit 0\n")
        source.chmod(0o755)
        lib_bin_dir = tmp_path / "lib" / "bin"
        symlink = lib_bin_dir / "abx-test-binary"

        with transaction.atomic():
            binary = Binary.objects.create(
                machine=self.machine,
                name="abx-test-binary",
                abspath=str(source),
                version="1.0.0",
                status=Binary.StatusChoices.INSTALLED,
            )
            binary.symlink_to_lib_bin_after_commit(lib_bin_dir)
            assert not symlink.exists()

        assert symlink.is_symlink()
        assert symlink.resolve() == source


class TestBinaryStateMachine:
    """Test the BinaryMachine state machine."""

    @pytest.fixture(autouse=True)
    def setup_binary(self, binary):
        self.binary = binary

    def test_binary_state_machine_initial_state(self):
        """BinaryMachine should start in queued state."""
        sm = BinaryMachine(self.binary)
        assert sm.current_state_value == Binary.StatusChoices.QUEUED

    def test_binary_state_machine_can_start(self):
        """BinaryMachine.can_start() should check name and binproviders."""
        sm = BinaryMachine(self.binary)
        assert sm.can_install()

        self.binary.binproviders = ""
        self.binary.save()
        sm = BinaryMachine(self.binary)
        assert not sm.can_install()


class TestProcessModel:
    """Test the Process model."""

    @pytest.fixture(autouse=True)
    def setup_machine(self, machine):
        self.machine = machine

    def test_process_creation(self):
        """Process should be created with default values."""
        process = Process.objects.create(
            machine=self.machine,
            cmd=["echo", "hello"],
            pwd="/tmp",
        )

        assert process.id is not None
        assert process.cmd == ["echo", "hello"]
        assert process.status == Process.StatusChoices.QUEUED
        assert process.pid is None
        assert process.exit_code is None

    def test_process_to_jsonl(self):
        """Process.to_json() should serialize correctly."""
        process = Process.objects.create(
            machine=self.machine,
            cmd=["echo", "hello"],
            pwd="/tmp",
            timeout=60,
        )
        json_data = process.to_json()

        assert json_data["type"] == "Process"
        assert json_data["cmd"] == ["echo", "hello"]
        assert json_data["pwd"] == "/tmp"
        assert json_data["timeout"] == 60

    def test_process_update_and_requeue(self):
        """Process.update_and_requeue() should update fields and save."""
        process = Process.objects.create(machine=self.machine, cmd=["test"])

        process.update_and_requeue(
            status=Process.StatusChoices.RUNNING,
            pid=12345,
            started_at=timezone.now(),
        )

        process.refresh_from_db()
        assert process.status == Process.StatusChoices.RUNNING
        assert process.pid == 12345
        assert process.started_at is not None


class TestProcessCurrent:
    """Test Process.current() method."""

    def test_process_current_creates_record(self):
        """Process.current() should create a Process for current PID."""
        proc = Process.current()

        assert proc is not None
        assert proc.pid == os.getpid()
        assert proc.status == Process.StatusChoices.RUNNING
        assert proc.machine is not None
        assert proc.iface is not None
        assert proc.iface.machine_id == proc.machine_id
        assert proc.started_at is not None

    def test_process_current_caches(self):
        """Process.current() should cache the result."""
        proc1 = Process.current()
        proc2 = Process.current()

        assert proc1.id == proc2.id

    def test_process_detect_type_runner(self):
        """_detect_process_type should detect the background runner command."""
        old_argv = sys.argv
        try:
            sys.argv = ["archivebox", "run", "--daemon"]
            result = Process._detect_process_type()
            assert result == Process.TypeChoices.ORCHESTRATOR
        finally:
            sys.argv = old_argv

    def test_process_detect_type_runner_watch(self):
        """runner_watch should be classified as a worker, not the orchestrator itself."""
        old_argv = sys.argv
        try:
            sys.argv = ["archivebox", "manage", "runner_watch", "--bind-url=http://127.0.0.1:8000"]
            result = Process._detect_process_type()
            assert result == Process.TypeChoices.WORKER
        finally:
            sys.argv = old_argv

    def test_process_detect_type_cli(self):
        """_detect_process_type should detect CLI commands."""
        old_argv = sys.argv
        try:
            sys.argv = ["archivebox", "add", "http://example.com"]
            result = Process._detect_process_type()
            assert result == Process.TypeChoices.ADD
        finally:
            sys.argv = old_argv

    def test_process_detect_type_binary(self):
        """_detect_process_type should detect non-ArchiveBox subprocesses as binary processes."""
        old_argv = sys.argv
        try:
            sys.argv = ["/usr/bin/wget", "https://example.com"]
            result = Process._detect_process_type()
            assert result == Process.TypeChoices.BINARY
        finally:
            sys.argv = old_argv

    def test_process_proc_allows_interpreter_wrapped_script(self, tmp_path):
        """Process.proc should accept a script recorded in DB when wrapped by an interpreter in psutil."""
        import psutil

        script = tmp_path / "on_CrawlSetup__90_chrome_launch.daemon.bg.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, str(script), "--url=https://example.com/"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def cleanup_process():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        try:
            os_proc = psutil.Process(process.pid)
            proc = Process.objects.create(
                machine=Machine.current(),
                cmd=[str(script), "--url=https://example.com/"],
                pid=process.pid,
                status=Process.StatusChoices.RUNNING,
                started_at=timezone.datetime.fromtimestamp(os_proc.create_time(), tz=timezone.get_current_timezone()),
            )

            resolved_proc = proc.proc
            assert resolved_proc is not None
            assert resolved_proc.pid == process.pid
        finally:
            cleanup_process()


class TestProcessHierarchy:
    """Test Process parent/child relationships."""

    @pytest.fixture(autouse=True)
    def setup_machine(self, machine):
        self.machine = machine

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

        assert child.parent == parent
        assert child in parent.children.all()

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

        assert grandchild.root == root
        assert child.root == root
        assert root.root == root

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

        assert root.depth == 0
        assert child.depth == 1


class TestProcessLifecycle:
    """Test Process lifecycle methods."""

    @pytest.fixture(autouse=True)
    def setup_machine(self, machine):
        self.machine = machine

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

        assert proc.is_running

    def test_process_is_running_fake_pid(self):
        """is_running should be False for non-existent PID."""
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now(),
        )

        assert not proc.is_running

    def test_process_poll_detects_exit(self):
        """poll() should detect exited process."""
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now(),
        )

        exit_code = proc.poll()

        assert exit_code is not None
        proc.refresh_from_db()
        assert proc.status == Process.StatusChoices.EXITED

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

        assert exit_code == 137
        proc.refresh_from_db()
        assert proc.exit_code == 137

    def test_process_terminate_dead_process(self):
        """terminate() should handle already-dead process."""
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now(),
        )

        result = proc.terminate()

        assert not result
        proc.refresh_from_db()
        assert proc.status == Process.StatusChoices.EXITED


class TestProcessClassMethods:
    """Test Process class methods for querying."""

    @pytest.fixture(autouse=True)
    def setup_machine(self, machine):
        self.machine = machine

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

        assert proc in running

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
        assert count >= 3

    def test_cleanup_stale_running(self):
        """cleanup_stale_running should mark stale processes as exited."""
        stale = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            started_at=timezone.now() - PID_REUSE_WINDOW - timedelta(hours=1),
        )

        cleaned = Process.cleanup_stale_running()

        assert cleaned >= 1
        stale.refresh_from_db()
        assert stale.status == Process.StatusChoices.EXITED

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

        assert cleaned >= 1
        stale.refresh_from_db()
        assert stale.status == Process.StatusChoices.EXITED

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

        cleaned = Process.cleanup_stale_running()

        assert cleaned >= 1
        stale.refresh_from_db()
        assert stale.status == Process.StatusChoices.EXITED

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

        cleaned = Process.cleanup_orphaned_workers()

        assert cleaned == 1
        child.refresh_from_db()
        assert child.status == Process.StatusChoices.EXITED

    def test_cleanup_orphaned_workers_marks_non_running_children_exited(self):
        """cleanup_orphaned_workers should retire child rows whose OS process is already gone."""
        child = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=999997,
            started_at=timezone.now() - timedelta(minutes=5),
        )

        cleaned = Process.cleanup_orphaned_workers()

        assert cleaned == 1
        child.refresh_from_db()
        assert child.status == Process.StatusChoices.EXITED
        assert child.ended_at is not None
        assert child.exit_code == 143


class TestProcessStateMachine:
    """Test the ProcessMachine state machine."""

    @pytest.fixture(autouse=True)
    def setup_process(self, process):
        self.process = process

    def test_process_state_machine_initial_state(self):
        """ProcessMachine should start in queued state."""
        sm = ProcessMachine(self.process)
        assert sm.current_state_value == Process.StatusChoices.QUEUED

    def test_process_state_machine_can_start(self):
        """ProcessMachine.can_start() should check cmd and machine."""
        sm = ProcessMachine(self.process)
        assert sm.can_start()

        self.process.cmd = []
        self.process.save()
        sm = ProcessMachine(self.process)
        assert not sm.can_start()

    def test_process_state_machine_is_exited(self):
        """ProcessMachine.is_exited() should check exit_code."""
        sm = ProcessMachine(self.process)
        assert not sm.is_exited()

        self.process.exit_code = 0
        self.process.save()
        sm = ProcessMachine(self.process)
        assert sm.is_exited()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
