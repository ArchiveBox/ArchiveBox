from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

_REQUIRED_DOCKER_INSTALL_TARGETS = {
    "archivewebpage",
    "defuddle",
    "forumdl",
    "gallerydl",
    "git",
    "istilldontcareaboutcookies",
    "liteparse",
    "mercury",
    "opencode",
    "opendataloader",
    "papersdl",
    "parse_rss_urls",
    "readability",
    "search_backend_ripgrep",
    "search_backend_sonic",
}

_REQUIRED_DOCKER_PREINSTALL_TARGETS = {
    "archivewebpage",
    "defuddle",
    "forumdl",
    "gallerydl",
    "git",
    "istilldontcareaboutcookies",
    "liteparse",
    "mercury",
    "opendataloader",
    "papersdl",
    "parse_rss_urls",
    "readability",
    "search_backend_ripgrep",
    "search_backend_sonic",
    "ublock",
    "wget",
    "ytdlp",
}

_DOCKER_PREINSTALL_EXCLUDED_TARGETS = {
    "twocaptcha",
}


def _archivebox_install_commands(dockerfile: Path) -> list[str]:
    text = dockerfile.read_text()
    return re.findall(r"archivebox install ([^\\\n]+)", text)


def _bare_archivebox_install_commands(dockerfile: Path) -> list[str]:
    text = dockerfile.read_text()
    return re.findall(r"archivebox install(?:\s+2>&1|\s*\\)", text)


def _abx_dl_plugin_install_targets(dockerfile: Path) -> set[str]:
    text = dockerfile.read_text()
    commands = re.findall(r"abx-dl plugins --install((?: \\\n|[^\n])*)", text)
    targets: set[str] = set()
    for command in commands:
        command_text = command.replace("\\", " ")
        targets.update(re.findall(r"\b[a-z][a-z0-9_]*\b", command_text))
    return targets


def test_dockerfiles_install_binaries_required_by_version_validation() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        commands = _archivebox_install_commands(REPO_ROOT / dockerfile_name)
        target_command = max(commands, key=lambda command: len(command.split()))
        targets = set(target_command.split())
        assert _REQUIRED_DOCKER_INSTALL_TARGETS <= targets


def test_dockerfile_prewarms_stable_plugin_dependencies_without_optional_captcha() -> None:
    text = (REPO_ROOT / "Dockerfile").read_text()
    assert "archivebox/abx-dl:latest" in text
    assert "archivebox/abxdl" not in text
    assert _abx_dl_plugin_install_targets(REPO_ROOT / "Dockerfile") == set()


def test_dockerfile_build_installs_disable_release_age_gate() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert "ABXPKG_POSTINSTALL_SCRIPTS=True" in text
        assert "ABXPKG_MIN_RELEASE_AGE=0" in text


def test_dockerfiles_do_not_queue_optional_binaries_during_validation() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        assert _bare_archivebox_install_commands(REPO_ROOT / dockerfile_name) == []


def test_dockerfiles_clean_build_data_dir_before_init() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert 'find "$DATA_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +' in text


def test_dockerfiles_pin_project_binary_paths_for_validation() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert 'GIT_BINARY="$LIB_DIR/env/bin/git"' in text
        assert 'GALLERYDL_BINARY="$LIB_DIR/env/bin/gallery-dl"' in text
        assert 'FORUMDL_BINARY="$LIB_DIR/env/bin/forum-dl"' in text
        assert 'OPENCODE_BINARY="$LIB_DIR/env/bin/opencode"' in text


def test_dockerfiles_preinstall_opencode_without_pnpm_home_override() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert 'PATH="/venv/bin:/opt/node/bin:/opt/archivebox/lib/bin:$PATH"' in text
        assert "env -u PNPM_HOME" in text
        assert "/opt/node/bin/corepack pnpm add" in text
        assert '--store-dir="$TMP_DIR/pnpm-store"' in text
        assert '--dir="$LIB_DIR/pnpm/packages/opencode" opencode-ai' in text
        assert 'chown -R "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR/pnpm/packages/opencode"' in text
        assert 'rm -rf "$TMP_DIR/pnpm-store" /root/.cache/node' in text
        assert 'ln -sf "$LIB_DIR/pnpm/packages/opencode/node_modules/.bin/opencode" "$LIB_DIR/bin/opencode"' in text
        assert 'ln -sf "$LIB_DIR/pnpm/packages/opencode/node_modules/.bin/opencode" "$LIB_DIR/env/bin/opencode"' in text
        assert 'chown "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR"' in text
        assert 'chown -h "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR/bin/opencode" "$LIB_DIR/env/bin/opencode"' in text


def test_dockerfiles_use_setpriv_instead_of_gosu() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert "gosu" not in text
        assert "setpriv" in text

    entrypoint = (REPO_ROOT / "bin/docker_entrypoint.sh").read_text()
    assert "gosu" not in entrypoint
    assert "setpriv" in entrypoint


def test_dockerfiles_create_archivebox_venv_in_archivebox_builder() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert "COPY --from=abx-dl /venv /venv" not in text
        assert 'uv venv /venv --python "${PYTHON_VERSION}"' in text
        assert "COPY --from=archivebox-builder /opt/uv/python /opt/uv/python" in text
        assert 'COMMIT_HASH="$(' in text
        assert 'HEAD_REF="$(cat "$CODE_DIR/.git/HEAD")"' in text
        assert 'echo "COMMIT_HASH=$COMMIT_HASH" | tee -a /VERSION.txt' in text
        assert 'rm -rf "$CODE_DIR/.git"' in text


def test_dockerfiles_do_not_duplicate_runtime_lib_with_recursive_chown() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert 'chown -R "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR"' not in text
        assert 'chown -R "$DEFAULT_PUID:$DEFAULT_PGID" "$DATA_DIR" "$TMP_DIR" "$LIB_DIR"' not in text
        assert 'chown "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR" "$PLAYWRIGHT_BROWSERS_PATH"' in text
        assert "COPY --from=abx-dl --chown=911:911 /opt/archivebox/lib /opt/archivebox/lib" in text


def test_dockerfiles_validate_current_papers_dl_path() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert '"$LIB_DIR/uv/packages/papers-dl/venv/bin/papers-dl" --version' in text
        assert "$LIB_DIR/pip/packages/papers-dl" not in text


def test_dockerfiles_do_not_default_multiarch_builds_to_amd64() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert "ARG TARGETPLATFORM=linux/amd64" not in text
        assert "ARG TARGETARCH=amd64" not in text
        assert "ARG TARGETPLATFORM\n" in text
        assert "FROM ${ABX_DL_IMAGE} AS abx-dl" in text


def test_dockerfiles_set_archivebox_home_for_setpriv_commands() -> None:
    for dockerfile_name in ("Dockerfile", "Dockerfile.multistage"):
        text = (REPO_ROOT / dockerfile_name).read_text()
        assert (
            'install -d -o "$DEFAULT_PUID" -g "$DEFAULT_PGID" "/home/$ARCHIVEBOX_USER/.config/abx" "/home/$ARCHIVEBOX_USER/.cache/abxbus"'
        ) in text
        assert 'HOME="/home/$ARCHIVEBOX_USER" XDG_CONFIG_HOME="/home/$ARCHIVEBOX_USER/.config"' in text


def test_dockerignore_keeps_minimal_git_metadata_for_image_version() -> None:
    text = (REPO_ROOT / ".dockerignore").read_text()
    assert ".git/" in text
    assert "!.git/" in text
    assert ".git/*" in text
    assert "!.git/HEAD" in text
    assert "!.git/packed-refs" in text
    assert "!.git/refs/" in text
    assert "!.git/refs/heads/" in text
    assert "!.git/refs/heads/**" in text
