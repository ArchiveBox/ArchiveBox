import textwrap
from pathlib import Path

import pytest

from archivebox.machine.models import Binary, Machine, Process
from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def _runtime_env(data_dir: Path, **extra: str) -> dict[str, str]:
    return {
        "ABXPKG_LIB_DIR": str(data_dir / "lib"),
        "PLUGINS": "liteparse",
        "LITEPARSE_ENABLED": "True",
        "TIMEOUT": "180",
        "ABXPKG_INSTALL_TIMEOUT": "180",
        **extra,
    }


def test_install_persists_machine_binary_config_and_recovers_stale_path(initialized_archive, tmp_path):
    _cmd_result = run_archivebox_cmd(
        ["install", "liteparse"],
        cwd=initialized_archive,
        timeout=240,
        env=_runtime_env(initialized_archive),
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert returncode == 0, stdout + stderr
    assert "liteparse" in stdout

    with use_archivebox_db(initialized_archive):
        liteparse_binary = Binary.objects.get(name="lit")
        machine = Machine.objects.get(pk=liteparse_binary.machine_id)
        machine.config = {}
        machine.save(update_fields=["config"])
        machine_id = machine.id
        binaries = list(Binary.objects.filter(status=Binary.StatusChoices.INSTALLED).order_by("name"))
        process = Process.objects.filter(process_type=Process.TypeChoices.BINARY).latest("created_at")

    installed_liteparse_path = Path(liteparse_binary.abspath)
    assert installed_liteparse_path.exists()
    assert installed_liteparse_path.is_relative_to(initialized_archive / "lib")
    assert binaries
    assert process.status == Process.StatusChoices.EXITED
    assert process.exit_code == 0

    tesseract_binary = next(binary for binary in binaries if binary.name == "tesseract")
    external_tool = Path(tesseract_binary.abspath)
    assert external_tool.is_file()
    assert external_tool.is_relative_to(initialized_archive / "lib")
    machine_event_script = textwrap.dedent(
        f"""
        import asyncio

        from abx_dl.events import MachineEvent
        from abx_dl.orchestrator import create_bus
        from archivebox.services.machine_service import MachineService

        async def main():
            bus = create_bus(name="machine_service_e2e")
            try:
                MachineService(bus)
                await bus.emit(MachineEvent(config={{
                    "LITEPARSE_BINARY": "/tmp/user-config-must-not-persist",
                    "CHROME_USER_DATA_DIR": "/tmp/profile",
                }}, config_type="user")).now()
                await bus.emit(MachineEvent(config={{
                    "LITEPARSE_BINARY": {str(installed_liteparse_path)!r},
                    "LITEPARSE_TESSERACT_BINARY": {str(external_tool)!r},
                    "ABX_INSTALL_CACHE": {{"lit": "cached"}},
                    "ABX_UV_CACHE": "/tmp/uv-cache",
                    "CHROME_USER_DATA_DIR": "/tmp/derived-profile",
                }}, config_type="derived")).now()
                await bus.emit(MachineEvent(method="unset", key="config/LITEPARSE_BINARY", config_type="derived")).now()
                await bus.emit(MachineEvent(
                    method="update",
                    key="config/LITEPARSE_BINARY",
                    value={str(installed_liteparse_path)!r},
                    config_type="derived",
                )).now()
                await bus.wait_until_idle()
            finally:
                await bus.destroy()

        asyncio.run(main())
        print("MACHINE_SERVICE_E2E_DONE")
        """,
    )
    _cmd_result = run_archivebox_cmd(
        ["shell", "-c", machine_event_script],
        cwd=initialized_archive,
        timeout=60,
        env=_runtime_env(initialized_archive),
    )
    shell_stdout, shell_stderr, shell_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert shell_code == 0, shell_stdout + shell_stderr
    assert "MACHINE_SERVICE_E2E_DONE" in shell_stdout

    with use_archivebox_db(initialized_archive):
        machine = Machine.objects.get(pk=machine_id)

    assert machine.config["LITEPARSE_BINARY"] == str(installed_liteparse_path)
    assert machine.config["LITEPARSE_TESSERACT_BINARY"] == str(external_tool)
    assert machine.config["LITEPARSE_BINARY"] != "/tmp/user-config-must-not-persist"
    assert machine.config["ABX_INSTALL_CACHE"] == {"lit": "cached"}
    assert machine.config["ABX_UV_CACHE"] == "/tmp/uv-cache"

    _cmd_result = run_archivebox_cmd(
        ["version"],
        cwd=initialized_archive,
        timeout=60,
        env=_runtime_env(initialized_archive),
    )
    version_stdout, version_stderr, version_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert version_code == 0, version_stderr
    assert "lit" in version_stdout

    installed_liteparse_path.unlink()

    _cmd_result = run_archivebox_cmd(
        ["version"],
        cwd=initialized_archive,
        timeout=60,
        env=_runtime_env(initialized_archive),
    )
    cleanup_stdout, cleanup_stderr, cleanup_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert cleanup_code == 0, cleanup_stdout + cleanup_stderr

    with use_archivebox_db(initialized_archive):
        cleaned_machine_config = Machine.objects.get(pk=machine_id).config or {}

    assert "LITEPARSE_BINARY" not in cleaned_machine_config
