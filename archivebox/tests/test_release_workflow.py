from pathlib import Path
import ast
import json
import importlib.util
import shlex
import os
import re
import shutil
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
RELEASE_CANDIDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-candidate.yml"
PIP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pip.yml"
DOCKER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docker.yml"
VERIFY_STAGING_SCRIPT = REPO_ROOT / "bin" / "verify-staging-release.py"
_VERIFY_SPEC = importlib.util.spec_from_file_location("verify_staging_release", VERIFY_STAGING_SCRIPT)
assert _VERIFY_SPEC is not None and _VERIFY_SPEC.loader is not None
_VERIFY_STAGING = importlib.util.module_from_spec(_VERIFY_SPEC)
_VERIFY_SPEC.loader.exec_module(_VERIFY_STAGING)


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
    assert "opencode" not in candidate["jobs"]
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


def test_stable_publication_requires_live_acceptance_before_upload():
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    publisher = workflow["jobs"]["python-release"]
    steps = publisher["steps"]
    gate = next(i for i, step in enumerate(steps) if step.get("name") == "Require matching acceptance on Cabbage")
    upload = next(i for i, step in enumerate(steps) if step.get("name") == "Publish the exact tested distributions")
    assert gate < upload
    # The same guard applies to automatic and manually requested stable releases.
    assert steps[gate]["if"] == "env.RELEASE_BRANCH == 'main'"
    assert "verify-staging-release.py" in steps[gate]["run"]
    assert not steps[gate].get("continue-on-error")
    assert publisher["permissions"]["deployments"] == "read"
    staging = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "staging-acceptance.yml").read_text())
    assert staging["jobs"]["acceptance"]["strategy"]["matrix"]["target"] == ["cabbage"]
    verifier = VERIFY_STAGING_SCRIPT.read_text()
    assert 'for environment in ("cabbage",):' in verifier
    assert "source_fingerprint" in verifier
    assert 'inspection.get("health") != "healthy"' in verifier
    assert "expected_abx_dl_digest" in verifier
    assert 'run["conclusion"] != "success"' in verifier


def test_staging_acceptance_uses_published_image_source_not_workflow_run_head():
    release = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    docker_steps = release["jobs"]["docker-release"]["steps"]
    verified = next(i for i, step in enumerate(docker_steps) if step.get("name") == "Verify published Docker images run")
    source = next(i for i, step in enumerate(docker_steps) if step.get("name") == "Record published image source")
    uploaded = next(i for i, step in enumerate(docker_steps) if step.get("name") == "Upload published image source")
    assert verified < source < uploaded
    assert docker_steps[uploaded]["with"]["name"] == "published-image-source"

    staging_text = (REPO_ROOT / ".github" / "workflows" / "staging-acceptance.yml").read_text()
    assert "branches: [dev]" not in staging_text
    assert "workflow_run.head_branch" not in staging_text
    assert "workflow_run.head_sha" not in staging_text
    staging = yaml.safe_load(staging_text)
    published = staging["jobs"]["published"]
    download = next(step for step in published["steps"] if step.get("name") == "Download published image source")
    assert download["with"]["name"] == docker_steps[uploaded]["with"]["name"]
    assert download["with"]["run-id"] == "${{ github.event.workflow_run.id }}"
    assert "head_branch" not in published["if"]
    assert published["outputs"]["sha"] == "${{ steps.source.outputs.sha }}"
    assert published["outputs"]["ready"] == "${{ steps.source.outputs.ready }}"
    assert '"$RELEASE_BRANCH"' in docker_steps[source]["run"]
    assert '"$RELEASE_SHA"' in docker_steps[source]["run"]
    assert '"$branch" == dev' in next(step for step in published["steps"] if step.get("id") == "source")["run"]

    acceptance = staging["jobs"]["acceptance"]
    assert acceptance["steps"][0]["with"]["ref"] == "${{ needs.published.outputs.sha }}"
    verify = next(
        step for step in acceptance["steps"] if step.get("name") == "Verify actual deployment, full captures and rendered snapshots"
    )
    assert verify["env"]["STAGING_SHA"] == "${{ needs.published.outputs.sha }}"


@pytest.mark.parametrize(("branch", "ready"), [("dev", "true"), ("main", "false")])
def test_staging_selects_actual_published_branch(tmp_path, branch, ready):
    release = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    record = next(step for step in release["jobs"]["docker-release"]["steps"] if step.get("name") == "Record published image source")
    staging = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "staging-acceptance.yml").read_text())
    select = next(step for step in staging["jobs"]["published"]["steps"] if step.get("id") == "source")
    jq = shutil.which("jq")
    assert jq is not None
    sha = "a" * 40
    output = tmp_path / "github-output"
    output.touch()
    env = {
        **os.environ,
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "JQ_BINARY": jq,
        "RELEASE_BRANCH": branch,
        "RELEASE_SHA": sha,
    }

    recorded = subprocess.run(["bash", "-c", record["run"]], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert recorded.returncode == 0, recorded.stderr
    source = tmp_path / "published-image-source" / "source.json"
    assert json.loads(source.read_text()) == {"branch": branch, "sha": sha}

    selected = subprocess.run(["bash", "-c", select["run"]], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert selected.returncode == 0, selected.stderr
    assert output.read_text().splitlines() == [f"sha={sha}", f"ready={ready}"]


def test_staging_rejects_published_source_with_malformed_sha(tmp_path):
    staging = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "staging-acceptance.yml").read_text())
    select = next(step for step in staging["jobs"]["published"]["steps"] if step.get("id") == "source")
    source = tmp_path / "published-image-source" / "source.json"
    source.parent.mkdir()
    source.write_text(json.dumps({"branch": "dev", "sha": "not-a-sha"}))
    output = tmp_path / "github-output"
    output.touch()
    env = {**os.environ, "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(output)}

    selected = subprocess.run(["bash", "-c", select["run"]], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert selected.returncode != 0
    assert output.read_text() == ""


def test_staging_gate_matches_the_exact_tested_docker_base_digest(tmp_path):
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    publisher = workflow["jobs"]["python-release"]
    steps = publisher["steps"]
    metadata = next(step for step in steps if step.get("name") == "Download tested Docker base-image metadata")
    gate = next(step for step in steps if step.get("name") == "Require matching acceptance on Cabbage")
    assert metadata["with"]["run-id"] == "${{ env.DOCKER_DIGEST_RUN_ID }}"
    assert publisher["env"]["DOCKER_DIGEST_RUN_ID"] == "${{ needs.candidate.outputs.digest_run_id }}"
    assert metadata["with"]["pattern"] == "digest-*"
    assert metadata["with"]["merge-multiple"] is True
    assert metadata["with"]["path"] == "${{ runner.temp }}/tested-docker-artifacts"
    assert steps.index(metadata) < steps.index(gate)
    assert gate["env"]["STAGING_DOCKER_ARTIFACT_DIR"] == "${{ runner.temp }}/tested-docker-artifacts"

    docker_workflow = yaml.safe_load(DOCKER_WORKFLOW.read_text())
    export = next(step for step in docker_workflow["jobs"]["build"]["steps"] if step.get("name") == "Export digest")
    assert export["env"]["ABX_DL_IMAGE_REF"] == "${{ steps.abx_dl_image.outputs.image }}"
    assert '"/tmp/digests/abx-dl-image-$ARTIFACT_NAME"' in export["run"]
    helper = (REPO_ROOT / "bin" / "staging-acceptance-host.sh").read_text()
    assert "abx_dl_image" in helper

    source_sha = "a" * 40
    base_digest = "sha256:" + "b" * 64
    (tmp_path / "source-ref").write_text(source_sha + "\n")
    for platform in ("linux-amd64", "linux-arm64"):
        (tmp_path / f"abx-dl-image-digest-{platform}").write_text(f"archivebox/abx-dl:1.13.51@{base_digest}\n")
    assert _VERIFY_STAGING.tested_abx_dl_digest(tmp_path, source_sha) == base_digest

    (tmp_path / "abx-dl-image-digest-linux-arm64").write_text(f"archivebox/abx-dl:1.13.52@{'sha256:' + 'c' * 64}\n")
    with pytest.raises(SystemExit, match="different abx-dl images"):
        _VERIFY_STAGING.tested_abx_dl_digest(tmp_path, source_sha)
    with pytest.raises(SystemExit, match="different source commit"):
        _VERIFY_STAGING.tested_abx_dl_digest(tmp_path, "d" * 40)


def test_staging_acceptance_limits_only_exact_known_auth_and_tls_failures():
    helper = (REPO_ROOT / "bin" / "staging-acceptance-host.sh").read_text()
    embedded = re.search(r"script=\"\$\(cat <<'PY'\n(.*?)\nPY\n\)\"", helper, re.S)
    assert embedded, "staging acceptance Python body not found"
    tree = ast.parse(embedded.group(1))
    classifier = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "accepted_limitation")
    namespace = {}
    exec(compile(ast.Module(body=[classifier], type_ignores=[]), "staging-acceptance", "exec"), namespace)
    accepts = namespace["accepted_limitation"]

    assert accepts("tlsnotary", "failed", "Not enough memory for TLSNotary")
    assert accepts("claudechrome", "failed", "ANTHROPIC_API_KEY not set")
    assert accepts("claudecodeextract", "failed", "Claude Code auth not set")
    assert accepts("claudecodecleanup", "failed", "Claude Code auth not set")
    assert not accepts("claudechrome", "failed", "ANTHROPIC_API_KEY not set; other failure")
    assert not accepts("other-plugin", "failed", "Claude Code auth not set")
    assert not accepts("claudechrome", "succeeded", "ANTHROPIC_API_KEY not set")
    assert "'limitations': []" in embedded.group(1)
    assert "'PLUGINS': ','.join(sorted(catalog))" in embedded.group(1)
    assert "for plugin in capture_plugins:" in embedded.group(1)
    assert "missing or truncated" in embedded.group(1)
    assert "output.stat().st_size != metadata.get('size')" in embedded.group(1)
    assert "tlsnotary reported unexpected status" in embedded.group(1)


@pytest.mark.parametrize("requested", ["", "archivebox/tests/test_urls.py", "archivebox/tests/test_release_workflow.py"])
def test_ci_batches_preserve_inventory_runner_ownership_and_single_file_runs(tmp_path, requested):
    nas_names = ["main/test_urls", "main/test_cli_machine", "main/test_cli_run", "main/test_takeover_util"]
    result = subprocess.run(
        ["uv", "run", "--no-cache", "--no-project", "python", str(REPO_ROOT / ".github/scripts/discover_test_matrix.py")],
        cwd=tmp_path,
        env={**os.environ, "TEST_FILE": requested, "UGNAS_CI_TESTS": json.dumps(nas_names)},
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
    for name in nas_names:
        item = next(item for item in matrix if item["name"] == name)
        assert item["paths"] == [f"archivebox/tests/{name.split('/')[-1]}.py"]
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
            env={**os.environ, "TEST_FILE": "", "UGNAS_CI_TESTS": "[]"},
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
