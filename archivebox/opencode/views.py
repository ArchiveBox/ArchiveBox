from __future__ import annotations

import atexit
import base64
import logging
import os
import re
import signal
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
import requests
from abx_plugins.plugins import opencode as opencode_plugin
from archivebox.config import CONSTANTS
from archivebox.config.common import get_config
from archivebox.core.routes_util import build_admin_url, get_api_base_url, get_base_url
from asgiref.sync import sync_to_async
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt


_PROCESS: subprocess.Popen | None = None
_PROCESS_READY: subprocess.Popen | None = None
_PROCESS_LOCK = threading.Lock()
_SESSION_LOCK = threading.Lock()
_LOGGER = logging.getLogger(__name__)
_PROXY_PREFIX = "/admin/agent/opencode"
_PROXY_PREFIX_REGEX = _PROXY_PREFIX.replace("/", r"\/")
_PROXY_PREFIX_NO_SLASH_REGEX = _PROXY_PREFIX.lstrip("/").replace("/", r"\/")
_CONFIG_PATH = Path(opencode_plugin.__file__).with_name("config.json")

_TEXT_CONTENT_TYPES = (
    "text/",
    "application/javascript",
    "application/x-javascript",
)
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_ARCHIVEBOX_SKILL = """---
name: archivebox
description: Use ArchiveBox's CLI and local REST API from an ArchiveBox collection.
---

You are running inside an ArchiveBox collection directory.

- ArchiveBox collection directory: {archivebox_data_dir}
- ArchiveBox BASE_URL: {archivebox_base_url}
- ArchiveBox Admin URL: {archivebox_admin_url}
- ArchiveBox REST API URL: {archivebox_api_url}
- Prefer the `archivebox` CLI for authenticated changes, e.g. `archivebox add`, `archivebox schedule`, `archivebox update`, and `archivebox shell`.
- Run ArchiveBox CLI commands from the ArchiveBox collection directory above.
- Get command help with `archivebox list --help`, `archivebox add --help`, `archivebox schedule --help`, etc. Do not use `archivebox help <command>`.
- Use `--depth=0` by default. Only use recursive crawling when the user explicitly asks for it; use `--depth=1` when you need pages one hop out.
- Before any recursive crawl, constrain scope with ArchiveBox config such as `CRAWL_MAX_URLS`, `CRAWL_MAX_SIZE`, `SNAPSHOT_MAX_*`, `URL_ALLOWLIST`, `URL_DENYLIST`, and related limits.
- Respect the configured `archivebox config --get ONLY_NEW` behavior unless the user explicitly says otherwise. Remind users that expected crawl URLs can be skipped when the collection already contains snapshots with the same URL.
- Always audit newly discovered crawl URLs before letting a crawl run broadly. Treat junk URLs such as privacy policies, legal pages, tag archives, sitemap files, feeds, login/logout URLs, and other low-value boilerplate as unwanted unless the user explicitly asked to archive them.
- Always watch crawl output and logs as the crawl progresses, and correct errors early instead of waiting until the crawl finishes.
- If a crawl contains bad URLs, pause it, edit the crawl's `urls` field to remove them, delete any unneeded snapshots already created under that crawl, then resume the crawl.
- Use `archivebox shell -c '...'` or `archivebox shell <<'PY' ... PY` for Django ORM work. Shell Plus prints an import banner first; keep stderr visible while debugging.
- Use full ArchiveBox module paths in shell code: `from archivebox.crawls.models import Crawl, CrawlSchedule` and `from archivebox.core.models import Snapshot, ArchiveResult`.
- If a model/field/relation is unclear, inspect `_meta.fields` before guessing, e.g. `archivebox shell -c "from archivebox.crawls.models import Crawl; print([f.name for f in Crawl._meta.fields])"`.
- Use `archivebox config --get BASE_URL` only to verify the configured base URL; prefer the seeded URLs above for API/admin requests.
- Use `$ARCHIVEBOX_API_URL` for REST API inspection when helpful. Do not assume admin session cookies authenticate API subdomain requests; prefer CLI/shell for authenticated mutations unless the admin provides or asks you to create an API token.
- Discover REST endpoints from `${{ARCHIVEBOX_API_URL}}v1/openapi.json`; crawl endpoints live under `/api/v1/crawls/`, snapshots under `/api/v1/core/`.
- Do not bypass ArchiveBox auth, expose API keys, or modify config unless the admin explicitly asks.
- After creating crawls or snapshots, report the crawl/snapshot IDs and the exact command or API request used.
"""


def _signal_owned_process(process: subprocess.Popen, sig: signal.Signals) -> None:
    try:
        os.killpg(process.pid, sig)
    except OSError:
        try:
            process.send_signal(sig)
        except ProcessLookupError:
            pass


def _stop_owned_process(process: subprocess.Popen | None = None) -> None:
    global _PROCESS, _PROCESS_READY
    owned_process = process or _PROCESS
    if owned_process is None:
        return
    if owned_process.poll() is None:
        _signal_owned_process(owned_process, signal.SIGCONT)
        _signal_owned_process(owned_process, signal.SIGTERM)
        try:
            owned_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _signal_owned_process(owned_process, signal.SIGKILL)
            owned_process.wait()
    if _PROCESS is owned_process:
        _PROCESS = None
    if _PROCESS_READY is owned_process:
        _PROCESS_READY = None


atexit.register(_stop_owned_process)


def _machine_config() -> dict[str, Any]:
    resolved = get_config()
    return dict(resolved.model_dump(mode="json"))


def _archivebox_data_dir_default() -> Path:
    return Path(CONSTANTS.DATA_DIR)


def _archivebox_route_urls(request: HttpRequest, route_config) -> tuple[str, str, str]:
    base_url = get_base_url(
        request=request,
        config=route_config,
    ).rstrip("/")
    admin_url = build_admin_url(
        "/admin/",
        request=request,
        config=route_config,
    ).rstrip("/")
    api_url = f"{get_api_base_url(request=request, config=route_config).rstrip('/')}/api/"
    return base_url, admin_url, api_url


def _config_value(config: dict, key: str, default):
    value = config.get(key, default)
    if value in (None, ""):
        return default
    return value


def _opencode_enabled(config: dict) -> bool:
    value = config.get("OPENCODE_ENABLED", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _require_enabled(config: dict) -> None:
    if not _opencode_enabled(config):
        raise Http404


def _require_superuser(request: HttpRequest):
    user = getattr(request, "user", None)
    if user is None:
        return redirect(f"/admin/login/?next={request.get_full_path()}")
    if (
        bool(getattr(user, "is_authenticated", False))
        and bool(getattr(user, "is_active", False))
        and bool(getattr(user, "is_superuser", False))
    ):
        return None
    if bool(getattr(user, "is_authenticated", False)):
        return HttpResponseForbidden(
            b"ArchiveBox agent access requires a superuser account.",
        )
    return redirect(f"/admin/login/?next={request.get_full_path()}")


def _origin_allowed(request: HttpRequest, path: str | None = None) -> bool:
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return True

    expected_host = request.get_host()
    pty_connect = bool(
        path and path.startswith("pty/") and path.endswith("/connect-token"),
    )
    if pty_connect:
        return True

    origin = _request_header(request, "Origin")
    if origin:
        return _same_host(origin, expected_host)

    referer = _request_header(request, "Referer")
    if referer:
        return _same_host(referer, expected_host)

    fetch_site = _request_header(request, "Sec-Fetch-Site")
    if fetch_site:
        return fetch_site in {"same-origin", "same-site", "none"}

    return False


def _same_host(value: str, expected_host: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and parsed.netloc == expected_host


def _settings(config: dict) -> dict:
    host = str(_config_value(config, "OPENCODE_HOST", "127.0.0.1"))
    port = int(_config_value(config, "OPENCODE_PORT", 4096))
    default_data_dir = _archivebox_data_dir_default()
    opencode_dir = Path(
        str(_config_value(config, "OPENCODE_STATE_DIR", default_data_dir / "opencode")),
    ).expanduser()
    workdir = Path(
        str(_config_value(config, "OPENCODE_WORKDIR", opencode_dir / "workdir")),
    ).expanduser()
    binary = str(_config_value(config, "OPENCODE_BINARY", "opencode"))
    timeout = int(_config_value(config, "OPENCODE_TIMEOUT", 120))
    return {
        "host": host,
        "port": port,
        "origin": f"http://{host}:{port}",
        "archivebox_data_dir": default_data_dir,
        "workdir": workdir,
        "opencode_dir": opencode_dir,
        "config_home": opencode_dir / "config",
        "data_home": opencode_dir / "data",
        "state_home": opencode_dir / "state",
        "cache_home": opencode_dir / "cache",
        "home": opencode_dir / "home",
        "binary": binary,
        "config": config,
        "timeout": timeout,
    }


def _resolve_binary(binary: str, config: dict) -> tuple[Any, Any, dict[str, str]]:
    try:
        from abxpkg import BinProvider
        from abx_plugins.plugins.base.utils import load_required_binary_from_config

        binary_environ = os.environ.copy()
        lib_dir = config.get("ABXPKG_LIB_DIR")
        if lib_dir:
            binary_environ["ABXPKG_LIB_DIR"] = str(lib_dir)
        loaded_dependencies = [
            load_required_binary_from_config(
                required_binary,
                _CONFIG_PATH,
                global_config=config,
                environ=binary_environ,
                install=False,
            )
            for required_binary in (
                str(config.get("NODE_BINARY") or "node"),
                str(config.get("GIT_BINARY") or "git"),
                binary,
            )
        ]
    except Exception as err:
        raise RuntimeError(
            f"OpenCode dependency is not installed from required_binaries: {err}",
        ) from err

    if any(not loaded.loaded_abspath for loaded in loaded_dependencies):
        raise RuntimeError(
            "OpenCode dependency is not installed from required_binaries.",
        )

    providers = [loaded.loaded_binprovider for loaded in loaded_dependencies if loaded.loaded_binprovider is not None]
    binary_env = BinProvider.build_exec_env(
        providers=providers,
        base_env=binary_environ,
    )
    return (
        loaded_dependencies[-1],
        loaded_dependencies[1],
        binary_env,
    )


def _project_route(workdir: Path, session_id: str = "") -> str:
    encoded = base64.b64encode(str(workdir.resolve()).encode()).decode()
    encoded = encoded.replace("+", "-").replace("/", "_").rstrip("=")
    route = f"{_PROXY_PREFIX}/{encoded}/session"
    return f"{route}/{session_id}" if session_id else route


def _ensure_project_files(settings: dict) -> None:
    workdir = settings["workdir"].resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    git_marker = workdir / ".git" / "not-a-git"
    if git_marker.exists():
        # Current OpenCode hangs on the legacy fake marker, so remove only
        # that invalid shape before initializing the real worktree.
        shutil.rmtree(git_marker.parent)

    editable_skill_path = settings["opencode_dir"] / "SKILL.md"
    editable_skill_path.parent.mkdir(parents=True, exist_ok=True)
    if not editable_skill_path.exists():
        editable_skill_path.write_text(
            _ARCHIVEBOX_SKILL.format(
                archivebox_data_dir=settings["archivebox_data_dir"],
                archivebox_base_url=settings.get("archivebox_base_url", ""),
                archivebox_admin_url=settings.get("archivebox_admin_url", ""),
                archivebox_api_url=settings.get("archivebox_api_url", ""),
            ),
        )

    opencode_skill_path = settings["config_home"] / "opencode" / "skills" / "archivebox" / "SKILL.md"
    opencode_skill_path.parent.mkdir(parents=True, exist_ok=True)
    if opencode_skill_path.resolve() != editable_skill_path.resolve():
        if opencode_skill_path.exists() or opencode_skill_path.is_symlink():
            opencode_skill_path.unlink()
        opencode_skill_path.symlink_to(editable_skill_path)


def _ensure_default_session(settings: dict) -> str:
    workdir = settings["workdir"].resolve()
    params = {"directory": str(workdir)}
    timeout = settings["timeout"]
    project = requests.post(
        f"{settings['origin']}/project/git/init",
        params=params,
        timeout=timeout,
    )
    project.raise_for_status()
    project_data = project.json()
    if Path(str(project_data.get("worktree") or "/")).resolve() != workdir:
        raise RuntimeError(
            f"OpenCode initialized the wrong project worktree: {project_data.get('worktree')!r}",
        )

    sessions = requests.get(
        f"{settings['origin']}/session",
        params={**params, "roots": "true", "limit": 55},
        timeout=timeout,
    )
    sessions.raise_for_status()
    session_data = sessions.json()
    if not isinstance(session_data, list):
        raise RuntimeError("OpenCode returned an invalid project session list.")
    for session_data_item in session_data:
        if not isinstance(session_data_item, dict):
            continue
        session_id = str(session_data_item.get("id") or "")
        session_directory = session_data_item.get("directory")
        if session_id and session_directory and Path(str(session_directory)).resolve() == workdir:
            return session_id

    session = requests.post(
        f"{settings['origin']}/session",
        params=params,
        json={},
        timeout=timeout,
    )
    session.raise_for_status()
    session_data = session.json()
    session_id = str(session_data.get("id") or "")
    session_directory = session_data.get("directory")
    if not session_id or not session_directory or Path(str(session_directory)).resolve() != workdir:
        raise RuntimeError(
            "OpenCode did not create a session for the requested worktree.",
        )
    return session_id


def _owned_process_running() -> bool:
    process = _PROCESS
    return process is not None and process.poll() is None


def _owned_process_ready() -> bool:
    process = _PROCESS_READY
    return process is not None and process is _PROCESS and process.poll() is None


def _health(settings: dict, timeout: float = 2) -> bool:
    try:
        response = requests.get(
            f"{settings['origin']}/global/health",
            timeout=timeout,
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def _opencode_version(settings: dict) -> str:
    try:
        response = requests.get(
            f"{settings['origin']}/global/health",
            timeout=2,
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("version") or "") if isinstance(data, dict) else ""
    except (requests.RequestException, ValueError):
        return ""


def _ensure_opencode(settings: dict) -> tuple[bool, str]:
    global _PROCESS, _PROCESS_READY
    started_process: subprocess.Popen | None = None
    workdir = settings["workdir"].resolve()

    with _PROCESS_LOCK:
        if _owned_process_ready():
            return True, ""
        if _health(settings):
            if _owned_process_running():
                _PROCESS_READY = _PROCESS
            return True, ""
        if _owned_process_running():
            _stop_owned_process(_PROCESS)

        try:
            binary, git_binary, binary_env = _resolve_binary(
                settings["binary"],
                settings["config"],
            )
        except RuntimeError as err:
            return False, str(err)

        env = {
            **os.environ,
            **binary_env,
            "ARCHIVEBOX_BASE_URL": str(settings.get("archivebox_base_url", "")),
            "ARCHIVEBOX_ADMIN_URL": str(settings.get("archivebox_admin_url", "")),
            "ARCHIVEBOX_API_URL": str(settings.get("archivebox_api_url", "")),
            "BROWSER": "false",
            "GIT_CEILING_DIRECTORIES": str(workdir),
            "HOME": str(settings["home"]),
            "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
            "XDG_CONFIG_HOME": str(settings["config_home"]),
            "XDG_DATA_HOME": str(settings["data_home"]),
            "XDG_STATE_HOME": str(settings["state_home"]),
            "XDG_CACHE_HOME": str(settings["cache_home"]),
        }

        settings["workdir"].mkdir(parents=True, exist_ok=True)
        settings["config_home"].mkdir(parents=True, exist_ok=True)
        settings["data_home"].mkdir(parents=True, exist_ok=True)
        settings["state_home"].mkdir(parents=True, exist_ok=True)
        settings["cache_home"].mkdir(parents=True, exist_ok=True)
        settings["home"].mkdir(parents=True, exist_ok=True)
        _ensure_project_files(settings)

        if not (workdir / ".git").exists():
            try:
                git_init = git_binary.exec(
                    cmd=("init", "--quiet"),
                    cwd=workdir,
                    env=env,
                    timeout=settings["timeout"],
                )
            except (AssertionError, OSError, subprocess.SubprocessError) as err:
                return False, f"OpenCode project initialization failed: {err}"
            if git_init.returncode != 0:
                output = (git_init.stderr or git_init.stdout or "").strip()
                return (
                    False,
                    f"OpenCode project initialization failed: {output or f'git exited with {git_init.returncode}'}",
                )

        if _health(settings):
            return True, ""

        binary_abspath = binary.loaded_abspath
        if binary.loaded_binprovider is not None:
            binary_abspath = binary.loaded_binprovider._exec_bin_abspath(
                Path(binary.loaded_abspath),
            )
        cmd = [
            str(binary_abspath),
            "serve",
            "--hostname",
            settings["host"],
            "--port",
            str(settings["port"]),
        ]
        try:
            _PROCESS = subprocess.Popen(
                cmd,
                cwd=workdir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                start_new_session=True,
            )
            _PROCESS_READY = None
            started_process = _PROCESS
        except FileNotFoundError:
            return False, f"OpenCode binary not found: {settings['binary']}"

        deadline = time.monotonic() + settings["timeout"]
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if _health(settings, timeout=min(2, remaining)):
                if time.monotonic() <= deadline:
                    _PROCESS_READY = started_process
                    return True, ""
                break
            if started_process and started_process.poll() is not None:
                if _PROCESS is started_process:
                    _PROCESS = None
                if _PROCESS_READY is started_process:
                    _PROCESS_READY = None
                return False, "OpenCode exited before the web server became ready."
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.25, remaining))

        _stop_owned_process(started_process)
        return False, "Timed out waiting for OpenCode to start."


def agent_view(request: HttpRequest):
    config = _machine_config()
    _require_enabled(config)
    auth_response = _require_superuser(request)
    if auth_response:
        return auth_response

    settings = _settings(config)
    route_config = request.__dict__.get("archivebox_config")
    base_url, admin_url, api_url = _archivebox_route_urls(request, route_config)
    settings["archivebox_base_url"] = base_url
    settings["archivebox_admin_url"] = admin_url
    settings["archivebox_api_url"] = api_url
    ok, error = _ensure_opencode(settings)
    recent_session_id = ""
    opencode_version = ""
    if ok:
        try:
            with _SESSION_LOCK:
                recent_session_id = _ensure_default_session(settings)
            opencode_version = _opencode_version(settings)
            if not opencode_version:
                ok = False
                error = "OpenCode health check did not report its version."
        except (requests.RequestException, RuntimeError, ValueError) as err:
            ok = False
            error = f"OpenCode project initialization failed: {err}"
    from archivebox.core.admin_site import archivebox_admin

    context = {
        **archivebox_admin.each_context(request),
        "title": "Agent",
        "error": "" if ok else error,
        "command": f"{settings['binary']} serve --hostname {settings['host']} --port {settings['port']}" if error else "",
        # OpenCode 1.17+ keeps durable sessions on the explicit
        # /<dirBase64>/session/<sessionId> route. We still seed localStorage
        # below because the sidebar state uses it, but the iframe itself must
        # open the durable session URL so a fresh browser does not land on the
        # transient new-session route and appear to have lost prior sessions.
        "proxy_url": _project_route(settings["workdir"], recent_session_id),
        "proxy_prefix": _PROXY_PREFIX,
        "opencode_version": opencode_version,
        "workdir": str(settings["workdir"].resolve()),
        "recent_session_id": recent_session_id,
    }
    return render(
        request,
        "opencode/agent.html",
        context,
        status=200 if ok else 502,
    )


def agent_health_view(request: HttpRequest):
    config = _machine_config()
    _require_enabled(config)
    auth_response = _require_superuser(request)
    if auth_response:
        return auth_response

    version = _opencode_version(_settings(config))
    healthy = bool(version)
    response = JsonResponse(
        {"healthy": healthy, "version": version},
        status=200 if healthy else 503,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _proxy_url(settings: dict, path: str | None) -> str:
    rel = "/" if not path else f"/{path}"
    return urljoin(settings["origin"], rel)


def _request_header(request: HttpRequest, name: str) -> str | None:
    meta = getattr(request, "META", {})
    if name == "Content-Type":
        value = meta.get("CONTENT_TYPE")
    elif name == "Content-Length":
        value = meta.get("CONTENT_LENGTH")
    else:
        value = meta.get(f"HTTP_{name.upper().replace('-', '_')}")
    return str(value) if value else None


def _request_headers(request: HttpRequest, settings: dict) -> dict[str, str]:
    forwarded = {}
    for key in ("Accept", "Accept-Language", "Content-Type", "Range", "User-Agent"):
        value = _request_header(request, key)
        if value:
            forwarded[key] = value
    return forwarded


def _request_params(request: HttpRequest) -> tuple[tuple[str, str], ...]:
    if hasattr(request.GET, "lists"):
        return tuple((key, str(value)) for key, values in request.GET.lists() for value in values)
    return tuple((key, str(value)) for key, value in dict(request.GET).items())


async def _event_chunks(
    settings: dict,
    path: str | None,
    method: str,
    params: tuple[tuple[str, str], ...],
    headers: dict[str, str],
):
    if not _owned_process_ready():
        ok, error = await sync_to_async(_ensure_opencode, thread_sensitive=False)(settings)
        if not ok:
            _LOGGER.warning("OpenCode event stream unavailable: %s", error)
            yield b'event: error\ndata: {"error":"OpenCode upstream unavailable"}\n\n'
            return

    timeout = httpx.Timeout(settings["timeout"], read=None)
    url = _proxy_url(settings, path)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream(
                method,
                url,
                params=params,
                headers=headers,
            ) as upstream:
                async for chunk in upstream.aiter_raw(chunk_size=512):
                    yield chunk
    except httpx.RequestError as err:
        _LOGGER.warning("OpenCode event stream ended: %s", err)


def _rewrite_text(body: bytes, settings: dict) -> bytes:
    text = body.decode("utf-8", errors="replace")
    text = text.replace(settings["origin"], _PROXY_PREFIX)
    text = text.replace("location.origin", f'location.origin+"{_PROXY_PREFIX}"')
    text = text.replace(
        "k(k5,{get component(){return t.router??Az},",
        f'k(k5,{{base:"{_PROXY_PREFIX}",get component(){{return t.router??Az}},',
    )
    text = text.replace('"/assets/', f'"{_PROXY_PREFIX}/assets/')
    text = text.replace("'/assets/", f"'{_PROXY_PREFIX}/assets/")
    proxy_path = rf'(\1.replace(/^{_PROXY_PREFIX_REGEX}(?=\/|$)/,"")||"/")'
    text = re.sub(r"\b(window\.location\.pathname)\b", proxy_path, text)
    text = re.sub(r"(?<![.\w])(location\.pathname)\b", proxy_path, text)
    text = text.replace(
        'window.history.replaceState(nz(o),"",r):window.history.pushState(o,"",r)',
        (
            f'window.history.replaceState(nz(o),"",r.startsWith("{_PROXY_PREFIX}")?r:r.startsWith("/")?"{_PROXY_PREFIX}"+r:r):'
            f'window.history.pushState(o,"",r.startsWith("{_PROXY_PREFIX}")?r:r.startsWith("/")?"{_PROXY_PREFIX}"+r:r)'
        ),
    )
    text = text.replace(
        'const BL="modulepreload",UL=function(t){return"/"+t}',
        f'const BL="modulepreload",UL=function(t){{return"{_PROXY_PREFIX}/"+t}}',
    )
    text = re.sub(
        rf"""(?P<prefix>\b(?:href|src|action)=["'])/(?!{_PROXY_PREFIX_NO_SLASH_REGEX}(?:/|$))""",
        rf"\g<prefix>{_PROXY_PREFIX}/",
        text,
    )
    text = re.sub(
        rf"""(?P<prefix>\b(?:fetch|EventSource)\(["'])/(?!{_PROXY_PREFIX_NO_SLASH_REGEX}(?:/|$))""",
        rf"\g<prefix>{_PROXY_PREFIX}/",
        text,
    )
    text = re.sub(
        rf"""(?P<prefix>\burl\(["']?)/(?!{_PROXY_PREFIX_NO_SLASH_REGEX}(?:/|$))""",
        rf"\g<prefix>{_PROXY_PREFIX}/",
        text,
    )
    return text.encode("utf-8")


def _response_headers(upstream: requests.Response, settings: dict) -> dict[str, str]:
    headers = {}
    for key, value in upstream.headers.items():
        lower = key.lower()
        if lower in _HOP_BY_HOP_HEADERS or lower in {
            "content-length",
            "content-encoding",
            "x-frame-options",
        }:
            continue
        if lower == "location":
            if value.startswith(settings["origin"]):
                value = value.replace(settings["origin"], _PROXY_PREFIX, 1)
            elif value.startswith("/"):
                value = f"{_PROXY_PREFIX}{value}"
        headers[key] = value
    return headers


def _proxy_error_response(error: Exception | str) -> HttpResponse:
    _LOGGER.warning("OpenCode upstream request failed: %s", error)
    return HttpResponse(
        b"OpenCode upstream request failed.",
        status=502,
        content_type="text/plain; charset=utf-8",
    )


@csrf_exempt
def opencode_proxy_view(request: HttpRequest, path: str | None = None):
    config = _machine_config()
    _require_enabled(config)
    auth_response = _require_superuser(request)
    if auth_response:
        return auth_response
    if not _origin_allowed(request, path):
        return HttpResponseForbidden(
            b"Cross-origin OpenCode agent requests are blocked.",
        )

    settings = _settings(config)
    route_config = request.__dict__.get("archivebox_config")
    base_url, admin_url, api_url = _archivebox_route_urls(request, route_config)
    settings["archivebox_base_url"] = base_url
    settings["archivebox_admin_url"] = admin_url
    settings["archivebox_api_url"] = api_url

    if request.method == "GET" and (path or "").endswith("/event"):
        response = StreamingHttpResponse(
            _event_chunks(
                settings,
                path,
                request.method or "GET",
                _request_params(request),
                _request_headers(request, settings),
            ),
            content_type="text/event-stream",
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    if path == "global/health" or not _owned_process_ready():
        ok, error = _ensure_opencode(settings)
        if not ok:
            return _proxy_error_response(error)

    try:
        method = request.method or "GET"
        upstream = requests.request(
            method,
            _proxy_url(settings, path),
            params=_request_params(request),
            data=request.body if method not in {"GET", "HEAD"} else None,
            headers=_request_headers(request, settings),
            stream=True,
            timeout=settings["timeout"],
            allow_redirects=False,
        )
    except requests.RequestException as err:
        return _proxy_error_response(err)

    try:
        body = upstream.content
    except requests.RequestException as err:
        upstream.close()
        return _proxy_error_response(err)

    content_type = upstream.headers.get("Content-Type", "")
    headers = _response_headers(upstream, settings)
    if any(content_type.startswith(prefix) for prefix in _TEXT_CONTENT_TYPES):
        body = _rewrite_text(body, settings)
    response = HttpResponse(
        body,
        status=upstream.status_code,
        content_type=content_type or "application/octet-stream",
    )
    for key, value in headers.items():
        response.headers[key] = value
    response.headers["Cache-Control"] = "no-store"
    return response
