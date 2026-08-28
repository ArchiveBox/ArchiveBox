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
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from django.db import IntegrityError
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
    PROCESS_PID_NAMESPACE_KEY,
    get_current_pid_namespace,
)
from archivebox.machine.detect import unknown_if_blank
from archivebox.tests.conftest import install_real_binary, resolve_abxpkg_binary_env

pytestmark = pytest.mark.django_db(transaction=True)


def _current_process_started_at():
    import psutil

    return datetime.fromtimestamp(
        psutil.Process(os.getpid()).create_time(),
        tz=timezone.get_current_timezone(),
    )


def _spawn_blocked_process(binary_abspath: str):
    import psutil

    process = subprocess.Popen(
        [binary_abspath, "-c", "print('READY', flush=True); input()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline() == "READY\n"
    started_at = datetime.fromtimestamp(
        psutil.Process(process.pid).create_time(),
        tz=timezone.get_current_timezone(),
    )
    return process, started_at


def _reaped_process_identity(binary_abspath: str) -> tuple[int, datetime]:
    process, started_at = _spawn_blocked_process(binary_abspath)
    assert process.stdin is not None
    process.stdin.write("\n")
    process.stdin.flush()
    assert process.wait(timeout=5) == 0
    return process.pid, started_at


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
    from archivebox.tests.conftest import install_real_binary

    return install_real_binary("python", machine=machine)


@pytest.fixture
def process(machine, binary, tmp_path):
    return Process.objects.create(
        machine=machine,
        binary=binary,
        cmd=[binary.abspath, "--version"],
        pwd=str(tmp_path),
    )


@pytest.fixture
def live_process_identity_factory(binary):
    processes = []

    def spawn() -> tuple[int, datetime]:
        process, started_at = _spawn_blocked_process(binary.abspath)
        processes.append(process)
        return process.pid, started_at

    yield spawn
    for process in processes:
        if process.poll() is None:
            assert process.stdin is not None
            process.stdin.write("\n")
            process.stdin.flush()
            assert process.wait(timeout=5) == 0


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

    def test_machine_from_jsonl_update(self, hermetic_lib_dir):
        """Machine.from_json() should update machine config."""
        Machine.current()  # Ensure machine exists
        install_real_binary("wget", binproviders="env,apt,brew")
        resolve_abxpkg_binary_env(hermetic_lib_dir, "wget")
        wget_path = hermetic_lib_dir / "env" / "bin" / "wget"
        assert wget_path.is_symlink()
        record = {
            "config": {
                "WGET_BINARY": str(wget_path),
            },
        }

        result = Machine.from_json(record)

        assert result is not None
        assert result.config.get("WGET_BINARY") == str(wget_path)

    def test_machine_from_jsonl_drops_invalid_binary_paths_keeps_mirror(self, hermetic_lib_dir):
        """Machine.from_json() drops invalid binary paths but mirrors other keys.

        ``Machine.config`` mirrors ``ArchiveBox.conf`` (non-binary user config
        keys live alongside derived binary state), so non-binary keys in the
        import survive. Only ``_BINARY`` paths get validated/dropped on import.
        """
        Machine.current()  # Ensure machine exists
        install_real_binary("wget", binproviders="env,apt,brew")
        resolve_abxpkg_binary_env(hermetic_lib_dir, "wget")
        wget_path = hermetic_lib_dir / "env" / "bin" / "wget"
        assert wget_path.is_symlink()
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

    def test_machine_current_drops_invalid_binary_paths_keeps_mirror(self, hermetic_lib_dir):
        """Machine.current() mirrors ArchiveBox.conf, only drops invalid binaries.

        ``Machine.config`` is the file ↔ DB mirror of ``ArchiveBox.conf``, so
        non-binary keys (``CHROME_ISOLATION``, ``CHROMIUM_VERSION``, etc.) are
        preserved on read. Only ``_BINARY`` paths get validated against
        ``ABXPKG_LIB_DIR`` and dropped when stale/missing.
        """
        import archivebox.machine.models as models

        install_real_binary("node", binproviders="env,apt,brew")
        install_real_binary("wget", binproviders="env,apt,brew")
        resolve_abxpkg_binary_env(hermetic_lib_dir, "node", "wget")
        chrome_path = hermetic_lib_dir / "env" / "bin" / "node"
        node_path = hermetic_lib_dir / "env" / "bin" / "wget"
        external_path = Path(sys.executable)
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

        # Valid binary paths inside ABXPKG_LIB_DIR survive.
        assert refreshed.config.get("CHROME_BINARY") == str(chrome_path)
        assert refreshed.config.get("NODE_BINARY") == str(node_path)
        # Non-binary mirror keys survive — they belong to ArchiveBox.conf.
        assert refreshed.config.get("ABX_INSTALL_CACHE") == {"wget": "2026-03-24T00:00:00+00:00"}
        assert refreshed.config.get("CHROME_ISOLATION") == "snapshot"
        assert refreshed.config.get("CHROME_USER_DATA_DIR") == "/tmp/profile"
        assert refreshed.config.get("CHROMIUM_VERSION") == "123.4.5"
        # Stale binary paths get dropped: YTDLP_BINARY outside ABXPKG_LIB_DIR,
        # WGET_BINARY path doesn't exist.
        assert "YTDLP_BINARY" not in refreshed.config
        assert "WGET_BINARY" not in refreshed.config

    def test_get_config_auto_applies_current_machine_config(self, hermetic_lib_dir):
        """get_config() applies the full Machine.config mirror as scope overrides.

        ``Machine.config`` mirrors ``ArchiveBox.conf``, so non-binary user keys
        like ``CHROME_ISOLATION`` flow through into the merged ``get_config()``
        result alongside validated binary paths.
        """
        import archivebox.machine.models as models
        from archivebox.config.common import get_config

        lib_dir = get_config(include_machine=False).ABXPKG_LIB_DIR
        assert lib_dir == hermetic_lib_dir
        install_real_binary("node", binproviders="env,apt,brew")
        resolve_abxpkg_binary_env(lib_dir, "node")
        chrome_path = lib_dir / "env" / "bin" / "node"
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

    def test_networkinterface_optional_location_fields_default_to_blank(self, machine):
        interface = NetworkInterface.objects.create(
            machine=machine,
            mac_address="00:00:00:00:00:01",
            ip_public="127.0.0.1",
            ip_local="127.0.0.1",
            dns_server="127.0.0.1",
        )

        assert interface.hostname == ""
        assert interface.iface == ""
        assert interface.isp == ""
        assert interface.city == ""
        assert interface.region == ""
        assert interface.country == ""

    def test_unknown_if_blank_normalizes_null_api_fields(self):
        assert unknown_if_blank(None) == "Unknown"
        assert unknown_if_blank("") == "Unknown"
        assert unknown_if_blank("  ") == "Unknown"
        assert unknown_if_blank("California") == "California"

    def test_networkinterface_identity_ignores_randomized_mac_address(self, machine):
        NetworkInterface.objects.create(
            machine=machine,
            mac_address="00:00:00:00:00:01",
            ip_public="127.0.0.1",
            ip_local="127.0.0.1",
            dns_server="127.0.0.1",
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            NetworkInterface.objects.create(
                machine=machine,
                mac_address="00:00:00:00:00:02",
                ip_public="127.0.0.1",
                ip_local="127.0.0.1",
                dns_server="127.0.0.1",
            )


@pytest.mark.django_db(transaction=True)
class TestBinaryModel:
    """Test the Binary model."""

    @pytest.fixture(autouse=True)
    def setup_machine(self, machine):
        self.machine = machine

    def test_binary_creation(self):
        """A resolved Binary should persist its detected installation."""
        from archivebox.tests.conftest import install_real_binary

        binary = install_real_binary("python", machine=self.machine)

        assert binary.id is not None
        assert binary.name == "python"
        assert binary.status == Binary.StatusChoices.INSTALLED
        assert binary.is_valid

    def test_binary_is_valid(self):
        """Binary.is_valid should be True for installed binaries with a resolved path."""
        from archivebox.tests.conftest import install_real_binary

        binary = install_real_binary("python", machine=self.machine)

        assert binary.is_valid

    def test_binary_manager_get_valid_binary(self):
        """BinaryManager.get_valid_binary() should find valid binaries."""
        from archivebox.tests.conftest import install_real_binary

        binary = install_real_binary("python", machine=self.machine)

        result = cast(BinaryManager, Binary.objects).get_valid_binary("python")

        assert result is not None
        assert result.id == binary.id
        assert Path(result.abspath).resolve() == Path(sys.executable).resolve()

    def test_binary_update_and_requeue(self):
        """Binary.update_and_requeue() should update fields and save."""
        from archivebox.tests.conftest import install_real_binary

        binary = install_real_binary("python", machine=self.machine)
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

        from archivebox.tests.conftest import install_real_binary

        binary = install_real_binary("python", machine=self.machine, overrides=overrides)

        assert binary is not None
        assert binary.overrides == overrides

    def test_binary_from_json_preserves_provider_package_metadata(self):
        """A real Binary install should preserve provider-specific package metadata."""
        from archivebox.tests.conftest import install_real_binary

        binary = install_real_binary(
            "python",
            machine=self.machine,
            overrides={"pip": {"install_args": ["python"]}},
        )

        assert binary is not None
        assert binary.overrides == {
            "pip": {
                "install_args": ["python"],
            },
        }

    @pytest.mark.django_db(transaction=True)
    def test_binary_lib_bin_symlink_waits_for_outer_transaction_commit(self, tmp_path):
        """Binary DB projection writes can be direct, but convenience symlinks must run after commit."""
        from archivebox.tests.conftest import install_real_binary

        binary = install_real_binary("python", machine=self.machine)
        source = Path(binary.abspath)
        lib_bin_dir = tmp_path / "lib" / "bin"
        symlink = lib_bin_dir / "python"

        with transaction.atomic():
            binary.symlink_to_lib_bin_after_commit(lib_bin_dir)
            assert not symlink.exists()

        assert symlink.is_symlink()
        assert symlink.resolve() == source.resolve()


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
    def setup_machine(self, machine, binary, tmp_path):
        self.machine = machine
        self.binary = binary
        self.pwd = str(tmp_path)

    def test_process_creation(self):
        """Process should be created with default values."""
        process = Process.objects.create(
            machine=self.machine,
            binary=self.binary,
            cmd=[self.binary.abspath, "--version"],
            pwd=self.pwd,
        )

        assert process.id is not None
        assert process.cmd == [self.binary.abspath, "--version"]
        assert process.status == Process.StatusChoices.QUEUED
        assert process.pid is None
        assert process.exit_code is None

    def test_process_to_jsonl(self):
        """Process.to_json() should serialize correctly."""
        process = Process.objects.create(
            machine=self.machine,
            binary=self.binary,
            cmd=[self.binary.abspath, "--version"],
            pwd=self.pwd,
            timeout=60,
        )
        json_data = process.to_json()

        assert json_data["type"] == "Process"
        assert json_data["cmd"] == [self.binary.abspath, "--version"]
        assert json_data["pwd"] == self.pwd
        assert json_data["timeout"] == 60

    def test_process_update_and_requeue(self):
        """Process.update_and_requeue() should update fields and save."""
        process = Process.objects.create(
            machine=self.machine,
            binary=self.binary,
            cmd=[self.binary.abspath, "--version"],
            pwd=self.pwd,
        )

        process.update_and_requeue(
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=_current_process_started_at(),
        )

        process.refresh_from_db()
        assert process.status == Process.StatusChoices.RUNNING
        assert process.pid == os.getpid()
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
        assert proc.env[PROCESS_PID_NAMESPACE_KEY] == get_current_pid_namespace()

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

    def test_process_proc_allows_interpreter_wrapped_script(self, binary):
        """Process.proc should accept a script recorded in DB when wrapped by an interpreter in psutil."""
        import psutil

        script = Path(__file__).parents[1] / "cli" / "archivebox_manage.py"
        process = subprocess.Popen(
            [binary.abspath, str(script), "shell"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            os_proc = psutil.Process(process.pid)
            proc = Process.objects.create(
                machine=Machine.current(),
                cmd=[str(script), "shell"],
                pid=process.pid,
                status=Process.StatusChoices.RUNNING,
                started_at=timezone.datetime.fromtimestamp(os_proc.create_time(), tz=timezone.get_current_timezone()),
            )

            resolved_proc = proc.proc
            assert resolved_proc is not None
            assert resolved_proc.pid == process.pid
        finally:
            assert process.stdin is not None
            process.stdin.close()
            process.wait(timeout=30)


class TestProcessHierarchy:
    """Test Process parent/child relationships."""

    @pytest.fixture(autouse=True)
    def setup_machine(self, machine):
        self.machine = machine

    def test_process_parent_child(self, live_process_identity_factory):
        """Process should track parent/child relationships."""
        parent_pid, parent_started_at = live_process_identity_factory()
        child_pid, child_started_at = live_process_identity_factory()
        parent = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.CLI,
            status=Process.StatusChoices.RUNNING,
            pid=parent_pid,
            started_at=parent_started_at,
        )

        child = Process.objects.create(
            machine=self.machine,
            parent=parent,
            process_type=Process.TypeChoices.WORKER,
            status=Process.StatusChoices.RUNNING,
            pid=child_pid,
            started_at=child_started_at,
        )

        assert child.parent == parent
        assert child in parent.children.all()

    def test_process_root(self, live_process_identity_factory):
        """Process.root should return the root of the hierarchy."""
        root_pid, root_started_at = live_process_identity_factory()
        child_pid, child_started_at = live_process_identity_factory()
        grandchild_pid, grandchild_started_at = live_process_identity_factory()
        root = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.CLI,
            status=Process.StatusChoices.RUNNING,
            pid=root_pid,
            started_at=root_started_at,
        )
        child = Process.objects.create(
            machine=self.machine,
            parent=root,
            status=Process.StatusChoices.RUNNING,
            pid=child_pid,
            started_at=child_started_at,
        )
        grandchild = Process.objects.create(
            machine=self.machine,
            parent=child,
            status=Process.StatusChoices.RUNNING,
            pid=grandchild_pid,
            started_at=grandchild_started_at,
        )

        assert grandchild.root == root
        assert child.root == root
        assert root.root == root

    def test_process_depth(self, live_process_identity_factory):
        """Process.depth should return depth in tree."""
        root_pid, root_started_at = live_process_identity_factory()
        child_pid, child_started_at = live_process_identity_factory()
        root = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=root_pid,
            started_at=root_started_at,
        )
        child = Process.objects.create(
            machine=self.machine,
            parent=root,
            status=Process.StatusChoices.RUNNING,
            pid=child_pid,
            started_at=child_started_at,
        )

        assert root.depth == 0
        assert child.depth == 1


class TestProcessLifecycle:
    """Test Process lifecycle methods."""

    @pytest.fixture(autouse=True)
    def setup_machine(self, machine, binary):
        self.machine = machine
        self.binary = binary

    def test_process_is_running_current_pid(self):
        """is_running should be True for current PID."""
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=_current_process_started_at(),
        )

        assert proc.is_running

    def test_process_is_running_reaped_process(self):
        """is_running should be False after the recorded OS process exits."""
        pid, started_at = _reaped_process_identity(self.binary.abspath)
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=pid,
            started_at=started_at,
        )

        assert not proc.is_running

    def test_cross_namespace_process_is_not_resolved_or_signaled_by_local_pid(self):
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=_current_process_started_at(),
            env={PROCESS_PID_NAMESPACE_KEY: f"{get_current_pid_namespace()}-other"},
        )

        assert not proc.shares_pid_namespace
        assert proc.proc is None
        assert proc.is_running
        assert proc.kill() is False
        assert proc.kill_tree() == 0

        proc.refresh_from_db()
        assert proc.status == Process.StatusChoices.RUNNING

    def test_process_poll_detects_exit(self):
        """poll() should detect exited process."""
        pid, started_at = _reaped_process_identity(self.binary.abspath)
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=pid,
            started_at=started_at,
        )

        exit_code = proc.poll()

        assert exit_code is not None
        proc.refresh_from_db()
        assert proc.status == Process.StatusChoices.EXITED

    def test_process_poll_normalizes_negative_exit_code(self):
        """poll() should normalize -1 exit codes to 137."""
        pid, started_at = _reaped_process_identity(self.binary.abspath)
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.EXITED,
            pid=pid,
            exit_code=-1,
            started_at=started_at,
        )

        exit_code = proc.poll()

        assert exit_code == 137
        proc.refresh_from_db()
        assert proc.exit_code == 137

    def test_process_terminate_dead_process(self):
        """terminate() should handle already-dead process."""
        pid, started_at = _reaped_process_identity(self.binary.abspath)
        proc = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=pid,
            started_at=started_at,
        )

        result = proc.terminate()

        assert not result
        proc.refresh_from_db()
        assert proc.status == Process.StatusChoices.EXITED


class TestProcessClassMethods:
    """Test Process class methods for querying."""

    @pytest.fixture(autouse=True)
    def setup_machine(self, machine, binary):
        self.machine = machine
        self.binary = binary

    def test_get_running(self):
        """get_running should return running processes."""
        proc = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=_current_process_started_at(),
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
                pid=os.getpid(),
                started_at=_current_process_started_at(),
            )

        count = Process.get_running_count(process_type=Process.TypeChoices.HOOK)
        assert count >= 3

    def test_cleanup_stale_running(self):
        """cleanup_stale_running should mark stale processes as exited."""
        pid, _started_at = _reaped_process_identity(self.binary.abspath)
        stale = Process.objects.create(
            machine=self.machine,
            status=Process.StatusChoices.RUNNING,
            pid=pid,
            started_at=timezone.now() - PID_REUSE_WINDOW - timedelta(hours=1),
        )

        cleaned = Process.cleanup_stale_running()

        assert cleaned >= 1
        stale.refresh_from_db()
        assert stale.status == Process.StatusChoices.EXITED

    def test_cleanup_stale_running_marks_timed_out_rows_exited(self):
        """cleanup_stale_running should retire RUNNING rows that exceed timeout + grace."""
        pid, _started_at = _reaped_process_identity(self.binary.abspath)
        stale = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=pid,
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
        parent_pid, parent_started_at = _reaped_process_identity(self.binary.abspath)
        parent = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.CLI,
            status=Process.StatusChoices.RUNNING,
            pid=parent_pid,
            started_at=parent_started_at,
        )
        child = Process.objects.create(
            machine=self.machine,
            parent=parent,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=_current_process_started_at(),
        )

        cleaned = Process.cleanup_orphaned_workers()

        assert cleaned == 1
        child.refresh_from_db()
        assert child.status == Process.StatusChoices.EXITED

    def test_cleanup_orphaned_workers_marks_non_running_children_exited(self):
        """cleanup_orphaned_workers should retire child rows whose OS process is already gone."""
        pid, started_at = _reaped_process_identity(self.binary.abspath)
        child = Process.objects.create(
            machine=self.machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=pid,
            started_at=started_at,
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
