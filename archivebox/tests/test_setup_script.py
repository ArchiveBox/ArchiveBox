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
