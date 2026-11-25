#!/usr/bin/env python3
"""Discover every test once, batching measured files within a bounded budget."""

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
    # dependencies and hosted-only requirements keep independent jobs. Known
    # medium files share the same 180-second budget: a 60-second file need not
    # pay a fresh runner queue, checkout, dependency install and worker startup.
    durations = json.loads((root / ".github/test-durations.json").read_text())["seconds"]
    environments = {
        path: line.removeprefix("# ci-environment: ").strip()
        for path in archivebox_tests
        for line in path.read_text().splitlines()[:5]
        if line.startswith("# ci-environment: ")
    }
    if set(environments.values()) - {"provider-capture", "live-provider"}:
        raise SystemExit("Unknown ci-environment requirement")
    hosted = {path for path in archivebox_tests if "# ci-runner: hosted" in path.read_text().splitlines()[:5]}
    max_workers = {
        path: int(line.removeprefix("# ci-workers: ").strip())
        for path in archivebox_tests
        for line in path.read_text().splitlines()[:5]
        if line.startswith("# ci-workers: ")
    }
    if any(limit < 1 for limit in max_workers.values()):
        raise SystemExit("ci-workers must be positive")
    requested = os.environ.get("TEST_FILE", "")
    batches: list[list[str]] = []
    compatible: list[tuple[int, str]] = []
    for path in archivebox_tests:
        if path in environments:
            continue
        test_path = path.relative_to(root).as_posix()
        duration = durations.get(test_path, 60)
        if (
            test_path not in durations
            or duration >= 180
            or path in hosted
            or path in max_workers
            or path.stem in {"test_auth_ldap", "test_postgres_backend"}
            or "test_allauth_" in test_path
            or test_path == requested
        ):
            batches.append([test_path])
            continue
        compatible.append((duration, test_path))
    # Fit shorter measured files into gaps instead of paying fresh runner setup.
    measured_batches: list[tuple[list[str], int]] = []
    for duration, test_path in sorted(compatible, key=lambda item: (-item[0], item[1])):
        for index, (paths, seconds) in enumerate(measured_batches):
            if len(paths) < 8 and seconds + duration <= 180:
                paths.append(test_path)
                measured_batches[index] = paths, seconds + duration
                break
        else:
            measured_batches.append(([test_path], duration))
    batches.extend(sorted(paths) for paths, _ in measured_batches)

    matrix: list[dict[str, object]] = []
    for paths in batches:
        matrix.append(
            {
                "name": f"main/{Path(paths[0]).stem}" if len(paths) == 1 else f"batch/{Path(paths[0]).stem}",
                "paths": paths,
                "paths_arg": " ".join(paths),
                "extra": "saml"
                if any("test_allauth_" in path for path in paths)
                else "ldap"
                if paths == ["archivebox/tests/test_auth_ldap.py"]
                else "",
                "count": len(paths),
                "ugnas": False,
                "environment": "",
                "max_workers": min((max_workers[root / path] for path in paths if root / path in max_workers), default=0),
            },
        )
    for path, environment in environments.items():
        test_path = path.relative_to(root).as_posix()
        matrix.append(
            {
                "name": f"{environment}/{path.stem}",
                "paths": [test_path],
                "paths_arg": test_path,
                "extra": "",
                "count": 1,
                "ugnas": False,
                "environment": environment,
                "max_workers": max_workers.get(path, 0),
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
    eligible = [item for item in reversed(matrix) if not item["environment"] and not any(root / path in hosted for path in item["paths"])]
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
