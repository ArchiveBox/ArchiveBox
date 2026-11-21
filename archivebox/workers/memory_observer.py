"""Optional process-local RSS detection; never attribute allocations to requests."""

import json
import logging
import os
import sys
import threading
import time

import psutil

from archivebox.workers.request_activity import request_activity, sampled_requests


# Match names internally; only these fixed labels and integer counts are logged.
_FRAME_GROUPS = (
    ("archivebox.misc.serve_static", "replay"),
    ("archivebox.search.", "search"),
    ("archivebox.core.exports", "export"),
    ("archivebox.core.templatetags.", "render"),
    ("django.template.", "render"),
    ("django.db.", "database"),
    ("archivebox.core.views", "view"),
    ("abx_plugins.plugins.", "plugin"),
)


def thread_activity() -> tuple[dict[str, int], dict[str, int]]:
    """Count active code families, NOT owners of RSS. Never inspect locals."""
    counts = dict.fromkeys(("replay", "search", "export", "render", "database", "view", "plugin", "other", "unobserved"), 0)
    outer = dict.fromkeys(
        ("original_replay", "snapshot_replay", "static", "admin", "search", "opencode", "other", "unobserved", "depth_limited"),
        0,
    )
    frames = sys._current_frames()
    counts["unobserved"] = max(0, len(frames) - 64)
    outer["unobserved"] = counts["unobserved"]
    frame = None
    try:
        for index, frame in enumerate(frames.values()):
            if index == 64:
                break
            category = "other"
            family = "other"
            for _ in range(64):
                if frame is None:
                    break
                module = frame.f_globals.get("__name__", "")
                matched = next(
                    (label for prefix, label in _FRAME_GROUPS if isinstance(module, str) and module.startswith(prefix)),
                    "other",
                )
                if category == "other":
                    category = matched
                # Code identity only: never inspect arguments, URLs or locals.
                name = frame.f_code.co_name
                if module == "archivebox.core.views":
                    if name in {"_serve_original_domain_replay", "_visible_replay_snapshots_for_domain"}:
                        family = "original_replay"
                    elif name == "_serve_snapshot_replay":
                        family = "snapshot_replay"
                elif module == "archivebox.misc.serve_static" and name == "serve_static_with_byterange_support":
                    family = "static"
                elif module == "archivebox.core.admin_snapshots" and name in {"changelist_view", "get_queryset", "get_results"}:
                    family = "admin"
                elif module == "archivebox.search.views" and name in {
                    "admin_snapshot_search_stream_view",
                    "public_snapshot_search_stream_view",
                    "run_search",
                    "iter_search_result_ids",
                    "iter_meta_search_ids",
                    "iter_url_prefix_search_ids",
                }:
                    family = "search"
                elif module == "abx_plugins.plugins.opencode.archivebox.views" and name in {
                    "_dispatch",
                    "agent_view",
                    "opencode_proxy_view",
                    "agent_browser_view",
                    "websocket_view",
                    "_websocket_context",
                }:
                    family = "opencode"
                frame = frame.f_back
            if frame is not None:
                outer["depth_limited"] += 1
            outer[family] += 1
            counts[category] += 1
    finally:
        # Do not retain application frames, request objects or their inputs.
        frame = None
        frames.clear()
    return counts, outer


def thread_categories() -> dict[str, int]:
    """Backward-compatible inner-stage counters."""
    return thread_activity()[0]


def kernel_peak_rss() -> int:
    # ru_maxrss is KiB on Linux and bytes on macOS. Unknown platforms do not
    # get an inferred unit; zero explicitly means this metric is unavailable.
    if sys.platform not in {"linux", "darwin"}:
        return 0
    import resource

    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value * (1024 if sys.platform == "linux" else 1))


class MemoryObserver:
    """Process-local lifecycle helper. A sub-second spike/kill may evade sampling."""

    def __init__(self, *, interval=1.0, growth_bytes=256 * 1024 * 1024, min_report_interval=10.0, logger=None):
        if interval <= 0 or growth_bytes <= 0 or min_report_interval <= 0:
            raise ValueError("Memory observer bounds must be positive")
        self.interval = interval
        self.growth_bytes = growth_bytes
        self.min_report_interval = min_report_interval
        self.logger = logger if logger is not None else logging.getLogger("uvicorn.error")
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None or self._stop.is_set():
            raise RuntimeError("Memory observer already started or stopped")
        self._thread = threading.Thread(target=self._run, name="worker-memory-observer", daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            self._thread = None
            self._stop.set()
            try:
                self.logger.warning("worker_memory_unavailable")
            except Exception:
                pass
        return self

    def stop(self) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        return self._thread is None or not self._thread.is_alive()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exception):
        self.stop()

    def _run(self):
        try:
            process = psutil.Process(os.getpid())
            sampled_peak = process.memory_info().rss
            kernel_peak = kernel_peak_rss()
            reported_sampled, reported_kernel = sampled_peak, kernel_peak
            last_report = float("-inf")
            self.logger.warning("worker_memory_baseline pid=%d rss_bytes=%d kernel_peak_bytes=%d", process.pid, sampled_peak, kernel_peak)
            while not self._stop.wait(self.interval):
                rss = process.memory_info().rss
                sampled_peak = max(sampled_peak, rss)
                kernel_peak = kernel_peak_rss()
                # A pre-exec footprint may leave kernel peak above current RSS.
                # Keep separate baselines so that cannot hide new RSS growth.
                growth = max(sampled_peak - reported_sampled, kernel_peak - reported_kernel)
                now = time.monotonic()
                if growth < self.growth_bytes or now - last_report < self.min_report_interval:
                    continue
                # A retained kernel peak may predate these active stacks; the
                # categories never attribute that peak to the sampled threads.
                categories, outer = thread_activity()
                self.logger.warning(
                    "worker_memory_growth pid=%d rss_bytes=%d sampled_peak_bytes=%d kernel_peak_bytes=%d growth_bytes=%d active_categories=%s outer_families=%s pending_asgi=%s sampled_requests=%s",
                    process.pid,
                    rss,
                    sampled_peak,
                    kernel_peak,
                    growth,
                    ",".join(f"{key}:{value}" for key, value in categories.items()),
                    ",".join(f"{key}:{value}" for key, value in outer.items()),
                    ",".join(f"{key}:{value}" for key, value in request_activity().items()),
                    json.dumps(sampled_requests(), separators=(",", ":")),
                )
                reported_sampled, reported_kernel, last_report = sampled_peak, kernel_peak, now
        except Exception:
            # Observation is optional. No exception text, traces or input data.
            try:
                self.logger.warning("worker_memory_unavailable")
            except Exception:
                # A broken log sink must not produce an unhandled thread error.
                pass
