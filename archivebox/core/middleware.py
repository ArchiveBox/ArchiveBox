__package__ = 'archivebox.core'

from django.utils import timezone

from ..config import PUBLIC_SNAPSHOTS


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
            policy = 'public' if PUBLIC_SNAPSHOTS else 'private'
            response['Cache-Control'] = f'{policy}, max-age=60, stale-while-revalidate=300'
            # print('Set Cache-Control header to', response['Cache-Control'])
        return response

    return middleware
