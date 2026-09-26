#!/usr/bin/env python3
"""Fail closed unless both live test servers accepted this exact release source.

CI tests alone do not establish that the automatically deployed image works on
our real servers. In particular, a stable PyPI upload must not overtake a stale
Docker :dev deployment. Only our staging workflow can provide this evidence;
own-version changes are normalized by the shared fingerprint helper, while
dependency pins, application code, and CI changes must still match exactly.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def tested_abx_dl_digest(artifact_dir, expected_sha):
    artifact_dir = Path(artifact_dir)
    source_ref = (artifact_dir / "source-ref").read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha) or source_ref != expected_sha:
        raise SystemExit("Stable publication blocked: tested Docker artifacts belong to a different source commit.")

    image_refs = []
    for platform in ("linux-amd64", "linux-arm64"):
        path = artifact_dir / f"abx-dl-image-digest-{platform}"
        image_ref = path.read_text().strip()
        match = re.search(r"@(?P<digest>sha256:[0-9a-f]{64})$", image_ref)
        if not match:
            raise SystemExit(f"Stable publication blocked: {path.name} is not pinned to a sha256 digest.")
        image_refs.append(match.group("digest"))
    if image_refs[0] != image_refs[1]:
        raise SystemExit("Stable publication blocked: amd64 and arm64 Docker builds used different abx-dl images.")
    return image_refs[0]


def github(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["RELEASE_SHA"]
    fingerprint = subprocess.check_output(
        [sys.executable, str(Path(__file__).with_name("release-source-fingerprint.py")), sha],
        text=True,
    ).strip()
    expected_abx_dl_digest = tested_abx_dl_digest(os.environ["STAGING_DOCKER_ARTIFACT_DIR"], sha)
    for environment in ("cabbage", "digestbox"):
        deployments = github(f"repos/{repo}/deployments?environment={environment}&per_page=100")
        accepted = False
        for deployment in deployments:
            payload = deployment.get("payload") or {}
            if not isinstance(payload, dict) or payload.get("source_fingerprint") != fingerprint:
                continue
            if deployment["creator"]["login"] != "github-actions[bot]" or payload.get("acceptance_version") != 1:
                continue
            statuses = github(f"repos/{repo}/deployments/{deployment['id']}/statuses?per_page=1")
            if not statuses or statuses[0]["state"] != "success":
                continue
            deployed_sha = deployment["sha"]
            if not re.fullmatch(r"[0-9a-f]{40}", deployed_sha):
                continue
            inspection = payload.get("inspection") or {}
            if inspection.get("revision") != deployed_sha or inspection.get("health") != "healthy":
                continue
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", inspection.get("image_id", "")):
                continue
            abx_dl_image = inspection.get("abx_dl_image", "")
            abx_dl_match = re.search(r"@(?P<digest>sha256:[0-9a-f]{64})$", abx_dl_image) if isinstance(abx_dl_image, str) else None
            if not abx_dl_match or abx_dl_match.group("digest") != expected_abx_dl_digest:
                continue
            deployed_fingerprint = subprocess.check_output(
                [sys.executable, str(Path(__file__).with_name("release-source-fingerprint.py")), deployed_sha],
                text=True,
            ).strip()
            if deployed_fingerprint != fingerprint:
                continue
            run_id = str(payload.get("run_id", ""))
            if not run_id.isdecimal():
                continue
            run = github(f"repos/{repo}/actions/runs/{run_id}")
            if (
                run["path"] != ".github/workflows/staging-acceptance.yml"
                or run["event"] != "workflow_run"
                or run["status"] != "completed"
                or run["conclusion"] != "success"
            ):
                continue
            print(f"{environment}: accepted {deployment['sha']} with abx-dl {expected_abx_dl_digest} ({run['html_url']})")
            accepted = True
            break
        if not accepted:
            raise SystemExit(f"Stable publication blocked: {environment} has not accepted source fingerprint {fingerprint}.")


if __name__ == "__main__":
    main()
