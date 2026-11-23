"""Run real modest allocation/lifecycle checks in a disposable subprocess."""

import io
import json
import logging
import mmap
import os
import sys
import time
from archivebox.workers.memory_observer import MemoryObserver, thread_categories


def main():
    output = io.StringIO()
    logger = logging.Logger("observer-test")
    logger.addHandler(logging.StreamHandler(output))
    mode = sys.argv[1]
    if mode == "transient":
        # The pytest parent's large pre-exec footprint survives exec in ru_maxrss.
        # A real fresh fork from this small single-threaded process gives this test
        # its own small RSS baseline without resetting telemetry or allocating more.
        child = os.fork()
        if child:
            _, status = os.waitpid(child, 0)
            raise SystemExit(os.waitstatus_to_exitcode(status))
    if mode == "audit-denial":

        def deny_frame_snapshot(event, args):
            if event == "sys._current_frames":
                raise PermissionError("SENSITIVE TEST SENTINEL MUST NOT BE LOGGED")

        sys.addaudithook(deny_frame_snapshot)

    def wait_for(text, count=1):
        deadline = time.monotonic() + 5
        while output.getvalue().count(text) < count:
            assert time.monotonic() < deadline, output.getvalue()
            time.sleep(0.01)

    start = time.monotonic()
    observer = MemoryObserver(
        interval=1.0 if mode == "transient" else 0.02,
        growth_bytes=1024 * 1024,
        min_report_interval=0.3,
        logger=logger,
    )
    with observer:
        wait_for("worker_memory_baseline")
        if mode == "transient":
            # Unmap real touched pages so the transient allocation returns to
            # the OS. Freeing a bytearray may leave it resident in malloc's
            # arena, which would test allocator retention instead of a spike.
            with mmap.mmap(-1, 8 * 1024 * 1024) as allocation:
                for offset in range(0, len(allocation), mmap.PAGESIZE):
                    allocation[offset] = 1
            wait_for("worker_memory_growth")
            assert output.getvalue().count("worker_memory_growth") == 1
            row = next(row for row in output.getvalue().splitlines() if "worker_memory_growth" in row)
            fields = dict(item.split("=", 1) for item in row.split()[1:])
            assert int(fields["kernel_peak_bytes"]) > int(fields["sampled_peak_bytes"])
        else:
            # Two ordinary touched buffers, 8 MiB TOTAL, retained below.
            buffers = [bytearray(4 * 1024 * 1024)]
        if mode == "audit-denial":
            wait_for("worker_memory_unavailable")
        elif mode != "transient":
            wait_for("worker_memory_growth")
            first = time.monotonic()
            buffers.append(bytearray(4 * 1024 * 1024))
            time.sleep(0.1)
            assert output.getvalue().count("worker_memory_growth") == 1
            wait_for("worker_memory_growth", count=2)
            assert time.monotonic() - first >= 0.25
            assert output.getvalue().count("worker_memory_growth") == 2
            del buffers
            time.sleep(0.35)
            assert output.getvalue().count("worker_memory_growth") == 2
    assert observer.stop()
    assert not observer._thread.is_alive()
    assert "SENSITIVE TEST SENTINEL" not in output.getvalue()
    assert output.getvalue().count("worker_memory_baseline") == 1
    if mode == "audit-denial":
        assert output.getvalue().count("worker_memory_unavailable") == 1
        assert "worker_memory_growth" not in output.getvalue()
    else:
        assert set(thread_categories()) == {"replay", "search", "export", "render", "database", "view", "plugin", "other", "unobserved"}
    print(json.dumps({"mode": mode, "elapsed_s": time.monotonic() - start, "logs": output.getvalue()}))


if __name__ == "__main__":
    main()
