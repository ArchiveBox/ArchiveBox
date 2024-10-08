__package__ = 'archivebox.core'

import ipaddress
from django.utils import timezone
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.core.exceptions import ImproperlyConfigured

from archivebox.config.common import SERVER_CONFIG


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
    def middleware(request):
        response = get_response(request)

        if '/archive/' in request.path or '/static/' in request.path:
            policy = 'public' if SERVER_CONFIG.PUBLIC_SNAPSHOTS else 'private'
            response['Cache-Control'] = f'{policy}, max-age=60, stale-while-revalidate=300'
            # print('Set Cache-Control header to', response['Cache-Control'])
        return response

    return middleware

class ReverseProxyAuthMiddleware(RemoteUserMiddleware):
    header = 'HTTP_{normalized}'.format(normalized=SERVER_CONFIG.REVERSE_PROXY_USER_HEADER.replace('-', '_').upper())

    def process_request(self, request):
        if SERVER_CONFIG.REVERSE_PROXY_WHITELIST == '':
            return

        ip = request.META.get('REMOTE_ADDR')

        for cidr in SERVER_CONFIG.REVERSE_PROXY_WHITELIST.split(','):
            try:
                network = ipaddress.ip_network(cidr)
            except ValueError:
                raise ImproperlyConfigured(
                    "The REVERSE_PROXY_WHITELIST config paramater is in invalid format, or "
                    "contains invalid CIDR. Correct format is a coma-separated list of IPv4/IPv6 CIDRs.")

            if ipaddress.ip_address(ip) in network:
                return super().process_request(request)
