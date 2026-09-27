#!/usr/bin/env python3
"""Discover every test once, batching measured short files."""

import json
import os
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    archivebox_tests = sorted((root / "archivebox/tests").glob("test_*.py"))

    if not archivebox_tests:
        raise SystemExit("No ArchiveBox tests discovered")

    # These are observed whole-job seconds, including setup. Unknown/long files,
    # optional dependencies and hosted-only requirements keep independent jobs.
    durations = json.loads((root / ".github/test-durations.json").read_text())["seconds"]
    hosted = {path for path in archivebox_tests if "# ci-runner: hosted" in path.read_text().splitlines()[:5]}
    requested = os.environ.get("TEST_FILE", "")
    batches: list[list[str]] = []
    batch: list[str] = []
    batch_seconds = 0
    for path in archivebox_tests:
        test_path = path.relative_to(root).as_posix()
        duration = durations.get(test_path, 60)
        if duration >= 60 or path in hosted or path.stem == "test_auth_ldap" or test_path == requested:
            batches.append([test_path])
            continue
        if batch and (len(batch) == 8 or batch_seconds + duration > 180):
            batches.append(batch)
            batch = []
            batch_seconds = 0
        batch.append(test_path)
        batch_seconds += duration
    if batch:
        batches.append(batch)

    matrix: list[dict[str, object]] = []
    for paths in batches:
        matrix.append(
            {
                "name": f"main/{Path(paths[0]).stem}" if len(paths) == 1 else f"batch/{Path(paths[0]).stem}",
                "paths": paths,
                "paths_arg": " ".join(paths),
                "extra": "ldap" if paths == ["archivebox/tests/test_auth_ldap.py"] else "",
                "count": len(paths),
                "ugnas": False,
            },
        )

    # Ordinary Linux tests can use either pool. Only genuine hosted-only
    # requirements need a file header; filenames never enter runner policy.
    # Keep a bounded NAS share so hosted capacity continues working in parallel.
    capacity = int(os.environ.get("UGNAS_CI_MAX_JOBS", "3"))
    # Start long jobs first in both pools instead of leaving several minutes of
    # work behind every short job in an alphabetically ordered hosted queue.
    matrix.sort(key=lambda item: sum(durations.get(path, 60) for path in item["paths"]), reverse=True)
    eligible = [item for item in matrix if not any(root / path in hosted for path in item["paths"])]
    for item in eligible[:capacity]:
        item["ugnas"] = True

    discovered_paths = [path for entry in matrix for path in entry["paths"]]
    if len(discovered_paths) != len(set(discovered_paths)):
        raise SystemExit("Tests were not discovered exactly once")
    if sorted(discovered_paths) != [path.relative_to(root).as_posix() for path in archivebox_tests]:
        raise SystemExit("Discovered test shard coverage does not match test files")

    print(f"Discovered {len(discovered_paths)} test files exactly once across {len(matrix)} jobs")
    print(json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
