#!/usr/bin/env python3
"""Discover every ArchiveBox test file for one CI matrix."""

import json
from pathlib import Path


def main() -> None:
    root = Path.cwd().resolve()
    archivebox_tests = sorted((root / "archivebox/tests").glob("test_*.py"))

    if not archivebox_tests:
        raise SystemExit("No ArchiveBox tests discovered")

    matrix: list[dict[str, object]] = []
    for path in archivebox_tests:
        matrix.append(
            {
                "name": f"main/{path.stem.removeprefix('test_')}",
                "path": path.relative_to(root).as_posix(),
                "extra": "ldap" if path.name == "test_auth_ldap.py" else "",
            },
        )

    discovered_paths = [str(entry["path"]) for entry in matrix]
    if len(discovered_paths) != len(set(discovered_paths)):
        raise SystemExit("Tests were not discovered exactly once")

    print(f"Discovered {len(matrix)} test files exactly once")
    print(json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
