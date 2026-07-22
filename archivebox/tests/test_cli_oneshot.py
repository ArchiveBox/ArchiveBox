from importlib.metadata import version

from archivebox.tests.conftest import run_archivebox_cmd


def test_oneshot_runs_abx_dl_through_abxpkg_env_projection(tmp_path):
    lib_dir = tmp_path / "lib"

    result = run_archivebox_cmd(
        ["oneshot", "--version"],
        cwd=tmp_path,
        env={"ABXPKG_LIB_DIR": str(lib_dir)},
    )

    abx_dl_projection = lib_dir / "env" / "bin" / "abx-dl"
    assert result.returncode == 0, result.stderr
    assert version("abx-dl") in result.stdout
    assert abx_dl_projection.is_symlink()
    assert abx_dl_projection.resolve().is_file()
