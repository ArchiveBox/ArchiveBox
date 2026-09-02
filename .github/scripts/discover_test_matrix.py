#!/usr/bin/env python3
"""Discover every ArchiveBox test file and expose it as one CI job."""

import json
from pathlib import Path


def main() -> None:
    root = Path.cwd().resolve()
    archivebox_tests = sorted((root / "archivebox/tests").glob("test_*.py"))

    if not archivebox_tests:
        raise SystemExit("No ArchiveBox tests discovered")

    matrix: list[dict[str, object]] = []
    for path in archivebox_tests:
        test_path = path.relative_to(root).as_posix()
        matrix.append(
            {
                "name": f"main/{path.stem}",
                "paths": [test_path],
                "paths_arg": test_path,
                "extra": (
                    "ldap"
                    if test_path.endswith("/test_auth_ldap.py")
                    else "allauth"
                    if test_path.endswith("/test_allauth_integration.py")
                    else ""
                ),
                "count": 1,
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
