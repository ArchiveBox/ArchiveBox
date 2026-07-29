__package__ = "archivebox.config"

import os
import importlib.metadata

from pathlib import Path
from functools import cache
from datetime import datetime
import re

#############################################################################################

IN_DOCKER = os.environ.get("IN_DOCKER", False) in ("1", "true", "True", "TRUE", "yes")

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent  # archivebox source code dir

#############################################################################################


@cache
def detect_installed_version(PACKAGE_DIR: Path = PACKAGE_DIR):
    """Autodetect the installed archivebox version by using pip package metadata, pyproject.toml file, or package.json file"""
    try:
        # if in production install, use pip-installed package metadata
        return importlib.metadata.version("archivebox").strip()
    except importlib.metadata.PackageNotFoundError:
        pass

    try:
        # if in dev Git repo dir, use pyproject.toml file
        pyproject_config = (PACKAGE_DIR.parent / "pyproject.toml").read_text().split("\n")
        for line in pyproject_config:
            if line.startswith("version = "):
                return line.split(" = ", 1)[-1].strip('"').strip()
    except FileNotFoundError:
        # building docs, pyproject.toml is not available
        pass

    return "dev"


@cache
def get_COMMIT_HASH() -> str | None:
    for env_var in ("ARCHIVEBOX_COMMIT_HASH",):
        env_commit_hash = os.environ.get(env_var, "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", env_commit_hash):
            return env_commit_hash

    if IN_DOCKER:
        try:
            version_text = Path("/VERSION.txt").read_text()
            matches = re.findall(r"^COMMIT_HASH=([0-9a-fA-F]{40})$", version_text, re.MULTILINE)
            if matches:
                return matches[-1]
        except Exception:
            pass

    try:
        packaged_commit_hash = (PACKAGE_DIR / "COMMIT_SHA").read_text().strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", packaged_commit_hash):
            return packaged_commit_hash
    except Exception:
        pass

    def _read_git_file(git_dir: Path, ref: str) -> str | None:
        try:
            return git_dir.joinpath(ref).read_text().strip()
        except Exception:
            pass

        try:
            packed_refs = git_dir.joinpath("packed-refs").read_text().splitlines()
        except Exception:
            return None

        for line in packed_refs:
            if line.startswith("#") or line.startswith("^") or not line.strip():
                continue
            commit_hash, packed_ref = line.split(" ", 1)
            if packed_ref == ref:
                return commit_hash.strip()

        return None

    try:
        try:
            pyproject_text = (PACKAGE_DIR.parent / "pyproject.toml").read_text()
        except FileNotFoundError:
            pyproject_text = ""
        if not re.search(r'^name = "archivebox"$', pyproject_text, re.MULTILINE):
            return None

        git_dir = PACKAGE_DIR.parent / ".git"
        if git_dir.is_file():
            gitdir_line = git_dir.read_text().strip()
            gitdir_path = gitdir_line.removeprefix("gitdir:").strip()
            git_dir = Path(gitdir_path)
            if not git_dir.is_absolute():
                git_dir = PACKAGE_DIR.parent / git_dir

        head = (git_dir / "HEAD").read_text().strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", head):
            return head

        ref = head.removeprefix("ref:").strip()
        commit_hash = _read_git_file(git_dir, ref)
        if commit_hash:
            return commit_hash
    except Exception:
        pass

    return None


@cache
def get_BUILD_TIME() -> str:
    for env_var in ("ARCHIVEBOX_BUILD_TIME", "BUILD_TIME"):
        build_time = os.environ.get(env_var, "").strip()
        if build_time:
            return build_time

    src_last_modified_unix_timestamp = (PACKAGE_DIR / "README.md").stat().st_mtime
    return datetime.fromtimestamp(src_last_modified_unix_timestamp).strftime("%Y-%m-%d %H:%M:%S %s")


VERSION: str = detect_installed_version()
