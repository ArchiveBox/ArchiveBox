import os
from pathlib import Path

import pytest

from archivebox.tests import conftest as test_harness


def test_session_data_dir_is_outside_repo_root():
    assert test_harness.SESSION_DATA_DIR != test_harness.REPO_ROOT
    assert test_harness.REPO_ROOT not in test_harness.SESSION_DATA_DIR.parents
    assert Path.cwd() != test_harness.REPO_ROOT
    if test_harness.REPO_ROOT in Path.cwd().parents:
        assert test_harness.PYTEST_BASETEMP_ROOT in (Path.cwd(), *Path.cwd().parents)


def test_in_process_archivebox_config_uses_temp_data_dir():
    from archivebox.config import CONSTANTS
    from archivebox.config.common import get_config

    data_dir = CONSTANTS.DATA_DIR.resolve()
    assert data_dir == Path.cwd().resolve()
    assert test_harness.REPO_ROOT not in data_dir.parents
    assert CONSTANTS.DATA_DIR != test_harness.REPO_ROOT

    config = get_config(include_machine=False)
    assert config.DATA_DIR in ("", str(data_dir))
    assert "ARCHIVE_DIR" not in config
    assert "USERS_DIR" not in config
    assert CONSTANTS.ARCHIVE_DIR == data_dir / "archive"
    assert CONSTANTS.USERS_DIR == data_dir / "archive" / "users"


def test_cli_helpers_reject_repo_root_runtime_paths():
    with pytest.raises(AssertionError, match="repo root"):
        test_harness.run_archivebox_cmd(["version"], cwd=test_harness.REPO_ROOT)

    with pytest.raises(AssertionError, match="repo root"):
        test_harness.run_python_cwd("print('hello')", cwd=test_harness.REPO_ROOT)


def test_runtime_guard_rejects_chdir_into_repo_root():
    with pytest.raises(AssertionError, match="repo root"):
        os.chdir(test_harness.REPO_ROOT)
