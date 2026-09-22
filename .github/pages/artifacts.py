"""Common screenshot artifact transport; coverage checks belong to each app."""

import json
import subprocess
from pathlib import PurePosixPath
from urllib.request import urlopen


def api(repo, path):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/{path}"]))


def trusted(run, repo, workflow, branch, successful=True):
    return (
        (run.get("head_repository") or {}).get("full_name", "").lower() == repo.lower()
        and run["head_branch"] == branch
        and run["event"] in ("push", "workflow_dispatch")
        and run["path"] == f".github/workflows/{workflow}"
        and (not successful or run["conclusion"] == "success")
    )


def runs(repo, workflow, branch, successful=True, artifact_names=("site-screenshots",)):
    # Ask for capture artifacts directly instead of checking every historical
    # workflow run (most app runs never produce a complete screenshot set).
    # Artifact creation time also includes fresh captures from old rerun jobs.
    candidates = []
    for name in artifact_names:
        rows = subprocess.check_output(
            [
                "gh",
                "api",
                f"repos/{repo}/actions/artifacts?name={name}&per_page=100",
                "--paginate",
                "--jq",
                ".artifacts[] | select(.expired == false) | @json",
            ],
            text=True,
        )
        candidates.extend(json.loads(row) for row in rows.splitlines())
    seen = set()
    for artifact in sorted(candidates, key=lambda item: item["created_at"], reverse=True):
        source = artifact.get("workflow_run") or {}
        run_id = source.get("id")
        if (
            artifact["name"] not in artifact_names
            or not run_id
            or run_id in seen
            or source.get("head_branch") != branch
            or source.get("head_repository_id") != source.get("repository_id")
        ):
            continue
        seen.add(run_id)
        run = api(repo, f"actions/runs/{run_id}")
        if trusted(run, repo, workflow, branch, successful):
            yield run


def names(repo, run):
    rows = subprocess.check_output(
        [
            "gh",
            "api",
            f"repos/{repo}/actions/runs/{run['id']}/artifacts?per_page=100",
            "--paginate",
            "--jq",
            ".artifacts[] | @json",
        ],
        text=True,
    )
    return {artifact["name"] for row in rows.splitlines() if not (artifact := json.loads(row))["expired"]}


def download(repo, run, name, destination):
    subprocess.run(
        [
            "gh",
            "run",
            "download",
            str(run["id"]),
            "--repo",
            repo,
            "--name",
            name,
            "--dir",
            str(destination),
        ],
        check=True,
    )


def relative_path(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or any(c in name for c in ":\\?#%"):
        raise ValueError(f"Unsafe screenshot path: {name}")
    return path


def fetch(base, name):
    relative_path(name)
    with urlopen(base + name, timeout=60) as response:
        return response.read()
