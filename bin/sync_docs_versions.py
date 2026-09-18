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

API = "https://readthedocs.org/api/v3/projects/archivebox/"


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

    refs = subprocess.check_output(["git", "ls-remote", "--tags", "origin"], text=True)
    tags = [line.split("refs/tags/", 1)[1] for line in refs.splitlines() if not line.endswith("^{}")]
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
    pending = [slug for slug in wanted if not versions[slug]["built"] or not versions[slug]["active"]]
    print("Awaiting successful builds:", ", ".join(pending) or "none")
    if not args.apply:
        return

    if project["default_branch"] != "main":
        subprocess.run(["git", "fetch", "--depth=1", "origin", "main"], check=True)
        configured = subprocess.run(["git", "cat-file", "-e", "FETCH_HEAD:.github/.readthedocs.yaml"], capture_output=True)
        if configured.returncode:
            raise SystemExit("main needs the docs build configuration PR before latest can safely track it")
        request("PATCH", "", json={"default_branch": "main"})
        request("POST", "versions/latest/builds/")
        pending.append("latest")

    for slug in wanted:
        version = versions[slug]
        if not version["active"] or version["hidden"]:
            request("PATCH", f"versions/{slug}/", json={"active": True, "hidden": False})
            # Activating a version triggers its first build automatically.
    latest_builds = request("GET", "builds/?version__slug=latest&limit=1")["results"]
    main_ref = subprocess.check_output(["git", "ls-remote", "origin", "refs/heads/main"], text=True).split()[0]
    if not latest_builds or not latest_builds[0]["success"] or latest_builds[0]["commit"] != main_ref:
        pending.append("latest")
    if pending:
        raise SystemExit("Desired versions are building or need historical build repair; keeping the existing picker until they succeed")
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
