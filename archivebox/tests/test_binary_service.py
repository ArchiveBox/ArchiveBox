import sys
import uuid
import asyncio
import shutil
from pathlib import Path

import pytest
from django.utils import timezone

from archivebox.machine.models import Binary, Machine, Process
from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def _runtime_env(data_dir: Path, *, lib_dir: Path | None = None, **extra: str) -> dict[str, str]:
    lib_dir = lib_dir or data_dir / "lib"
    return {
        "ABXPKG_LIB_DIR": str(lib_dir),
        **extra,
    }


def _run_real_binary_state_machine(data_dir: Path, *, name: str, binproviders: str, env: dict[str, str]):
    """Run a real Binary model through its abxpkg-backed state machine."""
    script = (
        "from archivebox.machine.models import Binary, Machine; "
        f"binary = Binary.objects.create(machine=Machine.current(), name={name!r}, binproviders={binproviders!r}, status=Binary.StatusChoices.QUEUED); "
        "assert binary.tick_claimed(lock_seconds=600); "
        "print('BINARY_STATE_MACHINE_E2E_DONE')"
    )
    return run_archivebox_cmd(
        ["shell", "-c", script],
        cwd=data_dir,
        timeout=120,
        env=env,
        default_cli_env=True,
        disable_extractors=True,
    )


def test_binary_request_preserves_native_overrides_in_db():
    from abxpkg.binary_service import BinaryEvent, BinaryRequestEvent, BinaryService
    from abx_dl.orchestrator import create_bus
    from archivebox.services.binary_service import ArchiveBoxBinaryService

    machine = Machine.current()
    overrides = {
        "pip": {
            "install_args": ["imagesize>=2.0.0"],
        },
    }
    binary = Binary.objects.create(
        machine=machine,
        name="python3",
        binproviders="env,pip",
        overrides=overrides,
        status=Binary.StatusChoices.QUEUED,
        retry_at=timezone.now(),
    )
    assert binary.tick_claimed(lock_seconds=600)
    binary.refresh_from_db()
    assert binary.status == Binary.StatusChoices.INSTALLED
    assert Path(binary.abspath).resolve() == Path(sys.executable).resolve()
    bus = create_bus(name=f"test_binary_native_overrides_{uuid.uuid4().hex[:8]}")
    ArchiveBoxBinaryService(bus)
    BinaryService(bus)
    binary_events: list[BinaryEvent] = []

    async def on_BinaryEvent(event: BinaryEvent) -> None:
        binary_events.append(event)

    bus.on(BinaryEvent, on_BinaryEvent)

    async def run_event() -> None:
        await bus.emit(
            BinaryRequestEvent(
                name="python3",
                binproviders="env,pip",
                overrides=overrides,
            ),
        ).now()
        await bus.wait_until_idle()

    asyncio.run(run_event())

    binary.refresh_from_db()
    assert binary.status == Binary.StatusChoices.INSTALLED
    assert binary.overrides == overrides
    assert binary_events
    assert binary_events[-1].overrides == overrides


def test_binary_request_installs_env_binary_and_recovers_stale_cache(initialized_archive, tmp_path):
    name = "archivebox"
    provider_bin_dir = initialized_archive / "lib" / "env" / "bin"
    host_binary = shutil.which(name)
    assert host_binary is not None
    runtime_env = _runtime_env(initialized_archive)
    _cmd_result = _run_real_binary_state_machine(initialized_archive, name=name, binproviders="env", env=runtime_env)
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert returncode == 0, stderr
    assert "BINARY_STATE_MACHINE_E2E_DONE" in stdout

    with use_archivebox_db(initialized_archive):
        binary = Binary.objects.get(name=name)
        machine_id = str(binary.machine_id)
        first_binary_id = str(binary.id)
        first_abspath = Path(binary.abspath)
        binary_processes = list(Process.objects.filter(process_type=Process.TypeChoices.BINARY).order_by("created_at"))

    assert binary.status == Binary.StatusChoices.INSTALLED
    assert binary.version
    assert binary.binprovider == "env"
    assert binary.binproviders == "env"
    assert first_abspath.exists()
    assert first_abspath == provider_bin_dir / name
    assert first_abspath.resolve() == Path(host_binary).resolve()
    assert first_abspath.is_relative_to(initialized_archive / "lib")
    assert (initialized_archive / "lib" / "env" / "bin" / name).exists()
    assert (initialized_archive / "machines" / machine_id / "binaries" / name / "index.jsonl").exists()
    assert binary_processes
    assert binary_processes[-1].status == Process.StatusChoices.EXITED
    assert binary_processes[-1].exit_code == 0
    assert binary_processes[-1].ended_at is not None
    assert binary_processes[-1].started_at < binary_processes[-1].ended_at
    assert any(f"--name={name}" in arg for arg in binary_processes[-1].cmd)

    _cmd_result = run_archivebox_cmd(
        ["version"],
        cwd=initialized_archive,
        timeout=60,
        env=runtime_env,
        default_cli_env=True,
        disable_extractors=True,
    )
    version_stdout, version_stderr, version_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert version_code == 0, version_stderr
    assert name in version_stdout
    assert binary.version in version_stdout

    first_abspath.unlink()

    _cmd_result = run_archivebox_cmd(
        ["run", f"--binary-id={first_binary_id}"],
        cwd=initialized_archive,
        timeout=120,
        env=runtime_env,
        default_cli_env=True,
        disable_extractors=True,
    )
    rerun_stdout, rerun_stderr, rerun_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert rerun_code == 0, rerun_stdout + rerun_stderr
    with use_archivebox_db(initialized_archive):
        recovered = Binary.objects.get(pk=first_binary_id)
        process_count = Process.objects.filter(process_type=Process.TypeChoices.BINARY).count()

    assert recovered.status == Binary.StatusChoices.INSTALLED
    assert recovered.version == binary.version
    assert Path(recovered.abspath).exists()
    assert Path(recovered.abspath).resolve() == Path(host_binary).resolve()
    assert process_count >= 2

    changed_lib_dir = tmp_path / "changed-lib"
    changed_provider_bin_dir = changed_lib_dir / "env" / "bin"
    changed_runtime_env = _runtime_env(
        initialized_archive,
        lib_dir=changed_lib_dir,
    )

    with use_archivebox_db(initialized_archive):
        Binary.objects.get(pk=first_binary_id).update_and_requeue(
            status=Binary.StatusChoices.QUEUED,
            retry_at=None,
        )

    _cmd_result = run_archivebox_cmd(
        ["run", f"--binary-id={first_binary_id}"],
        cwd=initialized_archive,
        timeout=120,
        env=changed_runtime_env,
        default_cli_env=True,
        disable_extractors=True,
    )
    relib_stdout, relib_stderr, relib_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert relib_code == 0, relib_stdout + relib_stderr
    with use_archivebox_db(initialized_archive):
        relibbed = Binary.objects.get(pk=first_binary_id)

    assert relibbed.status == Binary.StatusChoices.INSTALLED
    assert relibbed.version == binary.version
    assert Path(relibbed.abspath) == changed_provider_bin_dir / name
    assert Path(relibbed.abspath).exists()
    assert Path(relibbed.abspath).resolve() == Path(host_binary).resolve()


def test_missing_binary_request_stays_queued_then_recovers_when_provider_can_resolve(initialized_archive, tmp_path):
    name = "http"
    provider_bin_dir = initialized_archive / "lib" / "pip" / "venv" / "bin"
    runtime_env = _runtime_env(initialized_archive)

    _cmd_result = _run_real_binary_state_machine(initialized_archive, name=name, binproviders="env", env=runtime_env)
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert returncode != 0, stdout + stderr
    assert "Binary http installation failed" in stderr

    with use_archivebox_db(initialized_archive):
        queued = Binary.objects.get(name=name)
        queued_id = str(queued.id)
        failed_process = Process.objects.filter(process_type=Process.TypeChoices.BINARY).latest("created_at")
        machine_config = Machine.objects.get(pk=queued.machine_id).config or {}

    assert queued.status == Binary.StatusChoices.QUEUED
    assert queued.abspath == ""
    assert queued.retry_at is not None
    assert failed_process.status == Process.StatusChoices.EXITED
    assert failed_process.exit_code == 1
    assert f"{name.upper().replace('-', '_')}_BINARY" not in machine_config
    assert not (provider_bin_dir / name).exists()

    with use_archivebox_db(initialized_archive):
        queued = Binary.objects.get(pk=queued_id)
        queued.binproviders = "pip"
        queued.overrides = {"pip": {"install_args": ["httpie>=3.2.4"]}}
        queued.save(update_fields=["binproviders", "overrides", "modified_at"])
    recovered_runtime_env = _runtime_env(initialized_archive)

    _cmd_result = run_archivebox_cmd(
        ["run", f"--binary-id={queued_id}"],
        cwd=initialized_archive,
        timeout=120,
        env=recovered_runtime_env,
        default_cli_env=True,
        disable_extractors=True,
    )
    recover_stdout, recover_stderr, recover_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert recover_code == 0, recover_stdout + recover_stderr
    with use_archivebox_db(initialized_archive):
        recovered = Binary.objects.get(pk=queued_id)
        process_exit_codes = list(
            Process.objects.filter(process_type=Process.TypeChoices.BINARY).order_by("created_at").values_list("exit_code", flat=True),
        )

    assert recovered.status == Binary.StatusChoices.INSTALLED
    assert recovered.version
    assert Path(recovered.abspath).exists()
    assert Path(recovered.abspath) == provider_bin_dir / name
    assert recovered.binprovider == "pip"
    assert Path(recovered.abspath).is_file()
    assert process_exit_codes[-2:] == [1, 0]
