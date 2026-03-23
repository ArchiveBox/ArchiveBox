from __future__ import annotations

from __future__ import annotations

import re
from urllib.parse import urlparse

from archivebox.config.common import SERVER_CONFIG


_SNAPSHOT_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,36}$")


def split_host_port(host: str) -> tuple[str, str | None]:
    parsed = urlparse(f"//{host}")
    hostname = (parsed.hostname or host or "").lower()
    port = str(parsed.port) if parsed.port else None
    return hostname, port


def _normalize_base_url(value: str | None) -> str:
    if not value:
        return ""
    base = value.strip()
    if not base:
        return ""
    if "://" not in base:
        base = f"http://{base}"
    parsed = urlparse(base)
    if not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_base_url(value: str | None) -> str:
    return _normalize_base_url(value)


def get_listen_host() -> str:
    return (SERVER_CONFIG.LISTEN_HOST or "").strip()


def get_listen_parts() -> tuple[str, str | None]:
    return split_host_port(get_listen_host())


def _build_listen_host(subdomain: str | None) -> str:
    host, port = get_listen_parts()
    if not host:
        return ""
    full_host = f"{subdomain}.{host}" if subdomain else host
    if port:
        return f"{full_host}:{port}"
    return full_host


def get_admin_host() -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return get_listen_host().lower()
    override = _normalize_base_url(SERVER_CONFIG.ADMIN_BASE_URL)
    if override:
        return urlparse(override).netloc.lower()
    return _build_listen_host("admin")


def get_web_host() -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return get_listen_host().lower()
    override = _normalize_base_url(SERVER_CONFIG.ARCHIVE_BASE_URL)
    if override:
        return urlparse(override).netloc.lower()
    return _build_listen_host("web")

def get_api_host() -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return get_listen_host().lower()
    return _build_listen_host("api")

def get_public_host() -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return get_listen_host().lower()
    return _build_listen_host("public")


def get_snapshot_host(snapshot_id: str) -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return get_listen_host().lower()
    return _build_listen_host(snapshot_id)


def get_original_host(domain: str) -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return get_listen_host().lower()
    return _build_listen_host(domain)


def is_snapshot_subdomain(subdomain: str) -> bool:
    return bool(_SNAPSHOT_ID_RE.match(subdomain or ""))


def get_listen_subdomain(request_host: str) -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return ""
    req_host, req_port = split_host_port(request_host)
    listen_host, listen_port = get_listen_parts()
    if not listen_host:
        return ""
    if listen_port and req_port and listen_port != req_port:
        return ""
    if req_host == listen_host:
        return ""
    suffix = f".{listen_host}"
    if req_host.endswith(suffix):
        return req_host[: -len(suffix)]
    return ""


def host_matches(request_host: str, target_host: str) -> bool:
    if not request_host or not target_host:
        return False
    req_host, req_port = split_host_port(request_host)
    target_host_only, target_port = split_host_port(target_host)
    if req_host != target_host_only:
        return False
    if target_port and req_port and target_port != req_port:
        return False
    return True


def _scheme_from_request(request=None) -> str:
    if request:
        return request.scheme
    return "http"


def _build_base_url_for_host(host: str, request=None) -> str:
    if not host:
        return ""
    scheme = _scheme_from_request(request)
    return f"{scheme}://{host}"


def get_admin_base_url(request=None) -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return _build_base_url_for_host(get_listen_host(), request=request)
    override = _normalize_base_url(SERVER_CONFIG.ADMIN_BASE_URL)
    if override:
        return override
    return _build_base_url_for_host(get_admin_host(), request=request)


def get_web_base_url(request=None) -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return _build_base_url_for_host(get_listen_host(), request=request)
    override = _normalize_base_url(SERVER_CONFIG.ARCHIVE_BASE_URL)
    if override:
        return override
    return _build_base_url_for_host(get_web_host(), request=request)

def get_api_base_url(request=None) -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return _build_base_url_for_host(get_listen_host(), request=request)
    return _build_base_url_for_host(get_api_host(), request=request)


def get_public_base_url(request=None) -> str:
    return _build_base_url_for_host(get_public_host(), request=request)


# Backwards-compat aliases (archive == web)
def get_archive_base_url(request=None) -> str:
    return get_web_base_url(request=request)


def get_snapshot_base_url(snapshot_id: str, request=None) -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return _build_url(get_web_base_url(request=request), f"/snapshot/{snapshot_id}")
    return _build_base_url_for_host(get_snapshot_host(snapshot_id), request=request)


def get_original_base_url(domain: str, request=None) -> str:
    if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
        return _build_url(get_web_base_url(request=request), f"/original/{domain}")
    return _build_base_url_for_host(get_original_host(domain), request=request)


def build_admin_url(path: str = "", request=None) -> str:
    return _build_url(get_admin_base_url(request), path)


def build_web_url(path: str = "", request=None) -> str:
    return _build_url(get_web_base_url(request), path)

def build_api_url(path: str = "", request=None) -> str:
    return _build_url(get_api_base_url(request), path)


def build_archive_url(path: str = "", request=None) -> str:
    return _build_url(get_archive_base_url(request), path)


def build_snapshot_url(snapshot_id: str, path: str = "", request=None) -> str:
    return _build_url(get_snapshot_base_url(snapshot_id, request=request), path)


def build_original_url(domain: str, path: str = "", request=None) -> str:
    return _build_url(get_original_base_url(domain, request=request), path)


def _build_url(base_url: str, path: str) -> str:
    if not base_url:
        if not path:
            return ""
        return path if path.startswith("/") else f"/{path}"
    if not path:
        return base_url
    return f"{base_url}{path if path.startswith('/') else f'/{path}'}"
