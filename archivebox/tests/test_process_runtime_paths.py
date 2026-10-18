from importlib.resources import files
from pathlib import Path

import pytest

from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


class TestProcessRuntimePaths:
    def test_hook_processes_keep_execution_specific_log_paths(self, tmp_path):
        from archivebox.machine.models import PROCESS_STDERR_FILE_KEY, PROCESS_STDOUT_FILE_KEY
        from archivebox.tests.conftest import run_test_hook

        snap_dir = tmp_path / "snapshot"
        output_dir = snap_dir / "hashes"
        output_dir.mkdir(parents=True)
        (snap_dir / "source.txt").write_text("real runtime path input", encoding="utf-8")
        hook_path = Path(str(files("abx_plugins.plugins.hashes").joinpath("on_Snapshot__93_hashes.py")))
        log_paths = set()
        for _ in range(2):
            process = run_test_hook(
                hook_path,
                output_dir,
                config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "SNAP_DIR": str(snap_dir)},
                timeout=30,
                url="https://archivebox.io/tests/runtime-path",
            )
            process.refresh_from_db()
            assert process.exit_code == 0, process.stderr
            assert "Hash generation started" in process.stderr
            assert any(record.get("status") == "succeeded" for record in process.get_records())
            for path, key, suffix in (
                (process.stdout_file, PROCESS_STDOUT_FILE_KEY, ".stdout.log"),
                (process.stderr_file, PROCESS_STDERR_FILE_KEY, ".stderr.log"),
            ):
                assert path == Path(process.env[key])
                assert path.name.startswith(f"{hook_path.stem}.")
                assert path.name.endswith(suffix)
                assert path not in log_paths
                log_paths.add(path)

    def test_non_hook_processes_keep_runtime_files_in_pwd(self, tmp_path):
        init_result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, timeout=90)
        assert init_result.returncode == 0, init_result.stderr or init_result.stdout
        add_result = run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", "https://example.com/runtime-path"],
            cwd=tmp_path,
            timeout=90,
        )
        assert add_result.returncode == 0, add_result.stderr or add_result.stdout

        with use_archivebox_db(tmp_path):
            from archivebox.machine.models import Process

            process = next(
                row for row in Process.objects.order_by("-created_at") if "add" in row.cmd and row.process_type != Process.TypeChoices.HOOK
            )

        expected_dir = Path(process.pwd)
        assert process.status == Process.StatusChoices.EXITED
        assert process.exit_code == 0
        assert process.runtime_dir == expected_dir
        assert process.stdout_file == expected_dir / "stdout.log"
        assert process.stderr_file == expected_dir / "stderr.log"
