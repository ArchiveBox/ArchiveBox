import tempfile
from importlib.metadata import version
from pathlib import Path

from archivebox.tests.conftest import run_archivebox_cmd


def test_oneshot_runs_abx_dl_through_abxpkg_env_projection():
    with tempfile.TemporaryDirectory(prefix="archivebox-oneshot-") as tmp_dir:
        work_dir = Path(tmp_dir)
        lib_dir = work_dir / "lib"

        result = run_archivebox_cmd(
            ["oneshot", "--version"],
            cwd=work_dir,
            env={"ABXPKG_LIB_DIR": str(lib_dir)},
        )

        abx_dl_projection = lib_dir / "env" / "bin" / "abx-dl"
        assert result.returncode == 0, result.stderr
        assert version("abx-dl") in result.stdout
        assert abx_dl_projection.is_symlink()
        assert abx_dl_projection.resolve().is_file()
