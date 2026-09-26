import os
import subprocess

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
    before = admission.memory_headroom()
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
        during = admission.memory_headroom()
        assert during is not None
        assert during[0] > before[0] + 32 * 1024 * 1024
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
    assert admission.observe_memory_stalls("host", 100, 0.0, 0.0) is False
    assert admission.observe_memory_stalls("host", 400100, 20.0, 2.0) is True
    assert admission.observe_memory_stalls("host", 400100, 20.0, 4.0) is False
    assert admission.observe_memory_stalls("new-cgroup", 900, 20.0, 0.0) is True
    assert admission.observe_memory_stalls("new-cgroup", 900, 20.0, 2.0) is False


def test_transient_and_low_memory_stalls_do_not_starve_admission():
    admission = ResourceAdmission()
    for sample in range(20):
        assert admission.observe_memory_stalls("host", sample * 2600, 0.13, sample * 2.0) is False
    # One large interval alone is not sustained pressure; the rolling average
    # must agree before deferring work.
    assert admission.observe_memory_stalls("host", 1_000_000, 0.13, 40.0) is False
