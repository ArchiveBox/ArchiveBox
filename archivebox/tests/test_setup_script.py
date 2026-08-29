import subprocess
from pathlib import Path


SETUP_SCRIPT = Path(__file__).parents[2] / "bin" / "setup.sh"


def test_setup_script_is_a_uv_install_shortcut():
    script = SETUP_SCRIPT.read_text()
    install_flow = script.partition("cat <<EOF")[0]

    assert 'ARCHIVEBOX_PYTHON="${ARCHIVEBOX_PYTHON:-3.13}"' in script
    assert 'ARCHIVEBOX_PACKAGE="${ARCHIVEBOX_PACKAGE:-archivebox>=0.9.0rc0,<0.10}"' in script
    assert '"$UV_BINARY" tool install --python "$ARCHIVEBOX_PYTHON" --prerelease explicit --upgrade "$ARCHIVEBOX_PACKAGE"' in install_flow
    assert "https://astral.sh/uv/install.sh" in script
    assert "archivebox init" not in install_flow
    assert "archivebox install" not in install_flow


def test_setup_script_does_not_select_a_system_installer_or_runtime():
    script = SETUP_SCRIPT.read_text()

    assert "docker" not in script.lower()
    assert "debian-archivebox" not in script
    assert "apt-get" not in script
    assert "launchpad" not in script
    assert "archivebox server" not in script
    assert "useradd" not in script


def test_setup_script_has_valid_bash_syntax():
    result = subprocess.run(["bash", "-n", SETUP_SCRIPT], capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
