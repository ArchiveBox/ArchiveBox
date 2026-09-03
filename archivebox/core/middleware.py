__package__ = "archivebox.core"

import ipaddress
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.contrib.auth.models import AnonymousUser
from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseForbidden, HttpResponseNotModified
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import http_date

from archivebox.config import VERSION
from archivebox.config.common import get_config, get_request_config
from archivebox.config.version import get_COMMIT_HASH
from archivebox.core.routes_util import (
    build_admin_url,
    build_snapshot_url,
    build_web_url,
    get_admin_host,
    get_api_host,
    get_base_host,
    get_listen_host,
    get_listen_subdomain,
    get_web_host,
    host_matches,
    is_snapshot_subdomain,
    split_host_port,
)
from archivebox.core.views import OriginalDomainHostView, SnapshotHostView

ADMIN_LOGIN_HINT_COOKIE = "archivebox_admin_logged_in"


def _admin_login_hint_cookie_domain(config) -> str | None:
    """Resolve the parent domain to scope the cross-subdomain login hint.

    NOTE: this cookie carries only the single bit "a superuser is logged in
    on admin somewhere"; it MUST NOT be confused with the session cookie,
    which stays admin-host-scoped (see core/settings.py
    SESSION_COOKIE_DOMAIN comment — admin/web is a security boundary).

    Returns the hostname portion of ``get_base_host`` (which respects
    ``BASE_URL`` and falls back to the local-bind mapping). Strips the
    port — cookie ``Domain=`` attributes don't include ports. Returns
    ``None`` when subdomain routing is off, the base host is empty, or
    the base host is an IP / bare ``localhost`` (browsers reject
    cross-host cookies for those).
    """
    if not config.USES_SUBDOMAIN_ROUTING:
        return None
    base_host = get_base_host(config=config)
    if not base_host:
        return None
    hostname, _port = split_host_port(base_host)
    if not hostname or hostname == "localhost":
        return None
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return hostname
    return None


def detect_timezone(request, activate: bool = True):
    gmt_offset = (request.COOKIES.get("GMT_OFFSET") or "").strip()
    tz = None
    if gmt_offset.replace("-", "").isdigit():
        tz = timezone.get_fixed_timezone(int(gmt_offset))
        if activate:
            timezone.activate(tz)
    return tz


def TimezoneMiddleware(get_response):
    def middleware(request):
        detect_timezone(request, activate=True)
        return get_response(request)

    return middleware


def AdminCookieIsolationMiddleware(get_response):
    def middleware(request):
        response = get_response(request)

        if request.path == "/admin" or request.path.startswith("/admin/"):
            from archivebox.opencode.views import _PROXY_PREFIX

            is_opencode_proxy = request.path == _PROXY_PREFIX or request.path.startswith(f"{_PROXY_PREFIX}/")
            if is_opencode_proxy:
                response.headers["X-Frame-Options"] = "SAMEORIGIN"
                response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
            else:
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"

        config = request.__dict__.get("archivebox_config")
        if config is None or config.SERVER_SECURITY_MODE == "auto":
            from archivebox.config.common import get_request_config

            config = get_request_config(request, resolve_plugins=False)
        if not config.USES_SUBDOMAIN_ROUTING:
            return response

        if not config.BASE_URL and request.path.startswith("/admin/"):
            return response

        request_host = (request.get_host() or "").lower()
        request_hostname, _request_port = split_host_port(request_host)
        if host_matches(request_hostname, get_admin_host(config=config)):
            return response

        if host_matches(request_hostname, get_web_host(config=config)):
            for cookie_name in tuple(response.cookies.keys()):
                if cookie_name != ADMIN_LOGIN_HINT_COOKIE:
                    response.cookies.pop(cookie_name, None)
            return response

        response.cookies.pop(settings.SESSION_COOKIE_NAME, None)
        response.cookies.pop(settings.CSRF_COOKIE_NAME, None)
        return response

    return middleware


def CacheControlMiddleware(get_response):
    snapshot_path_re = re.compile(r"^/[^/]+/\\d{8}/[^/]+/[0-9a-fA-F-]{8,36}/")
    static_cache_key = (get_COMMIT_HASH() or VERSION or "dev").strip()

    def middleware(request):
        response = get_response(request)

        if request.path.startswith("/static/"):
            rel_path = request.path[len("/static/") :]
            static_path = finders.find(rel_path)
            if static_path:
                try:
                    mtime = Path(static_path).stat().st_mtime
                except OSError:
                    mtime = None
                etag = f'"{static_cache_key}:{int(mtime) if mtime else 0}"'
                inm = request.META.get("HTTP_IF_NONE_MATCH")
                if inm:
                    inm_list = [item.strip() for item in inm.split(",")]
                    if etag in inm_list or etag.strip('"') in [i.strip('"') for i in inm_list]:
                        not_modified = HttpResponseNotModified()
                        not_modified.headers["ETag"] = etag
                        not_modified.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                        if mtime:
                            not_modified.headers["Last-Modified"] = http_date(mtime)
                        return not_modified
                response.headers["ETag"] = etag
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                if mtime and not response.headers.get("Last-Modified"):
                    response.headers["Last-Modified"] = http_date(mtime)
                return response

        if ("/archive/" in request.path or "/static/" in request.path or snapshot_path_re.match(request.path)) and not response.get(
            "Cache-Control",
        ):
            config = request.__dict__.get("archivebox_config")
            if config is None:
                config = get_config(resolve_plugins=False)
                request.archivebox_config = config
            policy = "private" if config.PERMISSIONS == "private" else "public"
            response["Cache-Control"] = f"{policy}, max-age=60, stale-while-revalidate=300"
        return response

    return middleware


def ServerSecurityModeMiddleware(get_response):
    blocked_prefixes = ("/admin", "/accounts", "/api", "/add", "/web")
    allowed_methods = {"GET", "HEAD", "OPTIONS"}

    def middleware(request):
        config = request.__dict__.get("archivebox_config")
        if config is None or config.SERVER_SECURITY_MODE == "auto":
            base_config = config or get_config(resolve_plugins=False)
            if base_config.SERVER_SECURITY_MODE == "auto" and request.method.upper() not in allowed_methods:
                request_host, _request_port = split_host_port((request.get_host() or "").lower())
                base_host, _base_port = split_host_port(get_base_host(config=base_config))
                admin_host, _admin_port = split_host_port(get_admin_host(config=base_config))
                api_host, _api_port = split_host_port(get_api_host(config=base_config))
                web_host, _web_port = split_host_port(get_web_host(config=base_config))
                control_hosts = {host for host in (base_host, admin_host, api_host, web_host) if host}
                credentialed_api_request = request.path == "/api/v1/auth/check_api_token" or bool(
                    request.META.get("HTTP_X_ARCHIVEBOX_API_KEY") or request.META.get("HTTP_AUTHORIZATION"),
                )
                if not base_config.BASE_URL and credentialed_api_request:
                    control_hosts.add(request_host)
                first_run_setup_request = not base_config.BASE_URL and (
                    request.path == "/admin/login/"
                    or (
                        bool(getattr(request.user, "is_superuser", False))
                        and re.fullmatch(r"/admin/machine/machine/[0-9a-f-]{32,36}/change/", request.path)
                    )
                )
                if control_hosts and request_host not in control_hosts and not first_run_setup_request:
                    return HttpResponseForbidden("ArchiveBox is running with the control plane disabled on this host.")

            from archivebox.config.common import get_request_config

            config = get_request_config(request, resolve_plugins=False)

        if config.USES_SUBDOMAIN_ROUTING and config.BASE_URL and request.method.upper() not in allowed_methods:
            request_host, _request_port = split_host_port((request.get_host() or "").lower())
            control_hosts = {
                split_host_port(host)[0]
                for host in (
                    get_base_host(config=config),
                    get_admin_host(config=config),
                    get_api_host(config=config),
                    get_web_host(config=config),
                )
                if host
            }
            if request_host not in control_hosts:
                return HttpResponseForbidden("ArchiveBox is running with the control plane disabled on this host.")

        if config.CONTROL_PLANE_ENABLED:
            return get_response(request)

        request.user = AnonymousUser()
        request._cached_user = request.user

        if request.method.upper() not in allowed_methods:
            return HttpResponseForbidden("ArchiveBox is running with the control plane disabled in this security mode.")

        for prefix in blocked_prefixes:
            if request.path == prefix or request.path.startswith(f"{prefix}/"):
                return HttpResponseForbidden("ArchiveBox is running with the control plane disabled in this security mode.")

        return get_response(request)

    return middleware


def HostRoutingMiddleware(get_response):
    snapshot_path_re = re.compile(
        r"^/(?P<username>[^/]+)/(?P<date>\d{4}(?:\d{2})?(?:\d{2})?)/(?P<domain>[^/]+)/(?P<snapshot_id>[0-9a-fA-F-]{8,36})(?:/(?P<path>.*))?$",
    )
    snapshot_replay_path_re = re.compile(
        r"^/snapshot/(?P<snapshot_id>[0-9a-fA-F-]{8,36})(?:/(?P<path>.*))?$",
    )
    original_replay_path_re = re.compile(r"^/original/(?P<domain>[^/]+)(?:/(?P<path>.*))?$")

    def middleware(request):
        if request.path in {"/health", "/health/"}:
            return get_response(request)

        request_host = (request.get_host() or "").lower()
        config = request.__dict__.get("archivebox_config")
        if config is None or config.SERVER_SECURITY_MODE == "auto":
            config = get_request_config(request, resolve_plugins=False)
        admin_host = get_admin_host(config=config, request=request)
        web_host = get_web_host(config=config, request=request)
        api_host = get_api_host(config=config, request=request)
        listen_host = get_listen_host(config=config)
        subdomain = get_listen_subdomain(request_host, config=config, request=request)

        # Framework-owned assets must bypass snapshot/original-domain replay routing.
        # Otherwise pages on snapshot subdomains can receive HTML for JS/CSS requests.
        if request.path.startswith("/static/") or request.path in {"/favicon.ico", "/robots.txt"}:
            return get_response(request)

        if config.USES_SUBDOMAIN_ROUTING and config.BASE_URL and not host_matches(request_host, admin_host):
            add_should_redirect = not config.PUBLIC_ADD_VIEW and (request.path == "/add" or request.path.startswith("/add/"))
            if (
                request.path == "/admin"
                or request.path.startswith("/admin/")
                or request.path == "/accounts"
                or request.path.startswith("/accounts/")
                or add_should_redirect
            ):
                target = build_admin_url(request.path, request=request)
                if request.META.get("QUERY_STRING"):
                    target = f"{target}?{request.META['QUERY_STRING']}"
                return redirect(target)

        if subdomain and is_snapshot_subdomain(subdomain):
            view = SnapshotHostView.as_view()
            return view(request, snapshot_id=subdomain, path=request.path.lstrip("/"))

        # In subdomain mode with no explicit BASE_URL we can't safely emit
        # ``admin.``/``web.``/``snap-*.`` redirects: every URL builder uses the
        # request's own Host (via the request-host fallback in get_base_url),
        # so prepending ``admin.`` to whatever the client sent produces a
        # redirect chain of ``admin.admin.admin.<host>``. Pass the request
        # through; the misconfig banner on the rendered page tells the user
        # to pin BASE_URL so the redirects can resume.
        if config.USES_SUBDOMAIN_ROUTING and not config.BASE_URL:
            return get_response(request)

        if config.USES_SUBDOMAIN_ROUTING:
            snapshot_replay_match = snapshot_replay_path_re.match(request.path)
            if snapshot_replay_match:
                target = build_snapshot_url(
                    snapshot_replay_match.group("snapshot_id"),
                    (snapshot_replay_match.group("path") or "").strip("/"),
                    request=request,
                )
                if request.META.get("QUERY_STRING"):
                    target = f"{target}?{request.META['QUERY_STRING']}"
                return redirect(target)

            original_replay_match = original_replay_path_re.match(request.path)
            if original_replay_match:
                view = OriginalDomainHostView.as_view()
                return view(
                    request,
                    domain=original_replay_match.group("domain"),
                    path=(original_replay_match.group("path") or "").strip("/"),
                )

        if not config.USES_SUBDOMAIN_ROUTING:
            if host_matches(request_host, listen_host):
                return get_response(request)

            req_host, req_port = split_host_port(request_host)
            listen_host_only, listen_port = split_host_port(listen_host)
            if req_host.endswith(f".{listen_host_only}") and (not listen_port or not req_port or listen_port == req_port):
                target = build_web_url(request.path, request=request)
                if request.META.get("QUERY_STRING"):
                    target = f"{target}?{request.META['QUERY_STRING']}"
                return redirect(target)

            return get_response(request)

        if host_matches(request_host, admin_host):
            snapshot_match = snapshot_path_re.match(request.path)
            if config.USES_SUBDOMAIN_ROUTING and snapshot_match:
                snapshot_id = snapshot_match.group("snapshot_id")
                replay_path = (snapshot_match.group("path") or "").strip("/")
                if replay_path == "index.html":
                    replay_path = ""
                target = build_snapshot_url(snapshot_id, replay_path, request=request)
                if request.META.get("QUERY_STRING"):
                    target = f"{target}?{request.META['QUERY_STRING']}"
                return redirect(target)
            response = get_response(request)
            hint_cookie_domain = _admin_login_hint_cookie_domain(config)
            if (
                request.user.is_authenticated
                and request.user.is_active
                and request.user.is_superuser
                and not request.path.startswith("/admin/logout")
            ):
                response.set_cookie(
                    ADMIN_LOGIN_HINT_COOKIE,
                    "1",
                    max_age=1209600,
                    domain=hint_cookie_domain,
                    secure=request.is_secure(),
                    httponly=True,
                    samesite="Lax",
                )
            else:
                response.delete_cookie(ADMIN_LOGIN_HINT_COOKIE, domain=hint_cookie_domain, samesite="Lax")
            return response

        if host_matches(request_host, api_host):
            request.user = AnonymousUser()
            request._cached_user = request.user
            if request.path.startswith("/admin"):
                target = build_admin_url(request.path, request=request)
                if request.META.get("QUERY_STRING"):
                    target = f"{target}?{request.META['QUERY_STRING']}"
                return redirect(target)
            if not request.path.startswith("/api/"):
                target_path = f"/api{request.path if request.path.startswith('/') else f'/{request.path}'}"
                if request.META.get("QUERY_STRING"):
                    target_path = f"{target_path}?{request.META['QUERY_STRING']}"
                return redirect(target_path)
            return get_response(request)

        if host_matches(request_host, web_host):
            if request.COOKIES.get(ADMIN_LOGIN_HINT_COOKIE) == "1" and (request.path == "/public" or request.path.startswith("/public/")):
                target = build_admin_url("/admin/core/snapshot/", request=request)
                return redirect(target)
            request.user = AnonymousUser()
            request._cached_user = request.user
            return get_response(request)

        if subdomain:
            view = OriginalDomainHostView.as_view()
            return view(request, domain=subdomain, path=request.path.lstrip("/"))

        if host_matches(request_host, listen_host):
            target = build_web_url(request.path, request=request)
            if request.META.get("QUERY_STRING"):
                target = f"{target}?{request.META['QUERY_STRING']}"
            return redirect(target)

        if (admin_host or web_host) and config.BASE_URL:
            # Only force a canonical-host redirect when BASE_URL was set
            # explicitly. If BASE_URL is empty (e.g. 0.7.3 → 0.9.0 upgrade
            # where the user has CSRF_TRUSTED_ORIGINS but never set BASE_URL),
            # the subdomain we'd redirect to may not actually resolve in the
            # user's reverse proxy — serve the request as-is instead and let
            # the misconfig banner surface the problem in the page.
            target = build_web_url(request.path, request=request)
            if target:
                if request.META.get("QUERY_STRING"):
                    target = f"{target}?{request.META['QUERY_STRING']}"
                return redirect(target)

        return get_response(request)

    return middleware


class ReverseProxyAuthMiddleware(RemoteUserMiddleware):
    header = "HTTP_REMOTE_USER"

    def process_request(self, request):
        config = request.__dict__.get("archivebox_config")
        if config is None:
            config = get_config(base_config=settings.CONFIG, resolve_plugins=False)
            request.archivebox_config = config
        self.header = "HTTP_{normalized}".format(normalized=config.REVERSE_PROXY_USER_HEADER.replace("-", "_").upper())
        if config.REVERSE_PROXY_WHITELIST == "":
            return

        ip = request.META.get("REMOTE_ADDR")
        if not isinstance(ip, str):
            return

        for cidr in config.REVERSE_PROXY_WHITELIST.split(","):
            try:
                network = ipaddress.ip_network(cidr)
            except ValueError:
                raise ImproperlyConfigured(
                    "The REVERSE_PROXY_WHITELIST config parameter is in invalid format, or "
                    "contains invalid CIDR. Correct format is a coma-separated list of IPv4/IPv6 CIDRs.",
                )

            if ipaddress.ip_address(ip) in network:
                return super().process_request(request)
