from pathlib import Path

import pytest

from archivebox.workers import supervisord_util


@pytest.mark.parametrize(
    ("stat", "expected"),
    [
        ("active_file 216002560\ninactive_file 1555210240\n", 1962287104),
        ("active_file 216002560\ninactive_file 1555210240\nfile_dirty 104857600\nfile_writeback 52428800\n", 1805000704),
        ("active_file 0\ninactive_file 0\n", 191074304),
        ("active_file 10\nfile_dirty 20\n", 191074304),
        ("active_file 9999999999\n", 2147483648),
        ("active_file invalid\n", 191074304),
        ("malformed line with extra fields\n", 191074304),
        (None, 191074304),
    ],
)
def test_startup_cgroup_clean_cache_credit(tmp_path: Path, stat: str | None, expected: int):
    for name, value in {"memory.max": 2147483648, "memory.current": 1956409344, "memory.swap.max": 0, "memory.swap.current": 0}.items():
        (tmp_path / name).write_text(str(value))
    if stat is not None:
        (tmp_path / "memory.stat").write_text(stat)
    assert supervisord_util._cgroup_available_memory_bytes(tmp_path) == expected


def test_startup_cgroup_swap_and_unknown_limits(tmp_path: Path):
    assert supervisord_util._cgroup_available_memory_bytes(tmp_path) is None
    (tmp_path / "memory.max").write_text("max")
    (tmp_path / "memory.current").write_text("100")
    assert supervisord_util._cgroup_available_memory_bytes(tmp_path) is None
    (tmp_path / "memory.max").write_text("1000")
    (tmp_path / "memory.swap.max").write_text("500")
    (tmp_path / "memory.swap.current").write_text("200")
    assert supervisord_util._cgroup_available_memory_bytes(tmp_path) == 1200
    (tmp_path / "memory.swap.max").write_text("max")
    assert supervisord_util._cgroup_available_memory_bytes(tmp_path) == 900
