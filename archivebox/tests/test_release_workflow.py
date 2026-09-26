from pathlib import Path
import json
import shlex
import os
import re
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
RELEASE_CANDIDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-candidate.yml"
PIP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pip.yml"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize(
    "dev_change",
    [None, "no_bump", "source", "project_dependency", "locked_dependency", "package_dependency", "other_tool_version"],
)
def test_stable_release_reconciles_concurrent_version_only_dev_bump(tmp_path, dev_change):
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    steps = workflow["jobs"]["docker-release"]["steps"]
    sync_step = next(step for step in steps if step.get("name") == "Reconcile dev to the tested stable release")
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(work)], check=True, capture_output=True)
    _git(work, "config", "user.name", "ArchiveBox Tests")
    _git(work, "config", "user.email", "tests@archivebox.io")
    _git(work, "switch", "-c", "dev")
    (work / "etc").mkdir()
    project_template = (REPO_ROOT / "pyproject.toml").read_text() + '\n[tool.other]\nversion = "1.0"\n'
    lock_template = (REPO_ROOT / "uv.lock").read_text()
    package_template = (REPO_ROOT / "etc/package.json").read_text()

    def write_version(version):
        project, count = re.subn(r'^version = "[^"]+"$', f'version = "{version}"', project_template, count=1, flags=re.M)
        assert count == 1
        project, count = re.subn(r'^current_version = "[^"]+"$', f'current_version = "v{version}"', project, count=1, flags=re.M)
        assert count == 1
        lock, count = re.subn(
            r'(\[\[package\]\]\nname = "archivebox"\nversion = ")[^"]+',
            lambda match: f"{match.group(1)}{version}",
            lock_template,
            count=1,
        )
        assert count == 1
        package, count = re.subn(
            r'^(  "version": ")[^"]+',
            lambda match: f"{match.group(1)}{version}",
            package_template,
            count=1,
            flags=re.M,
        )
        assert count == 1
        (work / "pyproject.toml").write_text(project)
        (work / "uv.lock").write_text(lock)
        (work / "etc/package.json").write_text(package)

    write_version("0.9.56rc41")
    (work / "source.py").write_text("tested = True\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "tested source")
    base = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "origin", "dev")
    _git(work, "switch", "-c", "main")
    write_version("0.9.64")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "Bump release version to 0.9.64")
    stable = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "origin", "main")
    _git(work, "switch", "dev")
    if dev_change != "no_bump":
        write_version("0.9.56rc42")
    if dev_change == "source":
        (work / "source.py").write_text("tested = False\n")
    elif dev_change == "project_dependency":
        project = work / "pyproject.toml"
        project.write_text(re.sub(r'"abx-dl==[^"]+"', '"abx-dl==999.0"', project.read_text(), count=1))
    elif dev_change == "locked_dependency":
        lock = work / "uv.lock"
        lock.write_text(re.sub(r'(name = "abx-dl"\nversion = ")[^"]+', r"\g<1>999.0", lock.read_text(), count=1))
    elif dev_change == "package_dependency":
        package = work / "etc/package.json"
        dependencies = json.loads(package.read_text())["dependencies"]
        name, value = next(iter(dependencies.items()))
        package.write_text(package.read_text().replace(f'"{name}": "{value}"', f'"{name}": "999.0"'))
    elif dev_change == "other_tool_version":
        project = work / "pyproject.toml"
        project.write_text(project.read_text().replace('[tool.other]\nversion = "1.0"', '[tool.other]\nversion = "2.0"'))
    if dev_change != "no_bump":
        _git(work, "add", ".")
        _git(work, "commit", "-m", "Bump release version to 0.9.56rc42")
    candidate = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "origin", "dev")
    _git(work, "checkout", "--detach", stable)

    env = {**os.environ, "RELEASE_SHA": stable}
    result = subprocess.run(["bash", "-c", sync_step["run"]], cwd=work, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    merged = _git(work, "ls-remote", "origin", "refs/heads/dev").split()[0]

    channel_step = next(
        step for step in yaml.safe_load(RELEASE_CANDIDATE_WORKFLOW.read_text())["jobs"]["prepare"]["steps"] if step.get("id") == "channel"
    )

    def stable_channel(sha, branch="dev"):
        output = tmp_path / "channel-output"
        output.write_text("")
        channel_env = {**env, "GITHUB_SHA": sha, "GITHUB_REF_NAME": branch, "GITHUB_OUTPUT": str(output)}
        result = subprocess.run(["bash", "-c", channel_step["run"]], cwd=work, env=channel_env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return output.read_text().strip()

    if dev_change == "no_bump":
        assert merged == stable
        assert stable_channel(merged) == "stable=true"
        return
    if dev_change:
        assert merged == candidate
        assert "contains changes beyond" in result.stdout
        return
    assert merged not in {candidate, stable}
    assert _git(work, "rev-list", "--parents", "-n", "1", merged).split() == [merged, stable, candidate]
    assert _git(work, "rev-parse", f"{merged}^{{tree}}") == _git(work, "rev-parse", f"{stable}^{{tree}}")
    assert _git(work, "merge-base", stable, candidate) == base
    # Reconciliation creates a new merge commit with the tested main tree. Its
    # candidate workflow must not immediately bump dev and undo synchronization.
    assert stable_channel(merged) == "stable=true"
    assert stable_channel(merged, branch="main") == "stable=false"

    tag_script = next(step["run"] for step in steps if step.get("id") == "docker_meta")
    start = tag_script.index("SYNC_DEV=false")
    end = tag_script.index("\n{", start)
    sync_script = tag_script[start:end] + '\nprintf "%s\\n" "$SYNC_DEV"\n'
    sync_env = {**env, "GIT_BINARY": "git", "RELEASE_BRANCH": "main"}

    def sync_dev():
        result = subprocess.run(["bash", "-e", "-c", sync_script], cwd=work, env=sync_env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip().splitlines()[-1]

    assert sync_dev() == "true"
    _git(work, "switch", "-c", "after-merge", merged)
    (work / "source.py").write_text("tested = False\n")
    _git(work, "add", "source.py")
    _git(work, "commit", "-m", "New dev source change")
    _git(work, "push", "origin", "HEAD:refs/heads/dev")
    assert sync_dev() == "false"
    assert stable_channel(_git(work, "rev-parse", "HEAD")) == "stable=false"


def test_release_uses_registered_publisher_and_authorized_tag_credentials():
    assert RELEASE_WORKFLOW.exists()
    assert not (REPO_ROOT / ".github" / "workflows" / "release-runner.yml").exists()

    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    jobs = workflow["jobs"]
    python_release = jobs["python-release"]
    docker_release = jobs["docker-release"]

    assert python_release["environment"] == "pypi"
    checkout = python_release["steps"][0]
    assert checkout["with"]["token"] == "${{ secrets.RELEASE_GH_TOKEN || github.token }}"
    assert docker_release["needs"] == ["candidate", "python-release"]
    assert docker_release["env"]["DOCKER_DIGEST_RUN_ID"] == "${{ needs.candidate.outputs.digest_run_id }}"
    assert "release_ready" not in docker_release["if"]
    assert jobs["cascade"]["if"] == "needs.python-release.outputs.release_ready == 'true'"

    assert all(step.get("name") != "Verify published PyPI package installs and runs" for step in python_release["steps"])
    candidate = yaml.safe_load(RELEASE_CANDIDATE_WORKFLOW.read_text())
    assert candidate["jobs"]["python-artifacts"]["with"]["full_tests"] is False
    pip_workflow = yaml.safe_load(PIP_WORKFLOW.read_text())
    install_script = next(
        step["run"] for step in pip_workflow["jobs"]["build"]["steps"] if step.get("name") == "Release wheel import and CLI smoke"
    )
    assert "uv pip install --no-cache" in install_script
    assert "import archivebox" in install_script
    assert "archivebox version" in install_script

    docker_meta = next(step for step in docker_release["steps"] if step.get("id") == "docker_meta")
    tag_script = docker_meta["run"]
    owner_script = next(step["run"] for step in jobs["candidate"]["steps"] if step.get("id") == "owner")
    assert '[[ "$VERSION" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+$ ]]' in owner_script
    assert 'git merge-base --is-ancestor "$RELEASE_SHA" origin/main' in owner_script
    assert '[[ "$VERSION" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+$ ]]' in tag_script
    assert '[[ "$TAG_TARGET" == "$RELEASE_SHA" ]]' in tag_script
    assert '$GIT_BINARY merge-base --is-ancestor "$RELEASE_SHA" origin/main' in tag_script
    assert '[[ "$MAIN_VERSION" == "$VERSION" ]]' in tag_script
    assert '$GIT_BINARY merge-base --is-ancestor "$MAIN_TARGET" "$DEV_TARGET"' in tag_script
    assert '$GIT_BINARY diff --quiet "$MAIN_TARGET" "$DEV_TARGET"' in tag_script
    assert 'echo "${DOCKERHUB_IMAGE}:dev"' in tag_script
    assert 'echo "${DOCKERHUB_IMAGE}:sha-${SHORT_SHA}"' in tag_script
    assert 'echo "${DOCKERHUB_IMAGE}:${VERSION}"' in tag_script

    docker_verify = next(step for step in docker_release["steps"] if step.get("name") == "Verify published Docker images run")
    verify_script = docker_verify["run"]
    assert '"${DOCKERHUB_IMAGE}:sha-${SHORT_SHA}"' in verify_script
    assert '"${GHCR_IMAGE}:sha-${SHORT_SHA}"' in verify_script
    assert '"${DOCKERHUB_IMAGE}:${VERSION}"' not in verify_script

    release_script = (REPO_ROOT / "bin" / "release.sh").read_text()
    assert "Never create GitHub Releases for automated rc builds" in release_script
    assert "--prerelease" not in release_script
    assert "repos/${SLUG}/releases?per_page=100" not in release_script
    assert 'if [[ "$IS_RC" != true ]] && $GH_BINARY release view' in release_script
    assert "subscribed user" in release_script

    logical_lines = []
    current_line = ""
    for line in release_script.splitlines():
        current_line = f"{current_line} {line.strip()}".strip()
        if current_line.endswith("\\"):
            current_line = current_line[:-1]
            continue
        logical_lines.append(current_line)
        current_line = ""
    assert not current_line

    release_commands = [shlex.split(line) for line in logical_lines if line.startswith(("$GIT_BINARY ", "$UV_BINARY ", "$GH_BINARY "))]
    create_tag = next(
        index
        for index, command in enumerate(release_commands)
        if command[:3] == ["$GIT_BINARY", "push", "origin"] and command[3] == "refs/tags/${TAG}"
    )
    publish_pypi = next(index for index, command in enumerate(release_commands) if command[:2] == ["$UV_BINARY", "publish"])
    create_release = next(index for index, command in enumerate(release_commands) if command[:3] == ["$GH_BINARY", "release", "create"])

    publish_command = release_commands[publish_pypi]
    assert "--no-cache" in publish_command
    assert publish_command[publish_command.index("--trusted-publishing") + 1] == "always"
    assert "--verify-tag" in release_commands[create_release]
    assert create_tag < publish_pypi < create_release

    publish_line = logical_lines.index(next(line for line in logical_lines if line.startswith("$UV_BINARY publish ")))
    rc_skip_line = logical_lines.index(
        next(line for line in logical_lines if "skipped GitHub Release for rc version" in line and "CI_RUN_ID" in line),
    )
    create_release_line = logical_lines.index(next(line for line in logical_lines if line.startswith("$GH_BINARY release create ")))
    upload_release_line = logical_lines.index(next(line for line in logical_lines if line.startswith("$GH_BINARY release upload ")))
    assert publish_line < rc_skip_line < create_release_line < upload_release_line
