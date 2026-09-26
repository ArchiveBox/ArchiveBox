import json
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FINGERPRINT_SCRIPT = REPO_ROOT / "bin" / "release-source-fingerprint.py"
_SPEC = importlib.util.spec_from_file_location("release_source_fingerprint", FINGERPRINT_SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_FINGERPRINT_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FINGERPRINT_MODULE)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _fingerprint(repo: Path, revision: str) -> str:
    return subprocess.run(
        [sys.executable, str(FINGERPRINT_SCRIPT), revision],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_template_tree(repo: Path) -> None:
    (repo / "etc").mkdir()
    project = (REPO_ROOT / "pyproject.toml").read_text()
    project = re.sub(r'^version = "[^"]+"$', 'version = "0.9.56rc41"', project, count=1, flags=re.M)
    project = re.sub(r'^current_version = "[^"]+"$', 'current_version = "v0.9.56rc41"', project, count=1, flags=re.M)
    assert 'version = "0.9.56rc41"' in project
    assert 'current_version = "v0.9.56rc41"' in project
    lock, count = re.subn(
        r'(\[\[package\]\]\nname = "archivebox"\nversion = ")[^"]+',
        r"\g<1>0.9.56rc41",
        (REPO_ROOT / "uv.lock").read_text(),
        count=1,
    )
    assert count == 1
    package = json.loads((REPO_ROOT / "etc/package.json").read_text())
    package["version"] = "0.9.56rc41"
    (repo / "pyproject.toml").write_text(project)
    (repo / "uv.lock").write_text(lock)
    (repo / "etc/package.json").write_text(json.dumps(package, indent=2) + "\n")
    (repo / "source.py").write_text("release behavior = unchanged\n")


def _new_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "config", "user.name", "ArchiveBox Tests")
    _git(repo, "config", "user.email", "tests@archivebox.io")
    _write_template_tree(repo)
    return repo, _commit(repo, "stable acceptance source")


def test_fingerprint_ignores_only_archivebox_release_version_fields(tmp_path):
    repo, accepted = _new_repo(tmp_path)
    project = repo / "pyproject.toml"
    text = project.read_text()
    text = re.sub(r'^version = "[^"]+"$', 'version = "0.9.64"', text, count=1, flags=re.M)
    text = re.sub(r'^current_version = "[^"]+"$', 'current_version = "v0.9.64"', text, count=1, flags=re.M)
    project.write_text(text)
    lock = repo / "uv.lock"
    lock.write_text(re.sub(r'(?m)^(version = ")0\.9\.56rc41("\s*)$', r"\g<1>0.9.64\2", lock.read_text(), count=1))
    package = repo / "etc/package.json"
    package.write_text(package.read_text().replace('"version": "0.9.56rc41"', '"version": "0.9.64"'))
    stable = _commit(repo, "stable version bump")

    assert _fingerprint(repo, accepted) == _fingerprint(repo, stable)


def test_pyproject_version_normalization_matches_exact_template_bytes():
    project = (REPO_ROOT / "pyproject.toml").read_bytes()
    normalized = _FINGERPRINT_MODULE.normalize_file(b"pyproject.toml", project)
    expected = re.sub(
        rb'(?m)^(version = ")[^"\r\n]+("\s*(?:#.*)?\r?\n?)$',
        lambda match: match.group(1) + b"<ARCHIVEBOX_PROJECT_VERSION>" + match.group(2),
        project,
        count=1,
    )
    expected = re.sub(
        rb'(?m)^(current_version = ")[^"\r\n]+("\s*(?:#.*)?\r?\n?)$',
        lambda match: match.group(1) + b"<ARCHIVEBOX_PROJECT_VERSION>" + match.group(2),
        expected,
        count=1,
    )
    assert normalized == expected


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "project_dependency",
        "lock_dependency",
        "package_dependency",
        "other_tool_version",
        "file_mode",
    ],
)
def test_fingerprint_detects_non_release_version_changes(tmp_path, change):
    repo, accepted = _new_repo(tmp_path)
    if change == "source":
        (repo / "source.py").write_text("release behavior = changed\n")
    elif change == "project_dependency":
        path = repo / "pyproject.toml"
        path.write_text(path.read_text().replace('"abx-dl==1.13.51"', '"abx-dl==999.0"', 1))
    elif change == "lock_dependency":
        path = repo / "uv.lock"
        path.write_text(re.sub(r'(?m)(^name = "abx-dl"\nversion = ")[^"]+', r"\g<1>999.0", path.read_text(), count=1))
    elif change == "package_dependency":
        path = repo / "etc/package.json"
        payload = json.loads(path.read_text())
        name = next(iter(payload["dependencies"]))
        payload["dependencies"][name] = "999.0"
        path.write_text(json.dumps(payload, indent=2) + "\n")
    elif change == "other_tool_version":
        path = repo / "pyproject.toml"
        path.write_text(path.read_text() + '\n[tool.other]\nversion = "1.0"\n')
        _commit(repo, "add unrelated tool version")
        path.write_text(path.read_text().replace('version = "1.0"', 'version = "2.0"'))
    elif change == "file_mode":
        path = repo / "source.py"
        path.chmod(0o755)

    changed = _commit(repo, change)
    assert _fingerprint(repo, accepted) != _fingerprint(repo, changed)


def test_fingerprint_detects_submodule_gitlink_changes(tmp_path):
    repo, accepted = _new_repo(tmp_path)
    subrepo = tmp_path / "dependency"
    subrepo.mkdir()
    subprocess.run(["git", "init", "-q", str(subrepo)], check=True)
    _git(subrepo, "config", "user.name", "ArchiveBox Tests")
    _git(subrepo, "config", "user.email", "tests@archivebox.io")
    (subrepo / "dependency.txt").write_text("one\n")
    first = _commit(subrepo, "first dependency revision")
    (repo / "vendor").mkdir()
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{first},vendor/dependency")
    _git(repo, "commit", "-m", "add dependency gitlink")
    one = _git(repo, "rev-parse", "HEAD")

    (subrepo / "dependency.txt").write_text("two\n")
    second = _commit(subrepo, "second dependency revision")
    _git(repo, "update-index", "--cacheinfo", f"160000,{second},vendor/dependency")
    _git(repo, "commit", "-m", "update dependency gitlink")
    two = _git(repo, "rev-parse", "HEAD")

    assert _fingerprint(repo, accepted) != _fingerprint(repo, one)
    assert _fingerprint(repo, one) != _fingerprint(repo, two)
