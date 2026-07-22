#!/usr/bin/env python3
"""Build deterministic GitHub Actions matrices from every discovered test file."""

import argparse
import json
import re
from pathlib import Path


CHROMIUM_PATTERN = re.compile(
    rb"chrom|archivewebpage|PLUGINS=.*title|--plugins=.*title|SAVE_TITLE.*[Tt]rue",
    re.IGNORECASE,
)
SONIC_PATTERN = re.compile(
    rb"""shutil\.which\(["']sonic|SEARCH_BACKEND_ENGINE=.*sonic|worker_sonic""",
    re.IGNORECASE,
)


def contains(pattern: re.Pattern[bytes], paths: list[Path]) -> bool:
    return any(pattern.search(path.read_bytes()) for path in paths)


def archivebox_matrix(root: Path) -> list[dict[str, object]]:
    tests = sorted((root / "archivebox/tests").glob("test_*.py"))
    if not tests:
        raise SystemExit("No ArchiveBox tests discovered")

    shard_count = min(16, len(tests))
    matrix = []
    assigned: list[Path] = []
    for shard in range(shard_count):
        shard_tests = tests[shard::shard_count]
        assigned.extend(shard_tests)
        matrix.append(
            {
                "name": f"main/shard-{shard + 1}",
                "paths": [path.relative_to(root).as_posix() for path in shard_tests],
                "needs_chromium": contains(CHROMIUM_PATTERN, shard_tests),
                "needs_sonic": contains(SONIC_PATTERN, shard_tests),
            },
        )

    if sorted(assigned) != tests or len(assigned) != len(set(assigned)):
        raise SystemExit("ArchiveBox tests were not assigned exactly once")
    print(f"Assigned {len(tests)} test files exactly once across {shard_count} shards")
    return matrix


def plugin_matrix(root: Path) -> list[dict[str, object]]:
    plugins_root = root / "abx-plugins/abx_plugins/plugins"
    suite_dirs = sorted(path for path in plugins_root.glob("*/tests") if path.is_dir())
    root_tests = sorted((root / "abx-plugins/tests").glob("test_*.py"))
    if not suite_dirs or not root_tests:
        raise SystemExit("Plugin suites or root tests were not discovered")

    matrix: list[dict[str, object]] = []
    expected = list(root_tests)
    for suite_dir in suite_dirs:
        suite_tests = sorted(suite_dir.rglob("test_*.py"))
        if not suite_tests:
            raise SystemExit(f"No tests found in {suite_dir}")
        expected.extend(suite_tests)
        plugin = suite_dir.parent.name
        matrix.append(
            {
                "plugin": plugin,
                "name": f"plugin/{plugin}",
                "test_path": suite_dir.relative_to(root).as_posix(),
                "config_path": (suite_dir.parent / "config.json").relative_to(root).as_posix(),
                "needs_chromium": contains(re.compile(rb"chrom", re.IGNORECASE), suite_tests),
                "needs_sonic": plugin == "search_backend_sonic",
            },
        )

    matrix.append(
        {
            "plugin": "root",
            "name": "plugin/root",
            "test_path": "abx-plugins/tests",
            "config_path": "abx-plugins/abx_plugins/plugins/base/config.json",
            "needs_chromium": contains(re.compile(rb"chrom|archivewebpage", re.IGNORECASE), root_tests),
            "needs_sonic": False,
        },
    )

    assigned = []
    for entry in matrix:
        assigned.extend(sorted((root / str(entry["test_path"])).rglob("test_*.py")))
    if sorted(assigned) != sorted(expected) or len(assigned) != len(set(assigned)):
        raise SystemExit("Plugin tests were not assigned exactly once")
    print(
        f"Assigned {len(suite_dirs)} plugin suites and {len(root_tests)} root test files exactly once",
    )
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=("archivebox", "plugins"))
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.workspace.resolve()
    matrix = archivebox_matrix(root) if args.scope == "archivebox" else plugin_matrix(root)
    print(json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
