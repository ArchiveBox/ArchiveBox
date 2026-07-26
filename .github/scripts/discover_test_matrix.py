#!/usr/bin/env python3
"""Discover every ArchiveBox test file and pack it into one CI matrix."""

import json
from pathlib import Path

TARGET_SHARDS = 18

SLOW_TEST_WEIGHTS = {
    "test_cli_archiveresult.py": 200,
    "test_opencode_agent.py": 180,
    "test_cli_piping.py": 135,
    "test_api_v1_crawls_crawl_crawl_id.py": 130,
    "test_binary_service.py": 80,
    "test_api_v1_workflow_core_token_auth_side_effects.py": 55,
    "test_api_v1_cli_schedule.py": 50,
    "test_api_v1_cli_remove.py": 40,
    "test_api_v1_workflow_frozen_crawl_config_sources.py": 35,
    "test_cli_help.py": 35,
}


def test_weight(path: Path) -> int:
    return SLOW_TEST_WEIGHTS.get(path.name, 25)


def main() -> None:
    root = Path.cwd().resolve()
    archivebox_tests = sorted((root / "archivebox/tests").glob("test_*.py"))

    if not archivebox_tests:
        raise SystemExit("No ArchiveBox tests discovered")

    shard_count = min(TARGET_SHARDS, len(archivebox_tests))
    shards: list[list[Path]] = [[] for _ in range(shard_count)]
    shard_weights = [0 for _ in range(shard_count)]

    for path in sorted(archivebox_tests, key=lambda item: (-test_weight(item), item.as_posix())):
        shard_index = min(range(shard_count), key=lambda index: (shard_weights[index], index))
        shards[shard_index].append(path)
        shard_weights[shard_index] += test_weight(path)

    matrix: list[dict[str, object]] = []
    for index, shard in enumerate(shards, start=1):
        shard_paths = sorted(path.relative_to(root).as_posix() for path in shard)
        paths_arg = " ".join(shard_paths)
        matrix.append(
            {
                "name": f"main/shard-{index:02d}",
                "paths": shard_paths,
                "paths_arg": paths_arg,
                "extra": "ldap" if any(path.endswith("/test_auth_ldap.py") for path in shard_paths) else "",
                "count": len(shard_paths),
            },
        )

    discovered_paths = [path for entry in matrix for path in entry["paths"]]
    if len(discovered_paths) != len(set(discovered_paths)):
        raise SystemExit("Tests were not discovered exactly once")
    if sorted(discovered_paths) != [path.relative_to(root).as_posix() for path in archivebox_tests]:
        raise SystemExit("Discovered test shard coverage does not match test files")

    print(f"Discovered {len(discovered_paths)} test files exactly once across {len(matrix)} balanced shards")
    print(json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
