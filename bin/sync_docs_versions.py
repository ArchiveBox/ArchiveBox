#!/usr/bin/env python3
"""Keep one published docs version per minor, plus latest/main and dev.

Run with uv run bin/sync_docs_versions.py for a read-only plan. Pass --apply
with READTHEDOCS_TOKEN to reconcile. Retired versions are hidden, preserving
existing URLs. Missing builds must succeed before older entries are hidden.
"""

import argparse
import os
import subprocess
import sys

import requests
from packaging.version import InvalidVersion, Version

API = "https://app.readthedocs.org/api/v3/projects/archivebox/"
# Deployment maps these branch-backed versions to their release URL slugs manually.
# The hourly reconciler must never rename versions or rewrite release tags.
REPAIR_REFS = {
    "v0.7.4": "docs/restore-main-sphinx",
    "v0.8.6rc1": "docs/restore-08-sphinx",
    "v0.2.4": "docs/restore-02-sphinx",
    "v0.1.0": "docs/restore-01-sphinx",
    "v0.0.3": "docs/restore-00-sphinx",
}


def build_ready(version, build, expected_ref, expected_commit):
    """Only a successful current build from the intended Git source can replace docs."""
    source = version["identifier"] if version["slug"] == "latest" else version["verbose_name"]
    return bool(
        expected_commit
        and source == expected_ref
        and version["active"]
        and build
        and build["version"] == version["slug"]
        and build["state"]["code"] == "finished"
        and build["success"] is True
        and build["commit"] == expected_commit,
    )


def selected_tags(tags):
    releases = {}
    for tag in tags:
        if not tag.startswith("v"):
            continue
        try:
            version = Version(tag[1:])
        except InvalidVersion:
            continue
        releases.setdefault((version.major, version.minor), []).append((version, tag))
    minors = sorted(releases, reverse=True)
    selected = []
    for index, minor in enumerate(minors):
        if index < 2:
            candidates = [(version, tag) for version, tag in releases[minor] if version.pre and version.pre[0] == "rc"]
        else:
            candidates = [(version, tag) for version, tag in releases[minor] if not version.is_prerelease and not version.is_devrelease]
        if not candidates:
            raise ValueError(f"No {'RC' if index < 2 else 'stable'} release for minor {minor}")
        selected.append(max(candidates)[1])
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("READTHEDOCS_TOKEN")
    if args.apply and not token:
        parser.error("--apply requires READTHEDOCS_TOKEN")
    session = requests.Session()
    session.headers["User-Agent"] = "ArchiveBox-docs-version-policy"
    if token:
        session.headers["Authorization"] = f"Token {token}"

    def request(method, path, **kwargs):
        response = session.request(method, API + path, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    refs = subprocess.check_output(["git", "ls-remote", "--heads", "--tags", "origin"], text=True)
    remote_refs = {ref: commit for commit, ref in (line.split() for line in refs.splitlines())}
    tags = [ref.removeprefix("refs/tags/") for ref in remote_refs if ref.startswith("refs/tags/") and not ref.endswith("^{}")]
    expected_refs = {"latest": "main", "dev": "dev", **REPAIR_REFS}
    wanted = ["latest", "dev", *selected_tags(tags)]
    project = request("GET", "")
    page = request("GET", "versions/?limit=1000")
    versions = {version["slug"]: version for version in page["results"]}
    while page["next"]:
        response = session.get(page["next"], timeout=30)
        response.raise_for_status()
        page = response.json()
        versions.update((version["slug"], version) for version in page["results"])
    missing = set(wanted) - versions.keys()
    if missing:
        raise SystemExit(f"Read the Docs has not synchronized these tags: {sorted(missing)}")
    print("Desired picker:", ", ".join(wanted))
    print(f"latest currently tracks {project['default_branch']}; required branch: main")
    for slug in wanted:
        expected = expected_refs.get(slug, slug)
        source = versions[slug]["identifier"] if slug == "latest" else versions[slug]["verbose_name"]
        if source != expected:
            print(f"{slug}: source is {source}; requires staged deployment from {expected}")
    print("Current-build readiness is verified only with --apply (authenticated per-version API reads).")
    if not args.apply:
        return

    if project["default_branch"] != "main":
        subprocess.run(["git", "fetch", "--depth=1", "origin", "main"], check=True)
        configured = subprocess.run(["git", "cat-file", "-e", "FETCH_HEAD:.github/.readthedocs.yaml"], capture_output=True)
        if configured.returncode:
            raise SystemExit("main needs the docs build configuration PR before latest can safely track it")
        request("PATCH", "", json={"default_branch": "main"})
        request("POST", "versions/latest/builds/")

    pending = []
    for slug in wanted:
        version = versions[slug]
        expected = expected_refs.get(slug, slug)
        source = version["identifier"] if slug == "latest" else version["verbose_name"]
        if source != expected:
            # Refresh latest after changing the project's default branch.
            if slug == "latest":
                version = request("GET", "versions/latest/")
            else:
                pending.append(f"{slug} (deploy repair branch {expected})")
                continue
        is_branch = slug in expected_refs
        ref = f"refs/heads/{expected}" if is_branch else f"refs/tags/{expected}"
        commit = remote_refs.get(ref + "^{}", remote_refs.get(ref))
        if not commit:
            pending.append(f"{slug} (missing remote ref {expected})")
            continue
        if not version["active"]:
            request("PATCH", f"versions/{slug}/", json={"active": True, "hidden": True})
            # Activation starts a build; keep it out of the picker until verified.
            pending.append(f"{slug} (activated, awaiting build)")
            continue
        builds = request("GET", f"versions/{slug}/builds/?limit=1")["results"]
        if not build_ready(version, builds[0] if builds else None, expected, commit):
            pending.append(f"{slug} (newest build must succeed at {commit})")
    if pending:
        raise SystemExit("Keeping existing picker; awaiting: " + "; ".join(pending))
    for slug in wanted:
        if versions[slug]["hidden"]:
            request("PATCH", f"versions/{slug}/", json={"hidden": False})
    for slug, version in versions.items():
        if slug not in wanted and version["active"] and not version["hidden"]:
            request("PATCH", f"versions/{slug}/", json={"hidden": True})
            print("Hidden (URL preserved):", slug)
    if project["default_version"] != "latest":
        request("PATCH", "", json={"default_version": "latest"})
    print("Version visibility reconciled successfully")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as error:
        print(f"Read the Docs API request failed: {error}", file=sys.stderr)
        sys.exit(1)
