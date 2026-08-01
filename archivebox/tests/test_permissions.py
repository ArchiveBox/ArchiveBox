from archivebox.config.permissions import select_archivebox_user


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
