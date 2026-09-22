import subprocess
from pathlib import Path


SETUP_SCRIPT = Path(__file__).parents[2] / "bin" / "setup.sh"


def test_setup_script_initializes_then_links_container_dependencies():
    script = SETUP_SCRIPT.read_text()
    compose_flow = script.partition('if [ "$DOCKER_IMAGE_READY" = "true" ] && "$DOCKER_BINARY" compose version')[2].partition(
        'elif [ "$DOCKER_IMAGE_READY" = "true" ]',
    )[0]
    docker_flow = script.partition('elif [ "$DOCKER_IMAGE_READY" = "true" ]')[2].partition("\nfi")[0]
    docker_init = script.partition("docker_run_archivebox_init() {")[2].partition("\n}")[0]

    # Docker images already contain every runtime dependency. Initialization
    # must only create collection state; the following install command merely
    # projects the preloaded image cache into that collection.
    assert "docker_run_archivebox init" in docker_init
    assert "--install" not in docker_init
    assert compose_flow.index("docker_compose_run_archivebox init") < compose_flow.index("docker_compose_run_archivebox install")
    assert docker_flow.index("docker_run_archivebox_init") < docker_flow.index("docker_run_archivebox_install")
    assert "init --install" not in script


def test_setup_script_keeps_uv_as_the_native_fallback():
    script = SETUP_SCRIPT.read_text()
    native_flow = script.partition("install_archivebox_with_uv\n")[2]

    assert 'ARCHIVEBOX_PYTHON="${ARCHIVEBOX_PYTHON:-3.13}"' in script
    assert 'ARCHIVEBOX_PACKAGE="${ARCHIVEBOX_PACKAGE:-archivebox>=0.9.0rc0,<0.10}"' in script
    assert (
        'run_as_archivebox_user "$UV_BINARY" --no-config tool install --python "$ARCHIVEBOX_PYTHON" '
        '--prerelease explicit --upgrade "$ARCHIVEBOX_PACKAGE"'
    ) in script
    assert "https://astral.sh/uv/install.sh" in script
    assert ': | "$ARCHIVEBOX_BINARY" init' in native_flow
    assert native_flow.index(': | "$ARCHIVEBOX_BINARY" init') < native_flow.index('"$ARCHIVEBOX_BINARY" install')


def test_setup_script_has_valid_bash_syntax():
    result = subprocess.run(["bash", "-n", SETUP_SCRIPT], capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
