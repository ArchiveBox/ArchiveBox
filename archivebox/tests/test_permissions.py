from pathlib import Path

from archivebox.config.permissions import (
    is_root_identity,
    root_parent_can_grant_group_traversal,
    root_should_handoff_data_dir,
    select_archivebox_user,
)


def test_root_identity_includes_real_or_effective_root():
    assert is_root_identity(0, 0)
    assert is_root_identity(0, 911)
    assert is_root_identity(1000, 0)
    assert not is_root_identity(1000, 1000)


def test_root_uses_archivebox_account_for_root_owned_data_dir():
    assert select_archivebox_user(
        running_uid=0,
        running_gid=0,
        effective_uid=0,
        effective_gid=0,
        sudo_uid=0,
        sudo_gid=0,
        data_dir_uid=0,
        data_dir_gid=0,
        account_uid=911,
        account_gid=911,
    ) == (911, 911)


def test_root_preserves_existing_non_root_data_dir_owner():
    assert select_archivebox_user(
        running_uid=0,
        running_gid=0,
        effective_uid=0,
        effective_gid=0,
        sudo_uid=0,
        sudo_gid=0,
        data_dir_uid=1001,
        data_dir_gid=1002,
        account_uid=911,
        account_gid=911,
    ) == (1001, 1002)


def test_root_uses_owner_primary_group_for_mixed_user_root_data_dir():
    assert select_archivebox_user(
        running_uid=0,
        running_gid=0,
        effective_uid=0,
        effective_gid=0,
        sudo_uid=1001,
        sudo_gid=1002,
        data_dir_uid=1001,
        data_dir_gid=0,
        data_dir_owner_gid=1002,
        account_uid=911,
        account_gid=911,
    ) == (1001, 1002)


def test_root_uses_archivebox_account_for_unknown_data_dir_owner():
    assert select_archivebox_user(
        running_uid=0,
        running_gid=0,
        effective_uid=0,
        effective_gid=0,
        sudo_uid=0,
        sudo_gid=0,
        data_dir_uid=502,
        data_dir_gid=20,
        account_uid=911,
        account_gid=911,
        data_dir_owner_exists=False,
    ) == (911, 911)


def test_non_root_uses_current_effective_identity():
    assert select_archivebox_user(
        running_uid=501,
        running_gid=20,
        effective_uid=501,
        effective_gid=20,
        sudo_uid=0,
        sudo_gid=0,
        data_dir_uid=0,
        data_dir_gid=0,
        account_uid=None,
        account_gid=None,
    ) == (501, 20)


def test_effective_root_drops_back_to_real_user():
    assert select_archivebox_user(
        running_uid=1001,
        running_gid=1002,
        effective_uid=0,
        effective_gid=0,
        sudo_uid=0,
        sudo_gid=0,
        data_dir_uid=0,
        data_dir_gid=0,
        account_uid=None,
        account_gid=None,
    ) == (1001, 1002)


def test_root_hands_off_root_or_archivebox_owned_collection_boundaries():
    assert root_should_handoff_data_dir(is_root=True, data_dir_uid=0, account_uid=911)
    assert root_should_handoff_data_dir(is_root=True, data_dir_uid=911, account_uid=911)
    assert not root_should_handoff_data_dir(is_root=True, data_dir_uid=1001, account_uid=911)
    assert not root_should_handoff_data_dir(is_root=False, data_dir_uid=911, account_uid=911)
    assert not root_should_handoff_data_dir(is_root=True, data_dir_uid=911, account_uid=None)
    assert root_should_handoff_data_dir(
        is_root=True,
        data_dir_uid=502,
        account_uid=911,
        data_dir_owner_exists=False,
    )


def test_root_setup_commands_hand_off_only_an_empty_data_dir(tmp_path):
    from archivebox.config.permissions import root_data_dir_handoff_paths

    setup_commands = (
        ["archivebox", "init"],
        ["archivebox", "install"],
        ["archivebox", "server", "--init"],
        ["archivebox", "server", "--quick-init"],
        ["archivebox", "add", "--init", "https://example.com"],
    )
    for argv in setup_commands:
        assert root_data_dir_handoff_paths(tmp_path, argv) == (tmp_path,)

    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("keep root ownership")
    for argv in setup_commands:
        assert root_data_dir_handoff_paths(tmp_path, argv) == ()


def test_existing_collection_handoff_is_bounded_to_known_top_level_paths(tmp_path):
    from archivebox.config.permissions import root_data_dir_handoff_paths

    database = tmp_path / "index.sqlite3"
    archive = tmp_path / "archive"
    custom_plugins = tmp_path / "custom_plugins"
    custom_templates = tmp_path / "custom_templates"
    nested = archive / "large-existing-snapshot"
    errors_log = tmp_path / "logs" / "errors.log"
    database.touch()
    nested.mkdir(parents=True)
    custom_plugins.mkdir()
    custom_templates.mkdir()
    errors_log.parent.mkdir()
    errors_log.touch()

    paths = root_data_dir_handoff_paths(tmp_path, ["archivebox", "status"])

    assert paths == (tmp_path, database, archive, custom_plugins, custom_templates, errors_log.parent, errors_log)
    assert nested not in paths
    assert all(path == tmp_path or path.parent in (tmp_path, errors_log.parent) for path in paths)


def test_permission_repairs_avoid_recursive_collection_and_abxpkg_chown():
    from archivebox.misc import checks

    assert "chown -R" not in Path(checks.__file__).read_text(encoding="utf-8")
    entrypoint = (Path(__file__).parents[2] / "bin" / "docker_entrypoint.sh").read_text(encoding="utf-8")
    permission_error = entrypoint.partition("permission_error() {")[2].partition("\n}")[0]
    abxpkg_repairs = entrypoint.partition('ensure_dir "$ABXPKG_LIB_DIR"')[2].partition("run_as_archivebox touch")[0]

    assert 'for package_dir in "$provider_dir"/packages/*; do' in abxpkg_repairs
    assert 'ensure_file_owner "$package_dir/derived.env"' in abxpkg_repairs
    assert "chown -R" not in permission_error
    assert "chown -R" not in abxpkg_repairs


def test_docker_entrypoint_uses_non_root_functional_checks_before_metadata_repairs():
    entrypoint = (Path(__file__).parents[2] / "bin" / "docker_entrypoint.sh").read_text(encoding="utf-8")
    ensure_dir = entrypoint.partition("ensure_dir() {")[2].partition("\n}")[0]
    writable_probe = entrypoint.partition("assert_writable_dir() {")[2].partition("\n}")[0]

    assert 'run_as_archivebox mkdir -p "$path"' in ensure_dir
    assert 'path_is_writable "$path" && return 0' in ensure_dir
    assert ensure_dir.index('path_is_writable "$path" && return 0') < ensure_dir.index('chown_if_needed "$path"')
    assert ensure_dir.index('path_is_writable "$path" && return 0') < ensure_dir.index('chmod_if_possible "$path"')
    assert 'run_as_archivebox test -w "$path"' in entrypoint
    assert 'run_as_archivebox test -x "$path"' in entrypoint
    assert 'run_as_archivebox mktemp "$path/.permissions_test.XXXXXX"' in writable_probe
    assert 'run_as_archivebox rm -f "$probe"' in writable_probe
    assert "du -s" not in entrypoint
    assert "du -sb" not in entrypoint
    assert 'find "$DATA_DIR"' not in entrypoint
    assert 'find "$PERSONAS_DIR"' not in entrypoint
    for line in entrypoint.splitlines():
        assert not ("chown -R" in line and ("$DATA_DIR" in line or "$DATA_DIR/archive" in line))
        assert not ("chmod -R" in line and ("$DATA_DIR" in line or "$DATA_DIR/archive" in line))


def test_docker_entrypoint_keeps_root_pgid_and_validates_it_in_real_docker():
    entrypoint = (Path(__file__).parents[2] / "bin" / "docker_entrypoint.sh").read_text(encoding="utf-8")
    docker_validator = (Path(__file__).parents[2] / "bin" / "validate_docker_uid_gid.sh").read_text(encoding="utf-8")

    assert 'TARGET_UID="${PUID:-$DETECTED_UID}"' in entrypoint
    assert 'TARGET_GID="${PGID:-$DETECTED_GID}"' in entrypoint
    assert '[[ "$TARGET_UID" == "0" ]]' in entrypoint
    assert '[[ "$TARGET_GID" == "0" ]]' not in entrypoint.partition('[[ "$TARGET_UID" == "0" ]]')[2].partition("fi")[0]
    assert 'run_case "explicit non-root PUID with PGID zero is supported"' in docker_validator
    assert '"PUID=1201 PGID=0" "-" pass 1201 0' in docker_validator


def test_root_handoff_never_selects_filesystem_root():
    from archivebox.config.permissions import root_data_dir_handoff_paths

    assert root_data_dir_handoff_paths(Path("/"), ["archivebox", "init"]) == ()


def test_root_private_parent_grants_only_archivebox_group_traversal():
    assert root_parent_can_grant_group_traversal(parent_uid=0, parent_gid=0, parent_mode=0o700, account_gid=911)
    assert not root_parent_can_grant_group_traversal(parent_uid=0, parent_gid=0, parent_mode=0o701, account_gid=911)
    assert not root_parent_can_grant_group_traversal(parent_uid=0, parent_gid=911, parent_mode=0o710, account_gid=911)
    assert not root_parent_can_grant_group_traversal(parent_uid=0, parent_gid=100, parent_mode=0o750, account_gid=911)
    assert not root_parent_can_grant_group_traversal(parent_uid=1000, parent_gid=1000, parent_mode=0o700, account_gid=911)
