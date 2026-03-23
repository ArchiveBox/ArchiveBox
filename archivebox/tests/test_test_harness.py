import os
from pathlib import Path

import pytest

from archivebox.tests import conftest as test_harness


def test_session_data_dir_is_outside_repo_root():
    assert test_harness.SESSION_DATA_DIR != test_harness.REPO_ROOT
    assert test_harness.REPO_ROOT not in test_harness.SESSION_DATA_DIR.parents
    assert test_harness.REPO_ROOT not in Path.cwd().parents
    assert Path.cwd() != test_harness.REPO_ROOT


def test_cli_helpers_reject_repo_root_runtime_paths():
    with pytest.raises(AssertionError, match="repo root"):
        test_harness.run_archivebox_cmd(["version"], data_dir=test_harness.REPO_ROOT)

    with pytest.raises(AssertionError, match="repo root"):
        test_harness.run_archivebox_cmd_cwd(["version"], cwd=test_harness.REPO_ROOT)

    with pytest.raises(AssertionError, match="repo root"):
        test_harness.run_python_cwd("print('hello')", cwd=test_harness.REPO_ROOT)


def test_runtime_guard_rejects_chdir_into_repo_root():
    with pytest.raises(AssertionError, match="repo root"):
        os.chdir(test_harness.REPO_ROOT)
