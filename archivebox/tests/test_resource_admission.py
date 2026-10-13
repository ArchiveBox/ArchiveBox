import json
import os
import subprocess
import sys

from archivebox.services.resource_admission import ResourceAdmission, disk_backed_swap_free_bytes


def test_cpu_admission_respects_process_affinity():
    admission = ResourceAdmission()
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    assert 1 <= admission.snapshot_limit(100000) <= available
    assert admission.snapshot_limit(1) == 1


def test_snapshot_admission_stages_first_capture_then_uses_measured_headroom():
    admission = ResourceAdmission()
    assert admission.additional_snapshot_slots(3, active=0, observed_cost=None) == 1
    assert admission.additional_snapshot_slots(3, active=1, observed_cost=None) == 0
    # One observed peak costs 500 MB; only measured space is reserved for
    # each additional in-flight snapshot, with no fixed minimum RAM.
    assert admission.slots_for_headroom(3, active=0, observed_cost=500_000_000, available=1_100_000_000) == 2
    assert admission.slots_for_headroom(3, active=1, observed_cost=500_000_000, available=400_000_000) == 0
    assert admission.slots_for_headroom(3, active=1, observed_cost=500_000_000, available=900_000_000) == 0
    assert admission.slots_for_headroom(3, active=1, observed_cost=500_000_000, available=1_100_000_000) == 1
    assert admission.slots_for_headroom(3, active=0, observed_cost=500_000_000, available=0) == 1
    # Headroom from memory_headroom() also includes disk-backed free swap.
    assert admission.slots_for_headroom(3, active=0, observed_cost=500_000_000, available=2_000_000_000) == 3
    assert admission.additional_snapshot_slots(3, active=0, observed_cost=0) == 1


def test_memory_observation_tracks_a_real_child_process():
    admission = ResourceAdmission()
    before = admission.process_tree_memory()
    assert before is not None
    child = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "-c",
            "import sys; allocation = bytearray(64 * 1024 * 1024); allocation[0] = 1; print(len(allocation), flush=True); sys.stdin.read()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == str(64 * 1024 * 1024)
        during = admission.process_tree_memory()
        assert during is not None
        assert during > before + 32 * 1024 * 1024
    finally:
        assert child.stdin is not None
        child.stdin.close()
        assert child.wait(timeout=10) == 0


def test_memory_observation_counts_shared_pages_once_on_linux():
    admission = ResourceAdmission()
    before = admission.process_tree_memory()
    assert before is not None
    size = 128 * 1024 * 1024
    child = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "-c",
            """
import os
import sys
allocation = bytearray(128 * 1024 * 1024)
children = []
for _ in range(2):
    pid = os.fork()
    if pid == 0:
        sys.stdin.read()
        os._exit(0)
    children.append(pid)
print(len(allocation), flush=True)
sys.stdin.read()
for pid in children:
    os.waitpid(pid, 0)
""",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == str(size)
        during = admission.process_tree_memory()
        assert during is not None
        growth = during - before
        assert growth > size // 2
        if sys.platform.startswith("linux"):
            # These three real processes share one allocation. Linux PSS and
            # summing RSS differ by two copies, including inside a cgroup.
            assert growth < size * 2, f"Shared allocation counted repeatedly: {growth}"
    finally:
        assert child.stdin is not None
        child.stdin.close()
        assert child.wait(timeout=10) == 0


def test_disk_backed_swap_headroom_excludes_zram_but_keeps_backing_swap():
    swaps = """Filename Type Size Used Priority
/dev/zram0 partition 1000 100 100
/swapfile file 2000 500 -2
/dev/disk-swap partition 4000 1000 -3
"""

    assert disk_backed_swap_free_bytes(swaps, {"zram0", "254:0"}) == 4_500 * 1024


def test_disk_backed_swap_headroom_excludes_zram_device_alias():
    swaps = """Filename Type Size Used Priority
/dev/block/254:0 partition 800 200 100
/swapfile file 500 100 -2
"""

    assert disk_backed_swap_free_bytes(swaps, {"zram0", "254:0"}) == 400 * 1024


def test_memory_stall_counter_recovers_without_resetting_monitor():
    # Real kernel PSI units: cumulative microseconds and ten-second average.
    # Decision samples exercise the policy, not simulated hooks/processes.
    admission = ResourceAdmission()
    assert admission.observe_stalls("host", 100, 0.0, 0.0, 10.0) is False
    assert admission.observe_stalls("host", 400100, 20.0, 2.0, 10.0) is True
    assert admission.observe_stalls("host", 400100, 20.0, 4.0, 10.0) is False
    assert admission.observe_stalls("new-cgroup", 900, 20.0, 0.0, 10.0) is True
    assert admission.observe_stalls("new-cgroup", 900, 20.0, 2.0, 10.0) is False


def test_transient_and_low_memory_stalls_do_not_starve_admission():
    admission = ResourceAdmission()
    for sample in range(20):
        assert admission.observe_stalls("host", sample * 2600, 0.13, sample * 2.0, 10.0) is False
    # One large interval alone is not sustained pressure; the rolling average
    # must agree before deferring work.
    assert admission.observe_stalls("host", 1_000_000, 0.13, 40.0, 10.0) is False


def test_cpu_and_io_pressure_counters_recover_independently():
    admission = ResourceAdmission()
    # Actual Cabbage CPU samples (Oct 12 02:26 UTC). Memory PSI was zero;
    # the old admission check missed this sustained runnable CPU contention.
    assert admission.observe_stalls("cpu", 71414359784, 61.46, 0.0, 50.0)
    assert admission.observe_stalls("cpu", 71415840067, 63.19, 2.02, 50.0)
    assert admission.observe_stalls("cpu", 71417391396, 65.69, 4.03, 50.0)
    assert not admission.observe_stalls("memory", 8062503, 0.0, 4.03, 10.0)
    assert admission.observe_stalls("io", 11813206354, 11.49, 4.03, 10.0)
    # A stale rolling average must not hold admission after current stalls stop.
    assert not admission.observe_stalls("cpu", 71417391396, 65.69, 6.03, 50.0)
    assert not admission.observe_stalls("io", 11813206354, 11.49, 6.03, 10.0)
    # Distinct cgroups have independent counters; reset counters are not load.
    assert not admission.observe_stalls("cpu", 1, 65.69, 8.03, 50.0)
    assert not admission.observe_stalls("other-cpu", 42, 49.0, 8.03, 50.0)


def test_auto_admission_grows_gradually_and_backs_off_without_canceling_work():
    admission = ResourceAdmission()
    assert admission.snapshot_limit(0) == admission.snapshot_limit(100000)
    assert admission.concurrency_limit(4, pressure=False, now=0) == 2
    assert admission.concurrency_limit(4, pressure=False, now=5) == 2
    assert admission.concurrency_limit(4, pressure=False, now=10) == 3
    assert admission.concurrency_limit(4, pressure=True, now=11) == 1
    assert admission.concurrency_limit(4, pressure=False, now=15) == 1
    assert admission.concurrency_limit(4, pressure=False, now=21) == 2
    assert admission.concurrency_limit(1, pressure=False, now=40) == 1


def test_memory_observation_ignores_reclaimable_page_cache_of_written_files(tmp_path):
    # Captures write hundreds of MB of output files. Their page cache is
    # reclaimable, so it must not be charged as per-snapshot memory cost.
    admission = ResourceAdmission()
    before = admission.process_tree_memory()
    assert before is not None
    output = tmp_path / "capture-output.bin"
    with output.open("wb") as file:
        for _ in range(256):
            file.write(os.urandom(1024 * 1024))
        file.flush()
        os.fsync(file.fileno())
    during = admission.process_tree_memory()
    assert during is not None
    assert output.stat().st_size == 256 * 1024 * 1024
    assert during - before < 128 * 1024 * 1024, f"Page cache counted as capture memory: {during - before}"


def test_memory_observation_excludes_other_process_trees_from_capture_cost():
    # The observer is a sibling of a real allocating subprocess, like the
    # runner and an independently invoked importer sharing one container.
    observer = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "-c",
            """
import json
import os
import sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.core.settings")
import django
django.setup()
from archivebox.services.resource_admission import ResourceAdmission
admission = ResourceAdmission()
print(json.dumps([admission.process_tree_memory(), admission.memory_headroom()]), flush=True)
sys.stdin.readline()
print(json.dumps([admission.process_tree_memory(), admission.memory_headroom()]), flush=True)
""",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    allocator = None
    try:
        assert observer.stdout is not None and observer.stdin is not None
        before = json.loads(observer.stdout.readline())
        allocator = subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "-c",
                "import sys; allocation = bytearray(256 * 1024 * 1024); print(len(allocation), flush=True); sys.stdin.read()",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert allocator.stdout is not None
        assert allocator.stdout.readline().strip() == str(256 * 1024 * 1024)
        observer.stdin.write("\n")
        observer.stdin.flush()
        after = json.loads(observer.stdout.readline())
        assert observer.wait(timeout=20) == 0
        assert after[0] - before[0] < 128 * 1024 * 1024, "Sibling memory charged to capture cost"
        assert after[1] < before[1], "Sibling memory must still consume available headroom"
    finally:
        assert observer.stdin is not None
        observer.stdin.close()
        if observer.poll() is None:
            observer.kill()
            observer.wait(timeout=10)
        if allocator is not None:
            assert allocator.stdin is not None
            allocator.stdin.close()
            assert allocator.wait(timeout=10) == 0
