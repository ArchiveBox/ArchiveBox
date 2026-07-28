from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


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

    docker_meta = next(step for step in docker_release["steps"] if step.get("id") == "docker_meta")
    tag_script = docker_meta["run"]
    assert 'echo "${DOCKERHUB_IMAGE}:dev"' in tag_script
    assert 'echo "${DOCKERHUB_IMAGE}:sha-${SHORT_SHA}"' in tag_script
    assert 'echo "${DOCKERHUB_IMAGE}:${VERSION}"' in tag_script

    release_script = (REPO_ROOT / "bin" / "release.sh").read_text()
    create_tag = '$GIT_BINARY push origin "refs/tags/${TAG}"'
    publish_pypi = "$UV_BINARY publish --trusted-publishing always"
    create_release = '$GH_BINARY release create "$TAG" --repo "$SLUG" --verify-tag'
    assert release_script.index(create_tag) < release_script.index(publish_pypi)
    assert release_script.index(publish_pypi) < release_script.index(create_release)
