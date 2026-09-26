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


def github(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["RELEASE_SHA"]
    fingerprint = subprocess.check_output(
        [sys.executable, str(Path(__file__).with_name("release-source-fingerprint.py")), sha],
        text=True,
    ).strip()
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
            print(f"{environment}: accepted {deployment['sha']} ({run['html_url']})")
            accepted = True
            break
        if not accepted:
            raise SystemExit(f"Stable publication blocked: {environment} has not accepted source fingerprint {fingerprint}.")


if __name__ == "__main__":
    main()
