#!/usr/bin/env python3
"""Discover every test once, batching measured short files on hosted runners."""

import json
import os
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    archivebox_tests = sorted((root / "archivebox/tests").glob("test_*.py"))

    if not archivebox_tests:
        raise SystemExit("No ArchiveBox tests discovered")

    # These are observed whole-job seconds, including setup. Unknown/long files,
    # optional dependencies and existing NAS assignments keep independent jobs.
    durations = json.loads((root / ".github/test-durations.json").read_text())["seconds"]
    nas_tests = set(json.loads(os.environ.get("UGNAS_CI_TESTS", "[]")))
    requested = os.environ.get("TEST_FILE", "")
    batches: list[list[str]] = []
    batch: list[str] = []
    batch_seconds = 0
    for path in archivebox_tests:
        test_path = path.relative_to(root).as_posix()
        duration = durations.get(test_path, 60)
        if duration >= 60 or f"main/{path.stem}" in nas_tests or path.stem == "test_auth_ldap" or test_path == requested:
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
            },
        )

    discovered_paths = [path for entry in matrix for path in entry["paths"]]
    if len(discovered_paths) != len(set(discovered_paths)):
        raise SystemExit("Tests were not discovered exactly once")
    if sorted(discovered_paths) != [path.relative_to(root).as_posix() for path in archivebox_tests]:
        raise SystemExit("Discovered test shard coverage does not match test files")

    print(f"Discovered {len(discovered_paths)} test files exactly once across {len(matrix)} jobs")
    print(json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
