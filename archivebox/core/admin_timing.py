"""Opt-in, request-local timing for authenticated snapshot changelists."""

from functools import wraps
from time import perf_counter, thread_time


def timed_snapshot_changelist(view):
    @wraps(view)
    def measured(self, request, *args, **kwargs):
        enabled = (
            request.method == "GET"
            and request.headers.get("X-ArchiveBox-Admin-Timing") == "1"
            and request.user.is_active
            and request.user.is_staff
            and request.GET.get("_embedded") != "crawl"
        )
        if not enabled:
            return view(self, request, *args, **kwargs)
        started, cpu_started = perf_counter(), thread_time()
        response = view(self, request, *args, **kwargs)
        prepare = (perf_counter() - started) * 1000
        prepare_cpu = (thread_time() - cpu_started) * 1000
        # Redirects/errors are not measurements of a rendered changelist.
        if response.status_code != 200 or not hasattr(response, "render") or response.is_rendered:
            return response
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
            rendered = original_render()
            elapsed = (perf_counter() - render_started) * 1000
            cpu_elapsed = (thread_time() - render_cpu_started) * 1000
            metrics = (
                f"admin_prepare;dur={prepare:.1f}, admin_prepare_cpu;dur={prepare_cpu:.1f}, "
                f"admin_render;dur={elapsed:.1f}, admin_render_cpu;dur={cpu_elapsed:.1f}"
            )
            rendered["Server-Timing"] = ", ".join(filter(None, (rendered.get("Server-Timing"), metrics)))
            return rendered

        # Only this response is wrapped. The clocks start on its rendering thread,
        # not when queued by ASGI. No renderer, class or shared admin is patched.
        response.render = render
        return response

    return measured
