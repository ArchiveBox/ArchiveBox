from pathlib import Path

from archivebox.config import version


def _set_package_dir(monkeypatch, package_dir: Path) -> None:
    monkeypatch.setattr(version, "PACKAGE_DIR", package_dir)
    version.get_COMMIT_HASH.cache_clear()


def test_get_commit_hash_from_environment(monkeypatch) -> None:
    commit_hash = "e" * 40
    monkeypatch.setenv("ARCHIVEBOX_COMMIT_HASH", commit_hash)
    version.get_COMMIT_HASH.cache_clear()

    assert version.get_COMMIT_HASH() == commit_hash


def test_get_commit_hash_from_docker_version_file_ignores_short_hash(monkeypatch) -> None:
    commit_hash = "f" * 40

    class VersionPath:
        def __init__(self, path: str):
            self.path = path

        def read_text(self) -> str:
            assert self.path == "/VERSION.txt"
            return f"COMMIT_HASH={commit_hash}\nArchiveBox COMMIT_HASH={commit_hash[:7]}\n"

    monkeypatch.setattr(version, "IN_DOCKER", True)
    monkeypatch.setattr(version, "Path", VersionPath)
    version.get_COMMIT_HASH.cache_clear()

    assert version.get_COMMIT_HASH() == commit_hash


def test_get_commit_hash_from_detached_head(monkeypatch, tmp_path) -> None:
    commit_hash = "a" * 40
    package_dir = tmp_path / "archivebox"
    git_dir = tmp_path / ".git"
    package_dir.mkdir()
    git_dir.mkdir()
    git_dir.joinpath("HEAD").write_text(commit_hash)

    _set_package_dir(monkeypatch, package_dir)

    assert version.get_COMMIT_HASH() == commit_hash


def test_get_commit_hash_from_branch_ref(monkeypatch, tmp_path) -> None:
    commit_hash = "b" * 40
    package_dir = tmp_path / "archivebox"
    git_dir = tmp_path / ".git"
    ref_path = git_dir / "refs" / "heads" / "dev"
    package_dir.mkdir()
    ref_path.parent.mkdir(parents=True)
    git_dir.joinpath("HEAD").write_text("ref: refs/heads/dev")
    ref_path.write_text(commit_hash)

    _set_package_dir(monkeypatch, package_dir)

    assert version.get_COMMIT_HASH() == commit_hash


def test_get_commit_hash_from_packed_ref(monkeypatch, tmp_path) -> None:
    commit_hash = "c" * 40
    package_dir = tmp_path / "archivebox"
    git_dir = tmp_path / ".git"
    package_dir.mkdir()
    git_dir.mkdir()
    git_dir.joinpath("HEAD").write_text("ref: refs/heads/dev")
    git_dir.joinpath("packed-refs").write_text(f"{commit_hash} refs/heads/dev\n")

    _set_package_dir(monkeypatch, package_dir)

    assert version.get_COMMIT_HASH() == commit_hash


def test_get_commit_hash_from_worktree_gitdir(monkeypatch, tmp_path) -> None:
    commit_hash = "d" * 40
    package_dir = tmp_path / "worktree" / "archivebox"
    real_git_dir = tmp_path / "repo" / ".git" / "worktrees" / "worktree"
    package_dir.mkdir(parents=True)
    real_git_dir.mkdir(parents=True)
    package_dir.parent.joinpath(".git").write_text(f"gitdir: {real_git_dir}\n")
    real_git_dir.joinpath("HEAD").write_text(commit_hash)

    _set_package_dir(monkeypatch, package_dir)

    assert version.get_COMMIT_HASH() == commit_hash
