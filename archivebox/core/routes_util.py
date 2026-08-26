from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from django.utils.http import url_has_allowed_host_and_scheme

from archivebox.config.common import get_config, get_request_config

_SNAPSHOT_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,36}$")
_SNAPSHOT_SUBDOMAIN_RE = re.compile(r"^snap-(?P<suffix>[0-9a-fA-F]{12})$")
_ROLE_SUBDOMAIN_LABELS = ("admin", "web", "api")


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
    # Accept ``*.<host>`` as a synonym for ``<host>`` so users can paste the
    # wildcard-friendly form (e.g. from the banner suggestion) without it
    # leaking ``*.`` into every downstream URL. Subdomain routing already
    # prepends the appropriate role label (admin/web/api/snap-*) at build
    # time, so the bare base host is what we want to store.
    netloc = parsed.netloc
    while netloc.startswith("*."):
        netloc = netloc[2:]
    if not netloc:
        return ""
    return f"{parsed.scheme}://{netloc}"


def normalize_base_url(value: str | None) -> str:
    return _normalize_base_url(value)


def _csrf_trusted_origins(config) -> list[str]:
    raw = (config.CSRF_TRUSTED_ORIGINS or "").strip()
    if not raw:
        return []
    seen: list[str] = []
    for entry in raw.split(","):
        normalized = _normalize_base_url(entry.strip())
        if normalized and normalized not in seen:
            seen.append(normalized)
    return seen


def _allowed_hosts(config) -> set[str]:
    raw = (config.ALLOWED_HOSTS or "").strip()
    if not raw:
        return set()
    return {entry.strip().lower() for entry in raw.split(",") if entry.strip() and entry.strip() != "*"}


def derive_base_url_from_csrf(config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    """Pick a single CSRF_TRUSTED_ORIGINS entry to act as the implicit BASE_URL.

    0.7.3 → 0.9.0 upgrade path: any reverse-proxied 0.7.3 deployment already
    had ``CSRF_TRUSTED_ORIGINS=https://archive.example.com`` set (required for
    admin login to work). On upgrade, ``BASE_URL`` is the new knob — but it
    defaults to empty, and falling through to ``BIND_ADDR`` produces an
    unreachable URL like ``http://0.0.0.0:8000``. If the user has exactly one
    CSRF origin we treat it as the implicit BASE_URL so links/redirects keep
    pointing at the public hostname they already configured.

    Returns ``""`` when the inference is ambiguous (multiple origins) or
    impossible (none set) so callers fall through to their next strategy.
    """
    config = config or get_config(**config_kwargs)
    origins = _csrf_trusted_origins(config)
    if len(origins) == 1:
        return origins[0]
    return ""


def get_listen_host(config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    config = config or get_config(**config_kwargs)
    return (config.BIND_ADDR or "").strip()


def get_listen_parts(config: dict[str, Any] | None = None, **config_kwargs: Any) -> tuple[str, str | None]:
    config = config or get_config(**config_kwargs)
    return split_host_port(get_listen_host(config=config))


def _with_port(host: str, port: str | None) -> str:
    return f"{host}:{port}" if port else host


def strip_role_subdomain(host: str) -> str:
    """Strip leading ``admin.`` / ``web.`` / ``api.`` / ``snap-*.``
    labels from a host (preserving the port). Strips repeatedly so an
    already-compounded host like ``snap-X.snap-X.<base>`` reduces all the
    way down to ``<base>``.

    Used when we want to recover the canonical base host from a request that
    arrived on a role subdomain — otherwise builders that prepend their own
    role label (e.g. ``snap-X.``) compound onto the existing prefix and you
    get ``snap-X.snap-X.snap-X.<base>`` on every click.
    """
    if not host:
        return ""
    hostname, port = split_host_port(host)
    while hostname and "." in hostname:
        head, _sep, rest = hostname.partition(".")
        if head in _ROLE_SUBDOMAIN_LABELS or _SNAPSHOT_SUBDOMAIN_RE.match(head):
            hostname = rest
            continue
        break
    return _with_port(hostname, port)


def _is_local_bind_host(host: str) -> bool:
    return host in {"", "0.0.0.0", "::", "127.0.0.1", "::1", "localhost"}


def canonical_base_host_for_request(request_host: str) -> str:
    """Strip role subdomains and remap loopback hostnames to ``archivebox.localhost``.

    Used by the banner suggestion and the in-browser pin endpoint: when the
    user is hitting the server on raw ``localhost:9292`` or ``127.0.0.1:9292``
    we want to suggest the wildcard-friendly ``archivebox.localhost`` family
    instead, so the eventual pinned ``BASE_URL`` plays nicely with subdomain
    routing without forcing the user to add a /etc/hosts entry.
    """
    hostname, port = split_host_port(strip_role_subdomain(request_host or ""))
    if _is_local_bind_host(hostname):
        hostname = "archivebox.localhost"
    return _with_port(hostname, port)


def _root_host_from_listen(config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    config = config or get_config(**config_kwargs)
    listen_host, listen_port = get_listen_parts(config=config)
    root_host = "archivebox.localhost" if _is_local_bind_host(listen_host) else listen_host
    return _with_port(root_host, listen_port) if root_host else ""


def get_base_url(request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    override = _normalize_base_url(config.BASE_URL)
    if override:
        return override

    # A) Implicit BASE_URL from a single CSRF_TRUSTED_ORIGINS entry. Catches
    # 0.7.3 → 0.9.0 upgrades where users already set CSRF_TRUSTED_ORIGINS
    # for their reverse-proxy login but never set BASE_URL.
    csrf_derived = derive_base_url_from_csrf(config)
    if csrf_derived:
        return csrf_derived

    scheme = request.scheme if request else "http"
    if request:
        req_host, req_port = split_host_port(request.get_host())
        if req_host.endswith(".archivebox.localhost"):
            return f"{scheme}://{_with_port('archivebox.localhost', req_port)}"
        if _is_local_bind_host(req_host):
            return f"{scheme}://{_with_port('archivebox.localhost', req_port)}"
        # C) Per-request fallback: when ``BASE_URL`` is unset and CSRF didn't
        # give us a single origin, trust the request's Host header — but first
        # peel off any ``admin.`` / ``web.`` / ``api.`` / ``snap-*.`` label.
        # Otherwise the URL builders below prepend their own role label onto a
        # host that already carries one, producing the ``snap-X.snap-X.snap-X``
        # compounding bug. Django has already admitted the host via
        # ALLOWED_HOSTS; the misconfig banner surfaces the case where the
        # resulting URL doesn't match what the operator probably intended.
        canonical_host = strip_role_subdomain(request.get_host())
        return f"{scheme}://{canonical_host}"

    root_host = _root_host_from_listen(config=config)
    return f"{scheme}://{root_host}" if root_host else ""


def get_base_host(request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    return urlparse(get_base_url(request=request, config=config, **config_kwargs)).netloc.lower()


def _build_base_host(subdomain: str | None, request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    base_host = get_base_host(request=request, config=config, **config_kwargs)
    if not base_host:
        return ""
    host, port = split_host_port(base_host)
    full_host = f"{subdomain}.{host}" if subdomain else host
    return _with_port(full_host, port)


def get_admin_host(config: dict[str, Any] | None = None, request=None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return get_base_host(request=request, config=config)
    return _build_base_host("admin", request=request, config=config)


def get_web_host(config: dict[str, Any] | None = None, request=None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return get_base_host(request=request, config=config)
    return _build_base_host("web", request=request, config=config)


def get_api_host(config: dict[str, Any] | None = None, request=None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return get_base_host(request=request, config=config)
    return _build_base_host("api", request=request, config=config)


def get_snapshot_subdomain(snapshot_id: str) -> str:
    normalized = re.sub(r"[^0-9a-fA-F]", "", snapshot_id or "")
    suffix = (normalized[-12:] if len(normalized) >= 12 else normalized).lower()
    return f"snap-{suffix}"


def get_snapshot_host(snapshot_id: str, config: dict[str, Any] | None = None, request=None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return get_base_host(request=request, config=config)
    return _build_base_host(get_snapshot_subdomain(snapshot_id), request=request, config=config)


def get_original_host(domain: str, config: dict[str, Any] | None = None, request=None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return get_base_host(request=request, config=config)
    return _build_base_host(domain, request=request, config=config)


def is_snapshot_subdomain(subdomain: str) -> bool:
    value = (subdomain or "").strip()
    return bool(_SNAPSHOT_SUBDOMAIN_RE.match(value) or _SNAPSHOT_ID_RE.match(value))


def get_snapshot_lookup_key(snapshot_ref: str) -> str:
    value = (snapshot_ref or "").strip().lower()
    match = _SNAPSHOT_SUBDOMAIN_RE.match(value)
    if match:
        return match.group("suffix")
    if _SNAPSHOT_ID_RE.match(value):
        return re.sub(r"[^0-9a-fA-F]", "", value).lower()
    return value


def get_listen_subdomain(request_host: str, config: dict[str, Any] | None = None, request=None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return ""
    req_host, req_port = split_host_port(request_host)
    base_host, base_port = split_host_port(get_base_host(request=request, config=config))
    if not base_host:
        return ""
    if base_port and req_port and base_port != req_port:
        return ""
    if req_host == base_host:
        return ""
    suffix = f".{base_host}"
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
    return not (target_port and req_port and target_port != req_port)


def is_allowed_archivebox_redirect_url(url: str | None, request=None, config: dict[str, Any] | None = None) -> bool:
    """Allow login redirects to this host or to the explicit ArchiveBox BASE_URL family.

    Django already rejects arbitrary absolute ``next=`` URLs for the current host.
    ArchiveBox also has legitimate cross-subdomain handoffs (admin/web/api/snap-*),
    but only when BASE_URL is pinned. Without an explicit BASE_URL we do not widen
    trust based on a request Host header that may be user supplied.
    """
    if not url:
        return False

    require_https = bool(request and request.is_secure())
    request_host = request.get_host() if request else ""
    if url_has_allowed_host_and_scheme(url=url, allowed_hosts={request_host}, require_https=require_https):
        return True

    parsed = urlparse(url)
    if not parsed.netloc:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if require_https and parsed.scheme != "https":
        return False
    if parsed.username or parsed.password:
        return False

    config = config or get_config()
    base_url = _normalize_base_url(config.BASE_URL)
    if not base_url:
        return False

    base_host, base_port = split_host_port(urlparse(base_url).netloc)
    if not base_host:
        return False

    redirect_host = (parsed.hostname or "").lower()
    if redirect_host != base_host and not redirect_host.endswith(f".{base_host}"):
        return False

    try:
        redirect_port = str(parsed.port) if parsed.port else None
    except ValueError:
        return False
    if base_port:
        return redirect_port == base_port
    return redirect_port is None


def _scheme_from_request(request=None, config: dict[str, Any] | None = None) -> str:
    config = config or get_config()
    override = _normalize_base_url(config.BASE_URL)
    if override:
        return urlparse(override).scheme
    if request:
        return request.scheme
    return "http"


def _build_base_url_for_host(host: str, request=None, config: dict[str, Any] | None = None) -> str:
    if not host:
        return ""
    scheme = _scheme_from_request(request, config=config)
    return f"{scheme}://{host}"


def get_admin_base_url(request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return get_base_url(request=request, config=config)
    return _build_base_url_for_host(_build_base_host("admin", request=request, config=config), request=request, config=config)


def get_web_base_url(request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return get_base_url(request=request, config=config)
    return _build_base_url_for_host(_build_base_host("web", request=request, config=config), request=request, config=config)


def get_api_base_url(request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return get_base_url(request=request, config=config)
    return _build_base_url_for_host(_build_base_host("api", request=request, config=config), request=request, config=config)


def get_snapshot_base_url(snapshot_id: str, request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    if not config.USES_SUBDOMAIN_ROUTING:
        return _build_url(get_web_base_url(request=request, config=config), f"/snapshot/{str(snapshot_id).replace('-', '')}")
    return _build_base_url_for_host(
        _build_base_host(get_snapshot_subdomain(snapshot_id), request=request, config=config),
        request=request,
        config=config,
    )


def get_original_base_url(domain: str, request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    config = config or (get_request_config(request) if request is not None else get_config(**config_kwargs))
    return _build_url(get_web_base_url(request=request, config=config), f"/original/{domain}")


def build_admin_url(path: str = "", request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    return _build_url(get_admin_base_url(request, config=config, **config_kwargs), path)


def build_web_url(path: str = "", request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    return _build_url(get_web_base_url(request, config=config, **config_kwargs), path)


def build_snapshot_url(snapshot_id: str, path: str = "", request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    return _build_url(get_snapshot_base_url(snapshot_id, request=request, config=config, **config_kwargs), path)


def build_original_url(domain: str, path: str = "", request=None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    return _build_url(get_original_base_url(domain, request=request, config=config, **config_kwargs), path)


def _build_url(base_url: str, path: str) -> str:
    if not base_url:
        if not path:
            return ""
        return path if path.startswith("/") else f"/{path}"
    if not path:
        return base_url
    return f"{base_url}{path if path.startswith('/') else f'/{path}'}"
