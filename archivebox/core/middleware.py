__package__ = "archivebox.core"

import ipaddress
import re

from asgiref.sync import iscoroutinefunction
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import DisallowedHost, ImproperlyConfigured
from django.http import HttpResponseForbidden
from django.http.request import MediaType
from django.middleware.gzip import GZipMiddleware
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils.decorators import sync_and_async_middleware

from archivebox.config.common import get_config, get_request_config
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
    is_public_host,
    split_host_port,
)
from archivebox.core.replay_timing import mark_replay_phase
from archivebox.core.views import REPLAY_COOKIE_PREFIX, HealthCheckView, OriginalDomainHostView, SnapshotHostView
from archivebox.misc.serve_static import FAVICON_CACHE_CONTROL
from archivebox.plugins.forms import PluginConfigFormMixin

ADMIN_LOGIN_HINT_COOKIE = "archivebox_admin_logged_in"


@sync_and_async_middleware
def HealthCheckMiddleware(get_response):
    # Liveness has no user/collection state. Running it through authentication
    # loads Machine config from SQLite and bridges into synchronous middleware,
    # making the probe wait for the work it is meant to observe under load.
    health_view = HealthCheckView.as_view()
    if iscoroutinefunction(get_response):

        async def middleware(request):
            if request.path == "/health/" and request.method in {"GET", "HEAD"}:
                return health_view(request)
            return await get_response(request)

    else:

        def middleware(request):
            if request.path == "/health/" and request.method in {"GET", "HEAD"}:
                return health_view(request)
            return get_response(request)

    return middleware


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
        mark_replay_phase(request, "timezone_entry")
        detect_timezone(request, activate=True)
        return get_response(request)

    return middleware


def AdminCookieIsolationMiddleware(get_response):
    def middleware(request):
        response = get_response(request)

        if request.path in {"/admin", "/accounts"} or request.path.startswith(("/admin/", "/accounts/")):
            if not getattr(response, "xframe_options_exempt", False):
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

        subdomain = get_listen_subdomain(request_host, config=config)
        public_alias = (
            is_public_host(request_host, config, explicit=True)
            and subdomain not in {"admin", "api"}
            and not is_snapshot_subdomain(subdomain)
        )
        if host_matches(request_hostname, get_web_host(config=config)) or public_alias:
            for cookie_name in tuple(response.cookies.keys()):
                if cookie_name != ADMIN_LOGIN_HINT_COOKIE:
                    response.cookies.pop(cookie_name, None)
            return response

        # Provider integrations can introduce temporary cookies beyond Django's
        # session/CSRF pair (e.g. SAML's cross-site ACS handoff). None belong on
        # isolated content/API hosts. Preserve only the existing replay grants.
        for cookie_name in tuple(response.cookies.keys()):
            if cookie_name != ADMIN_LOGIN_HINT_COOKIE and not cookie_name.startswith(REPLAY_COOKIE_PREFIX):
                response.cookies.pop(cookie_name, None)
        return response

    return middleware


class UIGZipMiddleware(GZipMiddleware):
    def process_response(self, request, response):
        # Keep captured output and range responses byte-for-byte. Compress UI
        # pages and their text assets at the origin for installs without a CDN.
        if request.method not in {"GET", "HEAD"} or request.headers.get("Range"):
            return response
        asset = request.path_info.startswith("/static/") and request.path_info.endswith((".css", ".js", ".mjs", ".svg")) and not request.GET
        match = request.resolver_match
        media_type = response.get("Content-Type", "").partition(";")[0]
        snapshot_list = match and match.url_name in {"core_snapshot_changelist", "grid"} and match.app_name == "admin"
        add = match and match.view_name == "add" and media_type in {"text/html", "application/json"}
        admin_form = (getattr(response, "context_data", None) or {}).get("adminform") if match and match.app_name == "admin" else None
        settings_form = media_type == "text/html" and isinstance(getattr(admin_form, "form", None), PluginConfigFormMixin)
        if asset and response.status_code in (200, 304):
            # Small and revalidated assets use the same cache key as gzip variants.
            patch_vary_headers(response, ("Accept-Encoding",))
        if response.status_code == 200 and (add or settings_form):
            patch_vary_headers(response, ("Accept-Encoding",))
            # Django's gzip check also matches gzip;q=0, which opts out.
            encodings = map(MediaType, request.headers.get("Accept-Encoding", "").split(","))
            if not any(encoding.main_type == "gzip" and not encoding.sub_type and encoding.quality > 0 for encoding in encodings):
                return response
        if response.status_code == 200 and (asset or snapshot_list or add or settings_form):
            return super().process_response(request, response)
        return response


def CacheControlMiddleware(get_response):
    def middleware(request):
        response = get_response(request)

        if (
            getattr(request, "archivebox_cache_policy", None)
            and response.status_code in (200, 206, 304)
            and (
                request.GET.get("download") == "zip"
                or request.GET.get("preview")
                or request.GET.get("thumbnail")
                or request.GET.get("files")
            )
        ):
            # Derived views/downloads can trigger filesystem scans or rendering.
            # Keep raw artifacts' policy intact; these are crawler hints only.
            response["X-Robots-Tag"] = ", ".join(filter(None, (response.get("X-Robots-Tag"), "noindex, follow")))

        static_asset = (
            (request.path.startswith("/static/") or request.path == "/favicon.ico")
            and response.status_code in (200, 206, 304)
            and response.has_header("ETag")
        )
        favicon = response.status_code in (200, 206, 304) and response.get("Cache-Control") == FAVICON_CACHE_CONTROL
        # Session middleware may add Vary during authorization. Public,
        # cookie-independent asset bytes keep one browser cache entry as
        # sessions change. Keep User-Agent for the crawler access policy.
        if favicon or (static_asset and not response.cookies and response.get("Cache-Control", "").startswith("public,")):
            vary = [
                value.strip()
                for value in response.get("Vary", "").split(",")
                if value.strip().lower() not in {"", "cookie", "authorization"}
            ]
            if vary:
                response["Vary"] = ", ".join(vary)
            else:
                response.headers.pop("Vary", None)
        if static_asset or favicon:
            return response

        # Other private/unlisted artifacts remain private; auth errors stay unstored.
        snapshot_policy = getattr(request, "archivebox_cache_policy", None)
        if snapshot_policy and response.status_code in (200, 206, 304):
            if not response.get("Cache-Control"):
                response["Cache-Control"] = f"{snapshot_policy}, max-age=60, stale-while-revalidate=300"
            if snapshot_policy == "private":
                patch_cache_control(response, private=True)
        elif snapshot_policy or not response.get("Cache-Control"):
            response["Cache-Control"] = "private, no-store"
        patch_vary_headers(response, ("Cookie", "Authorization"))
        return response

    return middleware


def ServerSecurityModeMiddleware(get_response):
    blocked_prefixes = ("/admin", "/accounts", "/api", "/add", "/web")
    allowed_methods = {"GET", "HEAD", "OPTIONS"}

    def middleware(request):
        config = request.__dict__.get("archivebox_config")
        configured_mode = request.__dict__.get("_archivebox_config_security_mode", config.SERVER_SECURITY_MODE if config else None)
        if config is None or configured_mode == "auto":
            base_config = config or get_config(resolve_plugins=False)
            if (configured_mode or base_config.SERVER_SECURITY_MODE) == "auto" and request.method.upper() not in allowed_methods:
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

        # Built-in admin/API/snapshot/original replay routing stays unchanged.
        # Do not infer permission from request Host when BASE_URL is unset.
        configured_subdomain = get_listen_subdomain(request_host, config=config)
        builtin_replay_host = config.USES_SUBDOMAIN_ROUTING and configured_subdomain and configured_subdomain != "web"
        if not builtin_replay_host and not is_public_host(request_host, config):
            raise DisallowedHost(f"Public ArchiveBox host {request_host!r} is not in ALLOWED_HOSTS or BASE_URL.")

        # Framework-owned assets must bypass snapshot/original-domain replay routing.
        # Otherwise pages on snapshot subdomains can receive HTML for JS/CSS requests.
        if request.path.startswith("/static/") or request.path in {"/favicon.ico", "/robots.txt"}:
            return get_response(request)

        if (
            config.USES_SUBDOMAIN_ROUTING
            and config.BASE_URL
            and not host_matches(request_host, admin_host)
            # A dated snapshot path can belong to an owner named admin/accounts/add.
            # Keep it on the replay path instead of cycling through the admin host.
            and not snapshot_path_re.match(request.path)
        ):
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

        public_alias = is_public_host(request_host, config, explicit=True) and not host_matches(
            request_host,
            get_base_host(config=config, request=request),
        )
        if host_matches(request_host, web_host) or public_alias:
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
        config = get_request_config(request, resolve_plugins=False)
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
