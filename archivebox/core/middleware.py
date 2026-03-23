__package__ = 'archivebox.core'

import ipaddress
import re
from pathlib import Path
from django.utils import timezone
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import redirect
from django.contrib.staticfiles import finders
from django.utils.http import http_date
from django.http import HttpResponseForbidden, HttpResponseNotModified

from archivebox.config.common import SERVER_CONFIG
from archivebox.config import VERSION
from archivebox.config.version import get_COMMIT_HASH
from archivebox.core.host_utils import (
    build_admin_url,
    build_web_url,
    get_api_host,
    get_admin_host,
    get_listen_host,
    get_listen_subdomain,
    get_public_host,
    get_web_host,
    host_matches,
    is_snapshot_subdomain,
    split_host_port,
)
from archivebox.core.views import SnapshotHostView, OriginalDomainHostView


def detect_timezone(request, activate: bool=True):
    gmt_offset = (request.COOKIES.get('GMT_OFFSET') or '').strip()
    tz = None
    if gmt_offset.replace('-', '').isdigit():
        tz = timezone.get_fixed_timezone(int(gmt_offset))
        if activate:
            timezone.activate(tz)
    # print('GMT_OFFSET', gmt_offset, tz)
    return tz


def TimezoneMiddleware(get_response):
    def middleware(request):
        detect_timezone(request, activate=True)
        return get_response(request)

    return middleware


def CacheControlMiddleware(get_response):
    snapshot_path_re = re.compile(r"^/[^/]+/\\d{8}/[^/]+/[0-9a-fA-F-]{8,36}/")
    static_cache_key = (get_COMMIT_HASH() or VERSION or "dev").strip()
    def middleware(request):
        response = get_response(request)

        if request.path.startswith('/static/'):
            rel_path = request.path[len('/static/'):]
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

        if '/archive/' in request.path or '/static/' in request.path or snapshot_path_re.match(request.path):
            if not response.get('Cache-Control'):
                policy = 'public' if SERVER_CONFIG.PUBLIC_SNAPSHOTS else 'private'
                response['Cache-Control'] = f'{policy}, max-age=60, stale-while-revalidate=300'
                # print('Set Cache-Control header to', response['Cache-Control'])
        return response

    return middleware


def ServerSecurityModeMiddleware(get_response):
    blocked_prefixes = ("/admin", "/accounts", "/api", "/add", "/web")
    allowed_methods = {"GET", "HEAD", "OPTIONS"}

    def middleware(request):
        if SERVER_CONFIG.CONTROL_PLANE_ENABLED:
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
    def middleware(request):
        request_host = (request.get_host() or "").lower()
        admin_host = get_admin_host()
        web_host = get_web_host()
        api_host = get_api_host()
        public_host = get_public_host()
        listen_host = get_listen_host()
        subdomain = get_listen_subdomain(request_host)

        if not SERVER_CONFIG.USES_SUBDOMAIN_ROUTING:
            if host_matches(request_host, listen_host):
                return get_response(request)

            req_host, req_port = split_host_port(request_host)
            listen_host_only, listen_port = split_host_port(listen_host)
            if req_host.endswith(f".{listen_host_only}"):
                if not listen_port or not req_port or listen_port == req_port:
                    target = build_web_url(request.path, request=request)
                    if request.META.get("QUERY_STRING"):
                        target = f"{target}?{request.META['QUERY_STRING']}"
                    return redirect(target)

            return get_response(request)

        if host_matches(request_host, admin_host):
            return get_response(request)

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
            request.user = AnonymousUser()
            request._cached_user = request.user
            if request.path.startswith("/admin"):
                target = build_admin_url(request.path, request=request)
                if request.META.get("QUERY_STRING"):
                    target = f"{target}?{request.META['QUERY_STRING']}"
                return redirect(target)
            return get_response(request)

        if host_matches(request_host, public_host):
            request.user = AnonymousUser()
            request._cached_user = request.user
            return get_response(request)

        if subdomain:
            if is_snapshot_subdomain(subdomain):
                view = SnapshotHostView.as_view()
                return view(request, snapshot_id=subdomain, path=request.path.lstrip("/"))
            view = OriginalDomainHostView.as_view()
            return view(request, domain=subdomain, path=request.path.lstrip("/"))

        if host_matches(request_host, listen_host):
            target = build_web_url(request.path, request=request)
            if request.META.get("QUERY_STRING"):
                target = f"{target}?{request.META['QUERY_STRING']}"
            return redirect(target)

        if admin_host or web_host:
            target = build_web_url(request.path, request=request)
            if target:
                if request.META.get("QUERY_STRING"):
                    target = f"{target}?{request.META['QUERY_STRING']}"
                return redirect(target)

        return get_response(request)

    return middleware

class ReverseProxyAuthMiddleware(RemoteUserMiddleware):
    header = 'HTTP_{normalized}'.format(normalized=SERVER_CONFIG.REVERSE_PROXY_USER_HEADER.replace('-', '_').upper())

    def process_request(self, request):
        if SERVER_CONFIG.REVERSE_PROXY_WHITELIST == '':
            return

        ip = request.META.get('REMOTE_ADDR')
        if not isinstance(ip, str):
            return

        for cidr in SERVER_CONFIG.REVERSE_PROXY_WHITELIST.split(','):
            try:
                network = ipaddress.ip_network(cidr)
            except ValueError:
                raise ImproperlyConfigured(
                    "The REVERSE_PROXY_WHITELIST config paramater is in invalid format, or "
                    "contains invalid CIDR. Correct format is a coma-separated list of IPv4/IPv6 CIDRs.")

            if ipaddress.ip_address(ip) in network:
                return super().process_request(request)
