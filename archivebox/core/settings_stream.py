from functools import partial
from inspect import getclosurevars, isfunction
from pathlib import Path
from secrets import token_hex

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.handlers.asgi import ASGIHandler, ASGIRequest
from django.http import StreamingHttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.template.response import TemplateResponse

from archivebox.config import CONSTANTS
from archivebox.plugins.discovery import BUILTIN_PLUGINS_DIR, get_plugin_catalog

_TEMPLATES = CONSTANTS.PACKAGE_DIR / "templates"
_SETTINGS_TEMPLATES = {
    "add.html": "core/add.html",
    "admin/machine/machine/change_form.html": "admin/machine/machine/change_form.html",
    "admin/personas/persona/change_form.html": "admin/personas/persona/change_form.html",
}
_SENTRY_REQUEST_MIDDLEWARE = "abx_plugins.plugins.sentry.app.RequestAttributesMiddleware"


def _csrf_callback(callback, request):
    if not isfunction(callback) or callback.__module__ != "django.utils.decorators":
        return False
    values = getclosurevars(callback).nonlocals
    return type(values.get("middleware")) is CsrfViewMiddleware and values.get("request") is request


def render_settings_grid(context, form):
    template = context.template.engine.get_template("plugins/plugin_config_grid.html")
    # Resolve settings and binary links before sending headers. The deferred
    # callback only renders the built-in settings grid from this request's data.
    with context.push(plugin_groups=form.plugin_groups):
        if defer := context.get("defer_settings_grid"):
            values = context.flatten()
            values.pop("defer_settings_grid", None)
            return defer(partial(template.render, context.new(values)))
        return template.render(context)


def stream_settings_response(request, response):
    if (
        not isinstance(request, ASGIRequest)
        or request.method != "GET"
        or request.headers.get("Range")
        or type(response) is not TemplateResponse
        or response.status_code != 200
        or response.is_rendered
        # The opt-in admin timing wraps render() to measure the complete page.
        or "render" in vars(response)
        or settings.DEBUG
        or settings.CUSTOM_TEMPLATES_ENABLED
    ):
        return response

    name = response.template_name
    if isinstance(name, (tuple, list)) and len(name) == 1:
        name = name[0]
    if not isinstance(name, str) or name not in _SETTINGS_TEMPLATES:
        return response
    context = response.context_data or {}
    form = context.get("form") if name == "add.html" else getattr(context.get("adminform"), "form", None)
    if form is None or form.is_bound or (name == "add.html" and not context.get("can_override_crawl_config")):
        return response

    # Admin's native csrf_protect callback only sets headers and cookies. It
    # can run on the shell, but other callbacks may need the complete HTML.
    callbacks = list(response._post_render_callbacks)
    if not all(_csrf_callback(callback, request) for callback in callbacks):
        return response

    # A custom template, plugin or middleware may set cookies or transform HTML
    # during rendering. Keep those on the ordinary render-before-headers path.
    # The bundled Sentry app appends middleware that only records request
    # attributes and never reads or modifies the response body.
    middleware = tuple(settings.MIDDLEWARE)
    if middleware not in (settings.BUILTIN_MIDDLEWARE, (*settings.BUILTIN_MIDDLEWARE, _SENTRY_REQUEST_MIDDLEWARE)):
        return response
    if tuple(settings.INSTALLED_APPS) != settings.BUILTIN_INSTALLED_APPS:
        return response
    if len(settings.TEMPLATES) != 1 or set(settings.TEMPLATES[0].get("OPTIONS", ())) - {"context_processors"}:
        return response
    if any(
        Path(directory) not in {_TEMPLATES, _TEMPLATES / "core", _TEMPLATES / "admin"}
        for directory in settings.TEMPLATES[0].get("DIRS", ())
    ):
        return response
    if any(plugin.path.parent != BUILTIN_PLUGINS_DIR for plugin in get_plugin_catalog().values()):
        return response
    if Path(response.resolve_template(name).origin.name) != _TEMPLATES / _SETTINGS_TEMPLATES[name]:
        return response

    marker = f"archivebox-grid-{token_hex(16)}"
    grids = []

    def defer(render_grid):
        grids.append(render_grid)
        return marker

    def after_render(rendered):
        rendered.context_data.pop("defer_settings_grid", None)
        if not grids:
            return rendered
        boundary = marker.encode(rendered.charset)
        # Outer middleware can register a callback after this one. Give it a
        # complete buffered document, just as if the grid had rendered inline.
        if len(grids) != 1 or rendered.content.count(boundary) != 1 or rendered._post_render_callbacks != [*callbacks, after_render]:
            rendered.content = rendered.rendered_content
            return rendered

        prefix, _, suffix = rendered.content.partition(boundary)
        render_grid = grids.pop()
        charset = rendered.charset

        async def body():
            yield prefix
            grid = (await sync_to_async(render_grid, thread_sensitive=True)()).encode(charset)
            # Django flushes gzip per yield. Bound each compression step on
            # the ASGI loop while still streaming one complete HTML form.
            for offset in range(0, len(grid), ASGIHandler.chunk_size):
                yield grid[offset : offset + ASGIHandler.chunk_size]
            yield suffix

        streamed = StreamingHttpResponse(
            body(),
            status=rendered.status_code,
            reason=rendered.reason_phrase,
            charset=rendered.charset,
            headers=rendered.headers,
        )
        streamed.headers.pop("Content-Length", None)
        streamed.cookies = rendered.cookies
        streamed.context_data = rendered.context_data
        streamed._resource_closers.extend(rendered._resource_closers)
        return streamed

    response.context_data["defer_settings_grid"] = defer
    response.add_post_render_callback(after_render)
    return response
