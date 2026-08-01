from pathlib import Path


SETUP_SCRIPT = Path(__file__).parents[2] / "bin" / "setup.sh"


def test_setup_script_creates_archivebox_user_instead_of_rejecting_root():
    script = SETUP_SCRIPT.read_text()

    assert "You cannot run this script as root" not in script
    assert "useradd --system --create-home" in script
    assert 'ARCHIVEBOX_SYSTEM_USER="archivebox"' in script


def test_setup_script_never_recursively_chowns_collection_data():
    script = SETUP_SCRIPT.read_text()

    assert 'chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" "$HOME/archivebox" "$HOME/archivebox/data"' in script
    assert "chown -R" not in "\n".join(line for line in script.splitlines() if "archivebox/data" in line)


def test_setup_script_bootstraps_locked_abxpkg_version():
    script = SETUP_SCRIPT.read_text()

    assert 'ABXPKG_PACKAGE="${ABXPKG_PACKAGE:-abxpkg==1.12.41}"' in script
