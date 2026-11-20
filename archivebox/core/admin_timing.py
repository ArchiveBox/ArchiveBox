"""Opt-in, request-local timing for authenticated snapshot changelists."""

from functools import wraps
from pathlib import Path
from threading import get_native_id
from time import perf_counter, thread_time

from django.utils.cache import patch_cache_control

QUERY_FLAG = "_admin_timing"


def _read_schedstat(path: Path = Path("/proc/thread-self/schedstat")) -> tuple[int, int] | None:
    """Read the current thread's cumulative time runnable but not executing."""
    try:
        cpu_ns, runnable_ns, slices = map(int, path.read_text(encoding="ascii").split())
    except (OSError, ValueError):
        return None
    if not all(0 <= value < 2**64 for value in (cpu_ns, runnable_ns, slices)):
        return None
    return get_native_id(), runnable_ns


def _runnable_metric(phase: str, before: tuple[int, int] | None, after: tuple[int, int] | None) -> str | None:
    if before is None or after is None or before[0] != after[0] or after[1] <= before[1]:
        # An unchanged counter can mean scheduler accounting is unavailable.
        return None
    return f"admin_{phase}_runnable;dur={(after[1] - before[1]) / 1_000_000:.1f}"


def timed_snapshot_changelist(view):
    @wraps(view)
    def measured(self, request, *args, **kwargs):
        eligible = request.method == "GET" and request.user.is_active and request.user.is_staff and request.GET.get("_embedded") != "crawl"
        if not eligible:
            return view(self, request, *args, **kwargs)
        query_enabled = request.GET.get(QUERY_FLAG) == "1"
        if QUERY_FLAG in request.GET:
            # Keep diagnostics out of admin filters, saved navigation and cache keys.
            query = request.GET.copy()
            query.pop(QUERY_FLAG)
            request.GET = query
            request.META["QUERY_STRING"] = query.urlencode()
        if not query_enabled and request.headers.get("X-ArchiveBox-Admin-Timing") != "1":
            return view(self, request, *args, **kwargs)
        started, cpu_started = perf_counter(), thread_time()
        prepare_before = _read_schedstat()
        response = view(self, request, *args, **kwargs)
        prepare_runnable = _runnable_metric("prepare", prepare_before, _read_schedstat())
        prepare = (perf_counter() - started) * 1000
        prepare_cpu = (thread_time() - cpu_started) * 1000
        # Redirects/errors are not measurements of a rendered changelist.
        if response.status_code != 200 or not hasattr(response, "render") or response.is_rendered:
            return response
        if query_enabled:
            response.context_data["admin_timing_clean_url"] = request.get_full_path()
        original_render = response.render
        original_instance_render = response.__dict__.get("render")

        def render():
            # Restore the native method before rendering so the response
            # does not retain a closure (and its body) until cyclic GC.
            if original_instance_render is None:
                response.__dict__.pop("render", None)
            else:
                response.render = original_instance_render
            if response.is_rendered:
                return original_render()
            render_started, render_cpu_started = perf_counter(), thread_time()
            render_before = _read_schedstat()
            rendered = original_render()
            render_runnable = _runnable_metric("render", render_before, _read_schedstat())
            elapsed = (perf_counter() - render_started) * 1000
            cpu_elapsed = (thread_time() - render_cpu_started) * 1000
            metrics = (
                f"admin_prepare;dur={prepare:.1f}, admin_prepare_cpu;dur={prepare_cpu:.1f}, "
                f"admin_render;dur={elapsed:.1f}, admin_render_cpu;dur={cpu_elapsed:.1f}"
            )
            rendered["Server-Timing"] = ", ".join(filter(None, (rendered.get("Server-Timing"), metrics, prepare_runnable, render_runnable)))
            patch_cache_control(rendered, private=True, no_store=True)
            return rendered

        # Only this response is wrapped. The clocks start on its rendering thread,
        # not when queued by ASGI. No renderer, class or shared admin is patched.
        response.render = render
        return response

    return measured
