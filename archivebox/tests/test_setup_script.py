import os
import shutil
import subprocess
from pathlib import Path


SETUP_SCRIPT = Path(__file__).parents[2] / "bin" / "setup.sh"


def test_setup_script_creates_archivebox_user_instead_of_rejecting_root():
    script = SETUP_SCRIPT.read_text()

    assert "You cannot run this script as root" not in script
    assert "useradd --system --create-home" in script
    assert 'ARCHIVEBOX_SYSTEM_USER="archivebox"' in script
    assert "${BOOTSTRAP_UV_BINARY#/var/root/}" in script
    assert "mkdir -p /usr/local/bin" in script


def test_setup_script_never_recursively_chowns_collection_data():
    script = SETUP_SCRIPT.read_text()

    assert 'chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" "$ARCHIVEBOX_HOME_DIR" "$ARCHIVEBOX_DATA_DIR"' in script
    assert "chown -R" not in script


def test_setup_script_gives_archivebox_user_ownership_of_runtime_parent_dirs():
    script = SETUP_SCRIPT.read_text()

    assert 'for path in "$HOME/.local" "$HOME/.local/share" "$HOME/.cache" "$HOME/.cache/archivebox" "$HOME/.config"; do' in script
    assert 'chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" "$path"' in script
    assert '"$HOME/.config/uv"' in script


def test_setup_script_bootstraps_locked_abxpkg_version():
    script = SETUP_SCRIPT.read_text()
    prepare_function = script.partition("prepare_abxpkg_environment() {")[2].partition("\n}")[0]
    install_function = script.partition("install_archivebox_with_uv() {")[2].partition("\n}")[0]

    assert 'ABXPKG_PACKAGE="${ABXPKG_PACKAGE:-abxpkg==1.12.58}"' in script
    assert 'ARCHIVEBOX_PACKAGE="${ARCHIVEBOX_PACKAGE:-archivebox}"' in script
    assert '--prerelease allow --upgrade "$ARCHIVEBOX_PACKAGE"' in install_function
    assert "fix_root_install_ownership" in prepare_function
    assert "resolve_setup_binary git env,brew,apt true" in install_function


def test_setup_script_preserves_collection_and_compose_ownership_boundaries():
    script = SETUP_SCRIPT.read_text()

    assert "data|docker-compose.yml|compose.yml|compose.yaml|.env|Caddyfile)" in script
    assert 'mv -n "$path" "$ARCHIVEBOX_DATA_DIR/"' in script
    assert "if [ ! -f docker-compose.yml ]; then" in script
    assert 'chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" docker-compose.yml' in script
    assert 'mv -i "$HOME"/archivebox/*' not in script


def test_setup_script_prints_root_safe_runtime_commands():
    script = SETUP_SCRIPT.read_text()

    assert 'echo "    cd $ARCHIVEBOX_DATA_DIR' in script
    assert "at ~/archivebox/data" not in script
    assert "Server started on http://0.0.0.0" not in script
    assert "server --daemonize 0.0.0.0:8000" in script
    assert 'nohup "$ARCHIVEBOX_BINARY" server' not in script
    assert '"$DOCKER_BINARY" rm -f archivebox' in script
    assert "--connect-timeout 1 --max-time 2" in script


def test_setup_script_does_not_fail_when_clear_cannot_use_terminal():
    script = SETUP_SCRIPT.read_text()

    assert "if [ -t 1 ]; then\n    clear || true\nfi" in script


def test_setup_script_keeps_optional_binary_probes_quiet():
    script = SETUP_SCRIPT.read_text()

    assert "resolve_setup_binary open env false 2>/dev/null" in script
    assert "resolve_setup_binary docker env false 2>/dev/null" in script
    assert 'if [ -n "$OPEN_BINARY" ] && [ -t 1 ]; then' in script


def test_setup_script_selects_collection_library_before_installing_dependencies():
    script = SETUP_SCRIPT.read_text()
    native_install = script.partition(': | "$ARCHIVEBOX_BINARY" init')[2]

    select_library = "select_archivebox_lib_dir"
    install_dependencies = '"$ARCHIVEBOX_BINARY" install'

    assert select_library in native_install
    assert native_install.index(select_library) < native_install.index(install_dependencies)


def test_setup_script_preserves_existing_collection_library(tmp_path):
    archivebox_binary = shutil.which("archivebox")
    assert archivebox_binary

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    bootstrap_lib = tmp_path / "bootstrap-lib"
    configured_lib = tmp_path / "configured-lib"
    command_env = {**os.environ, "HOME": str(tmp_path), "ABXPKG_LIB_DIR": str(bootstrap_lib), "TERM": "dumb"}

    init_result = subprocess.run(
        [archivebox_binary, "init"],
        cwd=data_dir,
        capture_output=True,
        text=True,
        env=command_env,
        timeout=60,
    )
    assert init_result.returncode == 0, init_result.stderr or init_result.stdout

    config_result = subprocess.run(
        [archivebox_binary, "config", "--set", f"ABXPKG_LIB_DIR={configured_lib}"],
        cwd=data_dir,
        capture_output=True,
        text=True,
        env=command_env,
        timeout=60,
    )
    assert config_result.returncode == 0, config_result.stderr or config_result.stdout

    script = SETUP_SCRIPT.read_text()
    function_body = script.partition("select_archivebox_lib_dir() {")[2].partition("\n}")[0]
    harness = tmp_path / "select-library.sh"
    harness.write_text(f"select_archivebox_lib_dir() {{{function_body}\n}}\n")

    select_result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; ARCHIVEBOX_BINARY="$2"; select_archivebox_lib_dir; printf "%s" "$ABXPKG_LIB_DIR"',
            "bash",
            str(harness),
            archivebox_binary,
        ],
        cwd=data_dir,
        capture_output=True,
        text=True,
        env=command_env,
        timeout=60,
    )

    assert select_result.returncode == 0, select_result.stderr or select_result.stdout
    assert select_result.stdout == str(configured_lib)


def test_setup_script_moves_legacy_collection_without_moving_compose(tmp_path):
    script = SETUP_SCRIPT.read_text()
    function_prefix = script.partition("\ndocker_pull_archivebox() {")[0]
    harness = tmp_path / "setup-functions.sh"
    harness.write_text(function_prefix)

    archivebox_home = tmp_path / "archivebox"
    data_dir = archivebox_home / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "existing.txt").write_text("keep")
    (archivebox_home / "index.sqlite3").write_text("legacy-db")
    (archivebox_home / ".archivebox_id").write_text("legacy-id")
    (archivebox_home / "docker-compose.yml").write_text("services: {}")

    result = subprocess.run(
        ["bash", "-c", 'source "$1"; migrate_legacy_collection_dir', "bash", str(harness)],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path), "TERM": "xterm"},
        timeout=10,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert (data_dir / "existing.txt").read_text() == "keep"
    assert (data_dir / "index.sqlite3").read_text() == "legacy-db"
    assert (data_dir / ".archivebox_id").read_text() == "legacy-id"
    assert (archivebox_home / "docker-compose.yml").read_text() == "services: {}"
