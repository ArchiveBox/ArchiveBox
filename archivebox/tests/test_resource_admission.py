import os

from archivebox.services.resource_admission import ResourceAdmission


def test_cpu_admission_respects_process_affinity():
    admission = ResourceAdmission()
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    assert 1 <= admission.snapshot_limit(100000) <= available
    assert admission.snapshot_limit(1) == 1


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
