"""Admission signals, not estimates of how much RAM an extractor will need."""

import math
import os
import time
from pathlib import Path


RESOURCE_RECHECK_SECONDS = 2.0
# Scheduling policy, not a minimum-RAM claim: stop increasing extraction
# load when all non-idle work loses at least one second out of ten to memory
# stalls. Require both recent and rolling pressure so transient reclaim does
# not indefinitely starve otherwise viable work on small hosts.
MEMORY_FULL_STALL_PERCENT = 10.0


class ResourceAdmission:
    def __init__(self):
        self._memory_stalls: dict[str, tuple[int, float]] = {}
        self._checked_at = float("-inf")
        self._reason: str | None = None

    @staticmethod
    def cgroup_paths() -> list[Path]:
        root = Path("/sys/fs/cgroup")
        paths = [root]
        try:
            for line in Path("/proc/self/cgroup").read_text().splitlines():
                if line.startswith("0::"):
                    current = root / line[3:].lstrip("/")
                    if current.is_dir() and current.is_relative_to(root):
                        paths = [current, *[parent for parent in current.parents if parent.is_relative_to(root)]]
                    break
        except OSError:
            pass
        return paths

    def snapshot_limit(self, configured: int) -> int:
        cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
        for path in self.cgroup_paths():
            try:
                quota, period = (path / "cpu.max").read_text().split()
                if quota != "max":
                    cpus = min(cpus, max(1, math.ceil(int(quota) / int(period))))
            except (OSError, ValueError, ZeroDivisionError):
                continue
        # CPU quota limits parallel admission, not forward progress. A host
        # with a fractional CPU must still be able to run one snapshot.
        return max(1, min(configured, cpus))

    def observe_memory_stalls(self, source: str, total: int, avg10: float, sampled_at: float) -> bool:
        previous = self._memory_stalls.get(source)
        self._memory_stalls[source] = (total, sampled_at)
        if previous is None:
            return avg10 >= MEMORY_FULL_STALL_PERCENT
        previous_total, previous_time = previous
        elapsed = sampled_at - previous_time
        if elapsed <= 0 or total < previous_total:
            return False
        stalled_percent = (total - previous_total) / (elapsed * 1_000_000) * 100
        return avg10 >= MEMORY_FULL_STALL_PERCENT and stalled_percent >= MEMORY_FULL_STALL_PERCENT

    def memory_pressure(self) -> str | None:
        now = time.monotonic()
        if now - self._checked_at < RESOURCE_RECHECK_SECONDS:
            return self._reason
        self._checked_at = now
        reasons = []
        cgroups = self.cgroup_paths()
        for path in cgroups:
            try:
                current = int((path / "memory.current").read_text())
                for name in ("memory.high", "memory.max"):
                    limit = (path / name).read_text().strip()
                    if limit != "max" and current >= int(limit):
                        reasons.append(f"{name} reached")
            except (OSError, ValueError):
                continue
        for path in [Path("/proc/pressure/memory"), *[p / "memory.pressure" for p in cgroups]]:
            try:
                full = next(line for line in path.read_text().splitlines() if line.startswith("full "))
                fields = dict(field.split("=", 1) for field in full.split()[1:])
                if self.observe_memory_stalls(str(path), int(fields["total"]), float(fields["avg10"]), now):
                    reasons.append("memory stalls")
            except (OSError, ValueError, KeyError, StopIteration):
                continue
        self._reason = ", ".join(dict.fromkeys(reasons)) or None
        return self._reason


resource_admission = ResourceAdmission()
