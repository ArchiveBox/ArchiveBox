"""Admission signals, not estimates of how much RAM an extractor will need."""

import math
import os
import re
import stat
import sys
import time
from pathlib import Path

import psutil


RESOURCE_RECHECK_SECONDS = 2.0
# Scheduling policy, not a minimum-RAM claim: stop increasing extraction
# load when all non-idle work loses at least one second out of ten to memory
# stalls. Require both recent and rolling pressure so transient reclaim does
# not indefinitely starve otherwise viable work on small hosts.
MEMORY_FULL_STALL_PERCENT = 10.0
ZRAM_DEVICE_NAME = re.compile(r"zram\d+")


def zram_swap_identifiers(sys_block: Path = Path("/sys/block")) -> set[str]:
    """Return zram block names and major:minor IDs known to sysfs."""
    identifiers = set()
    for device in sys_block.glob("zram*"):
        if ZRAM_DEVICE_NAME.fullmatch(device.name):
            identifiers.add(device.name)
            try:
                identifiers.add((device / "dev").read_text().strip())
            except OSError:
                pass
    return identifiers


def swap_source_identifiers(filename: str) -> set[str]:
    """Identify a swap source by its visible name and, for block devices, ID."""
    identifiers = {Path(filename).name}
    try:
        source = os.stat(filename)
        if stat.S_ISBLK(source.st_mode):
            identifiers.add(f"{os.major(source.st_rdev)}:{os.minor(source.st_rdev)}")
    except OSError:
        pass
    return identifiers


def disk_backed_swap_free_bytes(swaps: str, zram_identifiers: set[str]) -> int:
    """Sum free active swap except zram, whose capacity is already backed by RAM."""
    lines = swaps.splitlines()
    free_kib = 0
    for line in lines[1:]:  # /proc/swaps starts with a column header
        fields = line.split()
        if len(fields) < 5:
            continue
        filename, _, size_kib, used_kib, _ = fields[:5]
        source_ids = swap_source_identifiers(filename)
        if source_ids & zram_identifiers or any(ZRAM_DEVICE_NAME.fullmatch(name) for name in source_ids):
            continue
        try:
            free_kib += max(0, int(size_kib) - int(used_kib))
        except ValueError:
            continue
    return free_kib * 1024


def host_swap_free_bytes(meminfo_swap_free: int) -> int:
    """Use only independently backed swap as extra capacity on Linux."""
    if not sys.platform.startswith("linux"):
        return psutil.swap_memory().free
    try:
        swaps = Path("/proc/swaps").read_text()
    except OSError:
        # If Linux swap sources cannot be classified, fail closed rather than
        # treating potentially RAM-backed zram capacity as extra headroom.
        return 0
    disk_free = disk_backed_swap_free_bytes(swaps, zram_swap_identifiers())
    return min(max(0, meminfo_swap_free), disk_free)


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
        # CPU quota bounds parallel work; measured memory admission is done
        # only after the first complete snapshot establishes its actual cost.
        return max(1, min(configured, cpus))

    def additional_snapshot_slots(self, configured: int, active: int, observed_cost: int | None) -> int:
        if not observed_cost:
            # Stage one complete real capture before spending memory on parallel
            # hook trees. A zero-cost/failed probe cannot justify fanout.
            return 1 if active == 0 and configured > 0 else 0
        headroom = self.memory_headroom()
        return self.slots_for_headroom(configured, active, observed_cost, headroom[1] if headroom else 0)

    @staticmethod
    def slots_for_headroom(configured: int, active: int, observed_cost: int, available: int) -> int:
        slots = max(0, configured - active)
        if observed_cost > 0:
            # Active captures can still grow to the measured peak. Reserve for
            # that growth before promising the remaining headroom to new work.
            unpromised = max(0, available - active * observed_cost)
            slots = min(slots, unpromised // observed_cost)
        return max(1, slots) if active == 0 and configured else slots

    def memory_headroom(self) -> tuple[int, int, int] | None:
        """Return workload RAM+swap usage, effective headroom, and host headroom."""
        try:
            meminfo = {
                name: int(value.split()[0]) * 1024
                for name, value in (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line)
            }
            host_swap_free = host_swap_free_bytes(meminfo.get("SwapFree", 0))
            host_available = meminfo["MemAvailable"] + host_swap_free
        except (OSError, ValueError, KeyError):
            host_swap_free = 0 if sys.platform.startswith("linux") else psutil.swap_memory().free
            host_available = psutil.virtual_memory().available + host_swap_free

        available = host_available
        used_bytes = None
        for path in self.cgroup_paths():
            try:
                memory_max = (path / "memory.max").read_text().strip()
                if memory_max == "max":
                    continue
                current = int((path / "memory.current").read_text())
                swap_max = (path / "memory.swap.max").read_text().strip()
                swap_current = int((path / "memory.swap.current").read_text())
                swap_room = host_swap_free if swap_max == "max" else min(host_swap_free, max(0, int(swap_max) - swap_current))
                available = min(available, max(0, int(memory_max) - current) + swap_room)
                if used_bytes is None:
                    used_bytes = current + swap_current
            except (OSError, ValueError, KeyError):
                continue
        if used_bytes is None:
            # Bare-metal and non-Linux installs have no finite cgroup. Count
            # the real runner process tree rather than the entire host.
            try:
                process = psutil.Process()
                processes = [process, *process.children(recursive=True)]
            except (psutil.Error, OSError):
                return None
            used_bytes = 0
            for child in processes:
                try:
                    used_bytes += child.memory_info().rss
                except (psutil.Error, OSError):
                    continue
        return used_bytes, available, host_available

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
