import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from archivebox.config import version


def _resolve_git_with_abxpkg(tmp_path: Path) -> Path:
    lib_dir = tmp_path / "abxpkg-lib"
    abxpkg = Path(sys.executable).with_name("abxpkg")
    result = subprocess.run(
        [str(abxpkg), "env", "--json", "--lib", str(lib_dir), "git"],
        check=True,
        capture_output=True,
        text=True,
    )
    json.loads(result.stdout)
    git = lib_dir / "env" / "bin" / "git"
    assert git.is_symlink()
    assert git.resolve().is_file()
    return git


def _git(git: Path, repo: Path, *args: str) -> str:
    result = subprocess.run(
        [str(git), "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_git_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    git = _resolve_git_with_abxpkg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(git, repo, "init", "--initial-branch=dev")
    _git(git, repo, "config", "user.name", "ArchiveBox Tests")
    _git(git, repo, "config", "user.email", "tests@archivebox.io")
    copied_version = repo / "archivebox" / "config" / "version.py"
    copied_version.parent.mkdir(parents=True)
    shutil.copyfile(version.__file__, copied_version)
    _git(git, repo, "add", "archivebox/config/version.py")
    _git(git, repo, "commit", "-m", "add ArchiveBox version module")
    return git, repo, _git(git, repo, "rev-parse", "HEAD")


def _commit_hash_from_copied_version(package_dir: Path) -> str:
    script = """
import importlib.util
import sys

path = sys.argv[1]
spec = importlib.util.spec_from_file_location("archivebox_test_version", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.get_COMMIT_HASH() or "")
"""
    version_path = package_dir / "config" / "version.py"
    result = subprocess.run(
        [sys.executable, "-c", script, str(version_path)],
        check=True,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key not in {"ARCHIVEBOX_COMMIT_HASH", "COMMIT_HASH"}},
    )
    return result.stdout.strip()


def test_get_commit_hash_from_environment() -> None:
    commit_hash = "e" * 40
    env = os.environ.copy()
    env["ARCHIVEBOX_COMMIT_HASH"] = commit_hash
    env.pop("COMMIT_HASH", None)
    result = subprocess.run(
        [sys.executable, "-c", "from archivebox.config.version import get_COMMIT_HASH; print(get_COMMIT_HASH() or '')"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.stdout.strip() == commit_hash


def test_get_commit_hash_from_detached_head(tmp_path) -> None:
    git, repo, commit_hash = _create_git_repo(tmp_path)
    _git(git, repo, "checkout", "--detach", commit_hash)

    assert _commit_hash_from_copied_version(repo / "archivebox") == commit_hash


def test_get_commit_hash_from_branch_ref(tmp_path) -> None:
    _git_binary, repo, commit_hash = _create_git_repo(tmp_path)

    assert _commit_hash_from_copied_version(repo / "archivebox") == commit_hash


def test_get_commit_hash_from_packed_ref(tmp_path) -> None:
    git, repo, commit_hash = _create_git_repo(tmp_path)
    _git(git, repo, "pack-refs", "--all")
    assert not (repo / ".git" / "refs" / "heads" / "dev").exists()

    assert _commit_hash_from_copied_version(repo / "archivebox") == commit_hash


def test_get_commit_hash_from_worktree_gitdir(tmp_path) -> None:
    git, repo, commit_hash = _create_git_repo(tmp_path)
    worktree = tmp_path / "worktree"
    _git(git, repo, "worktree", "add", "--detach", str(worktree), commit_hash)
    assert (worktree / ".git").is_file()

    assert _commit_hash_from_copied_version(worktree / "archivebox") == commit_hash
