from pathlib import Path
import json
import shlex
import os
import re
import shutil
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PIP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pip.yml"
DOCKER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docker.yml"


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

    prepare_path = yaml.safe_load(CI_WORKFLOW.read_text())["jobs"]["prepare"]["uses"]
    prepare = yaml.safe_load((REPO_ROOT / prepare_path).read_text())
    channel_step = next(step for step in prepare["jobs"]["prepare"]["steps"] if step.get("id") == "channel")

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
    # version preparation must not immediately bump dev and undo synchronization.
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
    ci = yaml.safe_load(CI_WORKFLOW.read_text())
    screenshots = yaml.load((REPO_ROOT / ".github" / "workflows" / "screenshots.yml").read_text(), Loader=yaml.BaseLoader)
    prepare_path = ci["jobs"]["prepare"]["uses"]
    prepare = yaml.safe_load((REPO_ROOT / prepare_path).read_text())
    assert prepare["jobs"]["prepare"]["steps"][-1]["uses"] == "ArchiveBox/monorepo/.github/actions/prepare-release-version@main"
    assert set(screenshots["on"]) == {"push", "schedule", "workflow_dispatch"}
    assert screenshots["on"]["push"] == {
        "branches": ["dev"],
        "paths": [
            ".github/workflows/screenshots.yml",
            "bin/take_screenshot.js",
            "bin/setup_ui_screenshot_data.js",
            *[
                f"archivebox/{app}/**"
                for app in ("automation", "domains", "linkhealth", "storage")
                if (REPO_ROOT / "archivebox" / app).is_dir()
            ],
            "archivebox/core/library*",
            "archivebox/core/admin*",
            "archivebox/core/models.py",
            "bin/collect_ui_screenshots.sh",
            "bin/generate_ui_screenshot_gallery.py",
            "archivebox/templates/**",
            "archivebox/core/templatetags/core_tags.py",
        ],
    }
    _, hours, *days = screenshots["on"]["schedule"][0]["cron"].split()
    assert days == ["*", "*", "*"]
    assert len(hours.split(",")) == 2
    first, second = map(int, hours.split(","))
    assert second - first == 12
    assert "prepare" not in screenshots["jobs"]
    assert screenshots["jobs"]["changes"]["steps"][0]["uses"] == "ArchiveBox/monorepo/.github/actions/changed-scheduled-inputs@main"
    assert screenshots["jobs"]["deploy"]["needs"] == "changes"
    assert screenshots["jobs"]["deploy"]["if"] == "needs.changes.outputs.changed == 'true' && github.ref == 'refs/heads/dev'"
    assert screenshots["jobs"]["complete"]["needs"] == ["changes", "deploy"]
    assert screenshots["jobs"]["complete"]["name"] == "Scheduled inputs: ${{ needs.changes.outputs.key }}"
    for name, job in ci["jobs"].items():
        if name not in {"prepare", "required", "dev-image"}:
            assert job["needs"] == "prepare"
            assert job["if"] == "needs.prepare.outputs.run_jobs == 'true'"
    early = ci["jobs"]["dev-image"]
    assert early["needs"] == "docker-digests"
    assert early["if"] == "github.event_name == 'push' && github.ref_name == 'dev'"
    publish = next(step["run"] for step in early["steps"] if step.get("id") == "publish")
    assert '[[ "$(< /tmp/digests/source-ref)" == "$GITHUB_SHA" ]]' in publish
    assert '[[ "${#digests[@]}" -eq 2 ]]' in publish
    assert publish.index('if [[ "$head" != "$GITHUB_SHA" ]]') < publish.index('--tag "$image:dev-unstable"')
    assert '--tag "$image:dev"' not in publish
    assert "dev-image" in ci["jobs"]["required"]["needs"]
    gate = next(step["run"] for step in jobs["candidate"]["steps"] if step.get("id") == "verified")
    assert 'ARTIFACT_RUN_ID="$CI_RUN_ID"' in gate
    assert 'DIGEST_RUN_ID="$CI_RUN_ID"' in gate
    assert 'ARTIFACT_RUN_ID="$CANDIDATE_RUN_ID"' not in gate
    assert 'DIGEST_RUN_ID="$CANDIDATE_RUN_ID"' not in gate
    docker_workflow = yaml.safe_load(DOCKER_WORKFLOW.read_text())
    version_check = next(
        step for step in docker_workflow["jobs"]["build"]["steps"] if step.get("name") == "Validate exact built image version and commit"
    )
    assert version_check["if"] == "inputs.full_tests"
    assert "archivebox version" in version_check["run"]
    assert "Missing exact commit marker" in version_check["run"]
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

    docker_verify = next(step for step in docker_release["steps"] if step.get("name") == "Promote the exact tested universal image")
    verify_script = docker_verify["run"]
    assert docker_verify["env"] == {
        "DOCKERHUB_TAGS": "${{ steps.docker_meta.outputs.dockerhub_tags }}",
        "GHCR_TAGS": "${{ steps.docker_meta.outputs.ghcr_tags }}",
    }
    assert '"${DOCKERHUB_IMAGE}@sha256:${digest}"' in verify_script
    assert 'imagetools create --dry-run "${REFS[@]}"' in verify_script
    assert 'imagetools inspect --raw "${REFS[0]}"' in verify_script
    assert 'imagetools inspect --raw "$tag"' in verify_script
    assert 'sort == ["amd64", "arm64"]' in verify_script
    assert '[[ "$ACTUAL" == "$EXPECTED" ]]' in verify_script
    assert "for registry in DOCKERHUB GHCR" in verify_script
    assert 'REFS=("${!image_var}:sha-${RELEASE_SHA::12}")' in verify_script
    assert 'imagetools create "${TAG_ARGS[@]}" "${REFS[@]}"' in verify_script
    assert "dev-unstable" not in verify_script
    assert "buildx build" not in verify_script

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


def test_dev_promotion_does_not_wait_for_its_own_deployment():
    ci = yaml.safe_load(CI_WORKFLOW.read_text())
    assert set(ci["jobs"]["required"]["needs"]) == {
        "prepare",
        "lint",
        "install-cli-platform",
        "tests",
        "codeql",
        "python-artifacts",
        "docker-digests",
        "dev-image",
    }
    docker = yaml.load(DOCKER_WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    assert docker["on"]["workflow_call"]["inputs"]["full_tests"]["default"] == "true"
    assert ci["jobs"]["docker-digests"]["with"].get("full_tests", True) is True
    validation = next(
        step
        for step in docker["jobs"]["build"]["steps"]
        if step.get("name") == "Validate Docker mounts, ports, CLI and compose concurrently"
    )
    assert "steps.docker_build.outputs.digest" in validation["env"]["ARCHIVEBOX_IMAGE"]


@pytest.mark.parametrize(
    "failed_lane",
    [
        None,
        "LINT_RESULT",
        "INSTALL_CLI_PLATFORM_RESULT",
        "TESTS_RESULT",
        "CODEQL_RESULT",
        "PYTHON_ARTIFACTS_RESULT",
        "DOCKER_DIGESTS_RESULT",
        "DEV_IMAGE_RESULT",
    ],
)
def test_required_ci_gate_rejects_each_failed_lane(failed_lane):
    ci = yaml.safe_load(CI_WORKFLOW.read_text())
    # An explicit status function overrides the implicit success() filter, so
    # failed predecessors still reach this strict shell gate. Cancellation alone
    # must suppress it, allowing the next run to acquire the concurrency group.
    assert ci["jobs"]["required"]["if"] == "${{ !cancelled() && needs.prepare.outputs.run_jobs == 'true' }}"
    gate = ci["jobs"]["required"]["steps"][0]
    env = {**os.environ, **dict.fromkeys(gate["env"], "success")}
    if failed_lane:
        env[failed_lane] = "failure"
    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", gate["run"]], env=env, capture_output=True, text=True)
    assert (result.returncode == 0) is (failed_lane is None), result.stdout + result.stderr


@pytest.mark.parametrize("requested", ["", "archivebox/tests/test_urls.py", "archivebox/tests/test_release_workflow.py"])
def test_ci_batches_preserve_inventory_runner_ownership_and_single_file_runs(tmp_path, requested):
    hosted_paths = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "archivebox/tests").glob("test_*.py")
        if "# ci-runner: hosted" in path.read_text().splitlines()[:5]
    }
    result = subprocess.run(
        ["uv", "run", "--no-cache", "--no-project", "python", str(REPO_ROOT / ".github/scripts/discover_test_matrix.py")],
        cwd=tmp_path,
        env={**os.environ, "TEST_FILE": requested, "UGNAS_CI_MAX_JOBS": "3"},
        capture_output=True,
        text=True,
        check=True,
    )
    matrix = json.loads(result.stdout.splitlines()[1])
    paths = [path for item in matrix for path in item["paths"]]
    expected = sorted(path.relative_to(REPO_ROOT).as_posix() for path in (REPO_ROOT / "archivebox/tests").glob("test_*.py"))
    assert sorted(paths) == expected
    assert len(paths) == len(set(paths))
    assert len(matrix) < len(paths)
    assert all(1 <= len(item["paths"]) <= 8 for item in matrix)
    assert sum(item["ugnas"] for item in matrix) == 3
    assert not any(path in hosted_paths for item in matrix if item["ugnas"] for path in item["paths"])
    ldap = next(item for item in matrix if item["extra"] == "ldap")
    assert ldap["paths"] == ["archivebox/tests/test_auth_ldap.py"]
    if requested:
        assert len([item for item in matrix if item["paths"] == [requested]]) == 1


def test_ci_discovery_handles_added_renamed_and_deleted_files_without_timing_edits(tmp_path):
    script = tmp_path / ".github/scripts/discover_test_matrix.py"
    script.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / ".github/scripts/discover_test_matrix.py", script)
    shutil.copy2(REPO_ROOT / ".github/test-durations.json", tmp_path / ".github/test-durations.json")
    tests = tmp_path / "archivebox/tests"
    tests.mkdir(parents=True)
    for name in ("test_core_config.py", "test_util.py"):
        shutil.copy2(REPO_ROOT / "archivebox/tests" / name, tests / name)

    def discover():
        result = subprocess.run(
            ["uv", "run", "--no-cache", "--no-project", "python", str(script)],
            cwd=tmp_path,
            env={**os.environ, "TEST_FILE": "", "UGNAS_CI_MAX_JOBS": "3"},
            capture_output=True,
            text=True,
            check=True,
        )
        matrix = json.loads(result.stdout.splitlines()[1])
        paths = [path for item in matrix for path in item["paths"]]
        assert sorted(paths) == sorted(path.relative_to(tmp_path).as_posix() for path in tests.glob("test_*.py"))
        assert len(paths) == len(set(paths))
        return matrix

    assert len(discover()) == 1
    (tests / "test_util.py").rename(tests / "test_renamed.py")
    assert len(discover()) == 2
    shutil.copy2(REPO_ROOT / "archivebox/tests/test_util.py", tests / "test_added.py")
    assert len(discover()) == 3
    (tests / "test_core_config.py").unlink()
    assert len(discover()) == 2

    source = REPO_ROOT / "archivebox/tests/test_util.py"
    (tests / "test_runner.py").write_text("# ci-runner: hosted\n" + source.read_text())
    assert next(item for item in discover() if "archivebox/tests/test_runner.py" in item["paths"])["ugnas"] is False
    (tests / "test_runner.py").rename(tests / "test_runner_renamed.py")
    assert next(item for item in discover() if "archivebox/tests/test_runner_renamed.py" in item["paths"])["ugnas"] is False
    (tests / "test_runner_renamed.py").unlink()
    assert all(item["ugnas"] for item in discover())

    (tests / "test_core_config.py").write_text("# ci-workers: 1\n" + source.read_text())
    limited = next(item for item in discover() if "archivebox/tests/test_core_config.py" in item["paths"])
    assert limited["paths"] == ["archivebox/tests/test_core_config.py"]
    assert limited["max_workers"] == 1
    (tests / "test_core_config.py").rename(tests / "test_limited_renamed.py")
    renamed = next(item for item in discover() if "archivebox/tests/test_limited_renamed.py" in item["paths"])
    assert renamed["max_workers"] == 1


def test_ci_collects_runtime_logs_without_following_snapshot_symlinks(tmp_path):
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/test-parallel.yml").read_text())
    step = next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "Collect failed runtime diagnostics"
    )
    home = tmp_path / "home"
    lib = tmp_path / "persistent-lib"
    logs = {
        tmp_path / "pytest/snapshot/hashes/hook.stderr.log": "original hook failure\n",
        home / ".npm/_logs/install.log": "npm download failure\n",
        lib / "cache/npm/_logs/bootstrap.log": "pnpm bootstrap failure\n",
    }
    for path, content in logs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (tmp_path / "pytest/loop").symlink_to("loop")
    (tmp_path / "pytest/snapshot/loop").symlink_to("..", target_is_directory=True)
    (tmp_path / "pytest/snapshot/broken.log").symlink_to("missing.log")
    (tmp_path / "pytest/snapshot/alias.log").symlink_to("hashes/hook.stderr.log")
    os.mkfifo(tmp_path / "pytest/snapshot/pipe.log")
    (tmp_path / "pytest/snapshot/not-a-log.txt").write_text("not diagnostic output")

    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=tmp_path,
        env={**os.environ, "HOME": str(home), "RUNNER_TEMP": str(tmp_path), "ABXPKG_LIB_DIR": str(lib)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = tmp_path / "runtime-logs"
    saved = {str(path.relative_to(output)): path.read_text() for path in output.rglob("*.log")}
    assert saved == {
        "pytest/snapshot/hashes/hook.stderr.log": "original hook failure\n",
        "npm/install.log": "npm download failure\n",
        "managed-npm/bootstrap.log": "pnpm bootstrap failure\n",
    }
    assert not any(path.is_symlink() for path in output.rglob("*"))


@pytest.mark.parametrize("runner,limit", [("github-hosted", 0), ("github-hosted", 1), ("self-hosted", 0), ("self-hosted", 1)])
def test_ci_applies_declared_worker_limit_without_changing_runtime_paths(tmp_path, runner, limit):
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/test-parallel.yml").read_text())
    step = next(
        step for job in workflow["jobs"].values() for step in job.get("steps", []) if step.get("name") == "Set job-local runtime paths"
    )
    env_file = tmp_path / "github-env"
    subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            **os.environ,
            "CI_RUNNER_ENVIRONMENT": runner,
            "CI_TEST_MAX_WORKERS": str(limit),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ENV": str(env_file),
        },
        check=True,
    )
    written = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    available = int(subprocess.check_output(["nproc"], text=True)) if runner == "github-hosted" else 2
    assert int(written["CI_TEST_WORKERS"]) == (min(available, limit) if limit else available)
    assert written["DATA_DIR"] == str(tmp_path / "archivebox-test-data")
    assert written["PERSONAS_DIR"] == str(tmp_path / "abx-personas")


def test_stacked_feature_prs_run_full_ci_without_publishing():
    ci = yaml.load(CI_WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    assert ci["on"]["pull_request"]["branches"] == ["dev", "main", "codex/feature-*"]
    assert ci["on"]["push"]["branches"] == ["dev", "main"]
    assert ci["jobs"]["dev-image"]["if"] == "github.event_name == 'push' && github.ref_name == 'dev'"


def test_pr_image_exports_use_release_compression_and_size_budget():
    docker = yaml.safe_load(DOCKER_WORKFLOW.read_text())
    steps = docker["jobs"]["build"]["steps"]
    pr_build = next(step for step in steps if step.get("id") == "docker_build_pr")
    release_build = next(step for step in steps if step.get("id") == "docker_build")
    assert "compression=zstd,compression-level=8" in release_build["with"]["outputs"]
    outputs = pr_build["with"]["outputs"].strip().splitlines()
    assert len(outputs) == 2
    assert outputs[0].startswith("type=docker,")
    assert outputs[1].startswith("type=oci,")
    assert all(output.endswith(",compression=zstd,compression-level=8") for output in outputs)
    validation = next(step for step in steps if step.get("name") == "Validate compressed image size")
    assert "$((1025 * 1024 * 1024))" in validation["run"]
    assert "if total > limit:" in validation["run"]
