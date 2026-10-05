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

    # These are observed per-file pytest seconds, including fixture/startup
    # time. Shared job setup is paid once per batch. Unknown/long files, optional
    # dependencies and hosted-only requirements keep independent jobs.
    durations = json.loads((root / ".github/test-durations.json").read_text())["seconds"]
    hosted = {path for path in archivebox_tests if "# ci-runner: hosted" in path.read_text().splitlines()[:5]}
    requested = os.environ.get("TEST_FILE", "")
    batches: list[list[str]] = []
    batch: list[str] = []
    batch_seconds = 0
    for path in archivebox_tests:
        test_path = path.relative_to(root).as_posix()
        duration = durations.get(test_path, 60)
        if test_path not in durations or duration >= 90 or path in hosted or path.stem == "test_auth_ldap" or test_path == requested:
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
    # This is queued work, not a worker count: several waves keep the capped
    # runners occupied while hosted jobs run in parallel.
    nas_job_limit = int(os.environ.get("UGNAS_CI_MAX_JOBS", "3"))
    # Keep long jobs early in the hosted queue. Giving the longest jobs to the
    # CPU-capped NAS instead created a tail after hosted work had finished; use
    # its extra slots for a bounded share of shorter work without filename rules.
    matrix.sort(key=lambda item: sum(durations.get(path, 60) for path in item["paths"]), reverse=True)
    eligible = [item for item in reversed(matrix) if not any(root / path in hosted for path in item["paths"])]
    for item in eligible[:nas_job_limit]:
        item["ugnas"] = True

    discovered_paths = [path for entry in matrix for path in entry["paths"]]
    if len(discovered_paths) != len(set(discovered_paths)):
        raise SystemExit("Tests were not discovered exactly once")
    if sorted(discovered_paths) != [path.relative_to(root).as_posix() for path in archivebox_tests]:
        raise SystemExit("Discovered test shard coverage does not match test files")

    print(
        f"Discovered {len(discovered_paths)} test files exactly once across {len(matrix)} jobs; "
        f"{sum(item['ugnas'] for item in matrix)} selected for ugNAS, subject to the availability check",
    )
    print(json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
