from pathlib import Path
import shlex

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
RELEASE_CANDIDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-candidate.yml"
PIP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pip.yml"


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
    assert docker_release["needs"] == "python-release"
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
