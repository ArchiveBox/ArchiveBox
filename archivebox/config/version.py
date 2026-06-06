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

    # raise Exception('Failed to detect installed archivebox version!')
    return "dev"


@cache
def get_COMMIT_HASH() -> str | None:
    for env_var in ("ARCHIVEBOX_COMMIT_HASH", "COMMIT_HASH"):
        env_commit_hash = os.environ.get(env_var, "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", env_commit_hash):
            return env_commit_hash

    if IN_DOCKER:
        try:
            version_txt = Path("/VERSION.txt").read_text()
            docker_commit_hashes = re.findall(r"COMMIT_HASH=([0-9a-fA-F]{40})", version_txt)
            if docker_commit_hashes:
                return docker_commit_hashes[-1]
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

    try:
        return list((PACKAGE_DIR.parent / ".git/refs/heads/").glob("*"))[0].read_text().strip()
    except Exception:
        pass

    return None


@cache
def get_BUILD_TIME() -> str:
    if IN_DOCKER:
        try:
            # if we're in the archivebox official docker image, /VERSION.txt will contain the build time
            docker_build_end_time = Path("/VERSION.txt").read_text().rsplit("BUILD_END_TIME=")[-1].split("\n", 1)[0]
            return docker_build_end_time
        except Exception:
            pass

    src_last_modified_unix_timestamp = (PACKAGE_DIR / "README.md").stat().st_mtime
    return datetime.fromtimestamp(src_last_modified_unix_timestamp).strftime("%Y-%m-%d %H:%M:%S %s")


# def get_versions_available_on_github(config):
#     """
#     returns a dictionary containing the ArchiveBox GitHub release info for
#     the recommended upgrade version and the currently installed version
#     """

#     # we only want to perform the (relatively expensive) check for new versions
#     # when its most relevant, e.g. when the user runs a long-running command
#     subcommand_run_by_user = sys.argv[3] if len(sys.argv) > 3 else 'help'
#     long_running_commands = ('add', 'schedule', 'update', 'status', 'server')
#     if subcommand_run_by_user not in long_running_commands:
#         return None

#     github_releases_api = "https://api.github.com/repos/ArchiveBox/ArchiveBox/releases"
#     response = requests.get(github_releases_api)
#     if response.status_code != 200:
#         stderr(f'[!] Warning: GitHub API call to check for new ArchiveBox version failed! (status={response.status_code})', color='lightyellow', config=config)
#         return None
#     all_releases = response.json()

#     installed_version = parse_version_string(config['VERSION'])

#     # find current version or nearest older version (to link to)
#     current_version = None
#     for idx, release in enumerate(all_releases):
#         release_version = parse_version_string(release['tag_name'])
#         if release_version <= installed_version:
#             current_version = release
#             break

#     current_version = current_version or all_releases[-1]

#     # recommended version is whatever comes after current_version in the release list
#     # (perhaps too conservative to only recommend upgrading one version at a time, but it's safest)
#     try:
#         recommended_version = all_releases[idx+1]
#     except IndexError:
#         recommended_version = None

#     return {'recommended_version': recommended_version, 'current_version': current_version}

# def can_upgrade(config):
#     if config['VERSIONS_AVAILABLE'] and config['VERSIONS_AVAILABLE']['recommended_version']:
#         recommended_version = parse_version_string(config['VERSIONS_AVAILABLE']['recommended_version']['tag_name'])
#         current_version = parse_version_string(config['VERSIONS_AVAILABLE']['current_version']['tag_name'])
#         return recommended_version > current_version
#     return False


VERSION: str = detect_installed_version()
