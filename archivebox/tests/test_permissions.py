from pathlib import Path

from archivebox.config.permissions import is_root_identity, root_should_handoff_data_dir, select_archivebox_user


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


def test_root_init_hands_off_only_an_empty_data_dir(tmp_path):
    from archivebox.config.permissions import root_data_dir_handoff_paths

    assert root_data_dir_handoff_paths(tmp_path, ["archivebox", "init"]) == (tmp_path,)

    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("keep root ownership")
    assert root_data_dir_handoff_paths(tmp_path, ["archivebox", "init"]) == ()


def test_existing_collection_handoff_is_bounded_to_known_top_level_paths(tmp_path):
    from archivebox.config.permissions import root_data_dir_handoff_paths

    database = tmp_path / "index.sqlite3"
    archive = tmp_path / "archive"
    nested = archive / "large-existing-snapshot"
    errors_log = tmp_path / "logs" / "errors.log"
    database.touch()
    nested.mkdir(parents=True)
    errors_log.parent.mkdir()
    errors_log.touch()

    paths = root_data_dir_handoff_paths(tmp_path, ["archivebox", "status"])

    assert paths == (tmp_path, database, archive, errors_log.parent, errors_log)
    assert nested not in paths
    assert all(path == tmp_path or path.parent in (tmp_path, errors_log.parent) for path in paths)


def test_permission_repair_hint_avoids_recursive_collection_chown():
    from archivebox.misc import checks

    assert "chown -R" not in Path(checks.__file__).read_text(encoding="utf-8")


def test_root_handoff_never_selects_filesystem_root():
    from archivebox.config.permissions import root_data_dir_handoff_paths

    assert root_data_dir_handoff_paths(Path("/"), ["archivebox", "init"]) == ()
