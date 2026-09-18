#!/usr/bin/env python3
"""Compare tracked text lines with a fixed git revision, excluding old/ and docs/.

Usage: uv run bin/measure_source.py <baseline-revision>
Counts real source files once, including new untracked files, but not symlinks,
binaries, ignored build artifacts, old/, or docs/. Documentation cleanup contributes
nothing to the measured reduction.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


def category(path: str) -> str:
    if path.startswith("archivebox/tests/"):
        return "tests"
    if path.startswith("archivebox/"):
        return "production"
    return "tooling_and_other"


def count(path: str, content: bytes, totals: Counter) -> None:
    if not path.startswith(("old/", "docs/")) and b"\0" not in content:
        totals[category(path)] += len(content.splitlines())


def baseline_lines(revision: str) -> Counter:
    entries = subprocess.check_output(["git", "ls-tree", "-rz", revision]).split(b"\0")
    totals = Counter()
    objects = []
    for entry in filter(None, entries):
        metadata, path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        if kind == b"blob" and mode != b"120000" and not path.startswith((b"old/", b"docs/")):
            objects.append((oid, path.decode()))
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        input=b"\n".join(oid for oid, _ in objects) + b"\n",
        capture_output=True,
        check=True,
    ).stdout
    offset = 0
    for _, path in objects:
        end = result.index(b"\n", offset)
        size = int(result[offset:end].split()[-1])
        count(path, result[end + 1 : end + 1 + size], totals)
        offset = end + size + 2
    return totals


def working_lines() -> Counter:
    paths = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]).split(b"\0")
    totals = Counter()
    for raw in set(filter(None, paths)):
        path = Path(raw.decode())
        if path.is_file() and not path.is_symlink():
            count(path.as_posix(), path.read_bytes(), totals)
    return totals


if __name__ == "__main__":
    baseline = baseline_lines(sys.argv[1])
    current = working_lines()
    rows = {}
    for name in sorted(baseline.keys() | current.keys()) + ["total"]:
        before = sum(baseline.values()) if name == "total" else baseline[name]
        after = sum(current.values()) if name == "total" else current[name]
        rows[name] = {
            "before": before,
            "after": after,
            "removed": before - after,
            "reduction_pct": round(100 * (before - after) / before, 2),
        }
    print(json.dumps(rows, indent=2))
