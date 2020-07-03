#@enforce_types
#def download_url(url: str, timeout: int=None) -> str:
#    """Download the contents of a remote url and return the text"""
#    from .config import TIMEOUT, CHECK_SSL_VALIDITY, WGET_USER_AGENT
#    timeout = timeout or TIMEOUT
#    response = requests.get(
#        url,
#        headers={'User-Agent': WGET_USER_AGENT},
#        verify=CHECK_SSL_VALIDITY,
#        timeout=timeout,
#    )
#    if response.headers.get('Content-Type') == 'application/rss+xml':
#        # Based on https://github.com/scrapy/w3lib/blob/master/w3lib/encoding.py
#        _TEMPLATE = r'''%s\s*=\s*["']?\s*%s\s*["']?'''
#        _XML_ENCODING_RE = _TEMPLATE % ('encoding', r'(?P<xmlcharset>[\w-]+)')
#        _BODY_ENCODING_PATTERN = r'<\s*(\?xml\s[^>]+%s)' % (_XML_ENCODING_RE)
#        _BODY_ENCODING_STR_RE = re.compile(_BODY_ENCODING_PATTERN, re.I | re.VERBOSE)
#        match = _BODY_ENCODING_STR_RE.search(response.text[:1024])
#        if match:
#            response.encoding = match.group('xmlcharset')
#    return response.text