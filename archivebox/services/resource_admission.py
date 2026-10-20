"""Measured resource pressure and memory headroom for capture admission."""

import math
import logging
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
IO_FULL_STALL_PERCENT = 10.0
# CPU has no system-wide "full" signal: use runnable work waiting for CPU.
# Ordinary runnable competition is expected; defer new work when it occupies
# at least half of both the recent interval and the rolling ten-second window.
CPU_SOME_STALL_PERCENT = 50.0
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
        self._stalls: dict[str, tuple[int, float]] = {}
        self._cpu_throttled: dict[str, int] = {}
        self._checked_at = float("-inf")
        self._reason: str | None = None
        self.observed_snapshot_cost: int | None = None
        self._concurrency = 1
        self._last_growth = float("-inf")

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
        return max(1, min(configured or cpus, cpus))

    def concurrency_limit(self, ceiling: int, *, pressure: bool, now: float) -> int:
        if pressure:
            self._concurrency = max(1, self._concurrency // 2)
            self._last_growth = now
        elif now - self._last_growth >= 10:
            self._concurrency = min(ceiling, self._concurrency + 1)
            self._last_growth = now
        return min(ceiling, self._concurrency)

    def additional_snapshot_slots(self, configured: int, active: int, observed_cost: int | None, *, crawl_id: str | None = None) -> int:
        pressure = self.resource_pressure()
        headroom = self.memory_headroom()
        if pressure or headroom <= 0:
            self.concurrency_limit(configured, pressure=True, now=time.monotonic())
            # Active captures also reset recovery; idle-only runner logging
            # otherwise hides the measured reason for later serial admission.
            logging.getLogger(__name__).warning(
                "Capture admission deferred for crawl %s: %s (active=%s slots=0 adaptive=%s)",
                crawl_id,
                pressure or f"memory headroom {headroom} bytes",
                active,
                self._concurrency,
            )
            return 0
        if not observed_cost:
            # Stage one complete real capture before spending memory on parallel
            # hook trees. Even this warmup must wait for resource pressure to clear.
            return self.slots_for_headroom(configured, active, observed_cost, headroom)
        previous_limit = self._concurrency
        ceiling = self.concurrency_limit(configured, pressure=False, now=time.monotonic())
        slots = self.slots_for_headroom(ceiling, active, observed_cost, headroom)
        if ceiling != previous_limit or slots < max(0, configured - active):
            logging.getLogger(__name__).info(
                "Snapshot admission decision: configured=%s adaptive=%s active=%s slots=%s observed_cost=%s available=%s pressure=%s",
                configured,
                ceiling,
                active,
                slots,
                observed_cost,
                headroom,
                pressure or "none",
            )
        return slots

    @staticmethod
    def slots_for_headroom(configured: int, active: int, observed_cost: int | None, available: int) -> int:
        if not observed_cost:
            return int(active == 0 and configured > 0 and available > 0)
        slots = max(0, configured - active)
        if observed_cost > 0:
            # Active captures can still grow to the measured peak. Reserve for
            # that growth before promising the remaining headroom to new work.
            unpromised = max(0, available - active * observed_cost)
            slots = min(slots, unpromised // observed_cost)
        return slots

    def memory_headroom(self) -> int:
        """Return effective available RAM plus independently backed swap."""
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
        for path in self.cgroup_paths():
            try:
                memory_max = (path / "memory.max").read_text().strip()
                if memory_max == "max":
                    continue
                current = int((path / "memory.current").read_text())
                # memory.current includes the page cache of every file a
                # capture writes (screenshots, WACZ, responses). The kernel
                # reclaims it under pressure, so counting it made each capture
                # look like ~2.8 GB and serialized a 16 GB host to one snapshot.
                stat = dict(line.split() for line in (path / "memory.stat").read_text().splitlines())
                current = max(0, current - int(stat.get("active_file", 0)) - int(stat.get("inactive_file", 0)))
                swap_max = (path / "memory.swap.max").read_text().strip()
                swap_current = int((path / "memory.swap.current").read_text())
                swap_room = host_swap_free if swap_max == "max" else min(host_swap_free, max(0, int(swap_max) - swap_current))
                available = min(available, max(0, int(memory_max) - current) + swap_room)
            except (OSError, ValueError, KeyError):
                continue
        return available

    def process_tree_memory(self) -> int | None:
        """Measure RAM and swap attributable to this runner and its children."""
        # Learn only this runner's process tree. Sibling web/importer processes
        # consume shared headroom, but their growth is not a capture's cost.
        try:
            process = psutil.Process()
            processes = [process, *process.children(recursive=True)]
        except (psutil.Error, OSError):
            return None
        used_bytes = 0
        for child in processes:
            try:
                if sys.platform.startswith("linux"):
                    try:
                        memory = child.memory_full_info()
                        # Chrome's processes share substantial resident
                        # memory. RSS charges those pages once per process
                        # and can falsely serialize captures on an idle host.
                        used_bytes += memory.pss + memory.swap
                        continue
                    except psutil.AccessDenied:
                        # Restricted /proc access still gets conservative
                        # accounting through the available RSS measurement.
                        pass
                used_bytes += child.memory_info().rss
            except (psutil.Error, OSError):
                continue
        return used_bytes

    def observe_stalls(self, source: str, total: int, avg10: float, sampled_at: float, threshold: float) -> bool:
        previous = self._stalls.get(source)
        self._stalls[source] = (total, sampled_at)
        if previous is None:
            return avg10 >= threshold
        previous_total, previous_time = previous
        elapsed = sampled_at - previous_time
        if elapsed <= 0 or total < previous_total:
            return False
        stalled_percent = (total - previous_total) / (elapsed * 1_000_000) * 100
        return avg10 >= threshold and stalled_percent >= threshold

    def observe_cpu_throttling(self, source: str, total: int) -> bool:
        previous = self._cpu_throttled.get(source)
        self._cpu_throttled[source] = total
        # Counters are cumulative: historical throttling or a recreated cgroup
        # must not indefinitely prevent new captures.
        return previous is not None and total > previous

    def resource_pressure(self, *, required_memory: int | None = None) -> str | None:
        # Check capacity on every admission, independently of cached PSI. An
        # idle runner still needs room for its last measured capture; allowing
        # one unconditionally can restart work into an already exhausted host.
        if required_memory is not None:
            available = self.memory_headroom()
            if available <= 0 or available < required_memory:
                return f"memory headroom {available} bytes below capture requirement {required_memory} bytes"
        now = time.monotonic()
        if now - self._checked_at < RESOURCE_RECHECK_SECONDS:
            return self._reason
        self._checked_at = now
        reasons = []
        cgroups = self.cgroup_paths()
        for path in cgroups:
            try:
                cpu_stat = dict(line.split() for line in (path / "cpu.stat").read_text().splitlines())
                # PSI measures waiting, not remaining CPU quota. One runnable
                # task can exhaust a fractional quota with almost no PSI.
                if self.observe_cpu_throttling(str(path), int(cpu_stat["nr_throttled"])):
                    reasons.append("cpu quota throttling")
            except (OSError, ValueError, KeyError):
                pass
            try:
                current = int((path / "memory.current").read_text())
                for name in ("memory.high", "memory.max"):
                    limit = (path / name).read_text().strip()
                    if limit != "max" and current >= int(limit):
                        reasons.append(f"{name} reached")
            except (OSError, ValueError):
                continue
        for resource, signal, threshold in (
            ("memory", "full", MEMORY_FULL_STALL_PERCENT),
            ("cpu", "some", CPU_SOME_STALL_PERCENT),
            ("io", "full", IO_FULL_STALL_PERCENT),
        ):
            host_pressure = Path(f"/proc/pressure/{resource}")
            scoped_pressure_available = False
            for path in [*[p / f"{resource}.pressure" for p in cgroups], host_pressure]:
                # Other containers or disks can stall without delaying this
                # cgroup. Host memory pressure remains shared physical pressure.
                if path == host_pressure and resource != "memory" and scoped_pressure_available:
                    continue
                try:
                    line = next(line for line in path.read_text().splitlines() if line.startswith(f"{signal} "))
                    fields = dict(field.split("=", 1) for field in line.split()[1:])
                    total, avg10 = int(fields["total"]), float(fields["avg10"])
                    scoped_pressure_available |= path != host_pressure
                    if self.observe_stalls(str(path), total, avg10, now, threshold):
                        reasons.append(f"{resource} stalls")
                except (OSError, ValueError, KeyError, StopIteration):
                    continue
        self._reason = ", ".join(dict.fromkeys(reasons)) or None
        return self._reason


resource_admission = ResourceAdmission()
