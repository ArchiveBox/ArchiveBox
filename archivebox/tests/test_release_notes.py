import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_NOTES_SCRIPT = REPO_ROOT / "bin" / "release_notes.py"


def git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_release_notes_falls_back_when_notes_are_deleted(tmp_path):
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.name", "ArchiveBox test")
    git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")
    notes = tmp_path / "docs" / "Release-Notes.md"
    notes.parent.mkdir()
    notes.write_text("Reviewed release notes\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "--quiet", "-m", "base")
    git(tmp_path, "tag", "v0.9.0")

    notes.unlink()
    git(tmp_path, "add", "-u")
    git(tmp_path, "commit", "--quiet", "-m", "Remove release notes")
    ref = git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    result = subprocess.run(
        [sys.executable, str(RELEASE_NOTES_SCRIPT), "v0.10.0", ref],
        cwd=tmp_path,
        env={**os.environ, "GIT_BINARY": "git"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "## Changes since v0.9.0" in result.stdout
    assert "Remove release notes" in result.stdout
    assert "Reviewed release notes" not in result.stdout
