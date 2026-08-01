import os
import subprocess
from pathlib import Path


SETUP_SCRIPT = Path(__file__).parents[2] / "bin" / "setup.sh"


def test_setup_script_creates_archivebox_user_instead_of_rejecting_root():
    script = SETUP_SCRIPT.read_text()

    assert "You cannot run this script as root" not in script
    assert "useradd --system --create-home" in script
    assert 'ARCHIVEBOX_SYSTEM_USER="archivebox"' in script


def test_setup_script_never_recursively_chowns_collection_data():
    script = SETUP_SCRIPT.read_text()

    assert 'chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" "$ARCHIVEBOX_HOME_DIR" "$ARCHIVEBOX_DATA_DIR"' in script
    assert "chown -R" not in "\n".join(line for line in script.splitlines() if "archivebox/data" in line)


def test_setup_script_bootstraps_locked_abxpkg_version():
    script = SETUP_SCRIPT.read_text()

    assert 'ABXPKG_PACKAGE="${ABXPKG_PACKAGE:-abxpkg==1.12.41}"' in script


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
    assert "server --daemonize 0.0.0.0:8000" in script
    assert 'nohup "$ARCHIVEBOX_BINARY" server' not in script
    assert '"$DOCKER_BINARY" rm -f archivebox' in script
    assert "--connect-timeout 1 --max-time 2" in script


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
