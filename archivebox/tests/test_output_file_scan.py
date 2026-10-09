"""Output discovery preserves real files without repeating filesystem metadata reads."""

import cProfile
import pstats
import shutil
from pathlib import Path


def test_output_scan_reuses_directory_entry_metadata(tmp_path):
    from archivebox.core.models import ArchiveResult

    source = Path(__file__)
    root = tmp_path / "snapshot"
    expected = {}
    for directory_index in range(16):
        directory = root / f"plugin{directory_index}" / "assets"
        directory.mkdir(parents=True)
        for file_index in range(16):
            destination = directory / f"saved-{file_index}.txt"
            shutil.copyfile(source, destination)
            expected[str(destination.relative_to(root))] = {"size": source.stat().st_size}

    profile = cProfile.Profile()
    actual = profile.runcall(ArchiveResult._scan_output_file_map, root)
    assert actual == expected
    # WHY: lstat for is_symlink followed by stat doubled remote/FUSE metadata
    # work. Count explicit native stat/lstat calls, not noisy elapsed-time limits.
    metadata_calls = {
        function: values[1]
        for (filename, _line, function), values in pstats.Stats(profile).stats.items()
        if filename == "~" and (function.endswith(".stat>") or function.endswith(".lstat>") or "'stat' of" in function)
    }
    assert sum(metadata_calls.values()) <= len(expected), metadata_calls


def test_output_scan_preserves_hidden_symlink_and_limit_rules(tmp_path):
    from archivebox.core.models import ArchiveResult

    root = tmp_path / "snapshot"
    (root / "nested").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / ".hidden" / "secret.txt").write_bytes(b"hidden directory")
    (root / ".hidden.txt").write_bytes(b"hidden file")
    (root / "nested" / "saved.txt").write_bytes(b"captured content")
    (root / "linked.txt").symlink_to(root / "nested" / "saved.txt")
    (root / "linked-directory").symlink_to(root / "nested", target_is_directory=True)
    (root / "dangling.txt").symlink_to(root / "absent.txt")
    assert ArchiveResult._scan_output_file_map(root) == {"nested/saved.txt": {"size": 16}}
    (root / "nested" / "saved.txt").write_bytes(b"new capture replaces the old output")
    assert ArchiveResult._scan_output_file_map(root) == {"nested/saved.txt": {"size": 35}}
    assert ArchiveResult._scan_output_file_map(tmp_path / "not-created") == {}

    limited = tmp_path / "limited"
    limited.mkdir()
    for index in range(12):
        (limited / f"{index}.txt").write_bytes(b"saved")
    assert ArchiveResult._scan_output_file_map(limited, max_scan=0) == {}
    files = ArchiveResult._scan_output_file_map(limited, max_scan=7)
    assert len(files) == 7
    assert all(metadata == {"size": 5} and (limited / path).read_bytes() == b"saved" for path, metadata in files.items())


def test_output_scan_does_not_require_access_to_excluded_symlink_target(tmp_path):
    from archivebox.core.models import ArchiveResult

    root = tmp_path / "snapshot"
    root.mkdir()
    private = tmp_path / "private"
    private.mkdir()
    (private / "directory").mkdir()
    (root / "excluded").symlink_to(private / "directory", target_is_directory=True)
    private.chmod(0)
    try:
        assert ArchiveResult._scan_output_file_map(root) == {}
    finally:
        private.chmod(0o700)


def test_unbounded_output_scan_never_classifies_excluded_targets(tmp_path):
    from archivebox.core.models import ArchiveResult

    root = tmp_path / "snapshot"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "saved.txt").write_bytes(b"captured")
    for index in range(64):
        (root / f"alias-{index}.txt").symlink_to(outside / "saved.txt")
        (root / f"directory-{index}").symlink_to(outside, target_is_directory=True)
        (root / f".hidden-{index}").write_bytes(b"not a preview")
    (root / "saved.txt").write_bytes(b"visible output")
    profile = cProfile.Profile()
    assert profile.runcall(ArchiveResult._scan_output_file_map, root) == {"saved.txt": {"size": 14}}
    classifications = sum(
        values[1]
        for (filename, _line, function), values in pstats.Stats(profile).stats.items()
        if filename == "~" and "'is_dir' of" in function
    )
    # WHY: is_dir follows alias targets even though none may become previews.
    # On FUSE this adds remote metadata work for every excluded response alias.
    assert classifications == 1, classifications
