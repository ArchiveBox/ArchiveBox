import re
import ssl


from typing import List, Optional, Any
from inspect import signature
from functools import wraps
from hashlib import sha256
from urllib.request import Request, urlopen
from urllib.parse import urlparse, quote, unquote
from html import escape, unescape
from datetime import datetime

from base32_crockford import encode as base32_encode         # type: ignore
import json as pyjson

from .config import (
    TIMEOUT,
    STATICFILE_EXTENSIONS,
    CHECK_SSL_VALIDITY,
    WGET_USER_AGENT,
    CHROME_OPTIONS,
)

### Parsing Helpers

# All of these are (str) -> str
# shortcuts to: https://docs.python.org/3/library/urllib.parse.html#url-parsing
scheme = lambda url: urlparse(url).scheme.lower()
without_scheme = lambda url: urlparse(url)._replace(scheme='').geturl().strip('//')
without_query = lambda url: urlparse(url)._replace(query='').geturl().strip('//')
without_fragment = lambda url: urlparse(url)._replace(fragment='').geturl().strip('//')
without_path = lambda url: urlparse(url)._replace(path='', fragment='', query='').geturl().strip('//')
path = lambda url: urlparse(url).path
basename = lambda url: urlparse(url).path.rsplit('/', 1)[-1]
domain = lambda url: urlparse(url).netloc
query = lambda url: urlparse(url).query
fragment = lambda url: urlparse(url).fragment
extension = lambda url: basename(url).rsplit('.', 1)[-1].lower() if '.' in basename(url) else ''
base_url = lambda url: without_scheme(url)  # uniq base url used to dedupe links

without_www = lambda url: url.replace('://www.', '://', 1)
without_trailing_slash = lambda url: url[:-1] if url[-1] == '/' else url.replace('/?', '?')
hashurl = lambda url: base32_encode(int(sha256(base_url(url).encode('utf-8')).hexdigest(), 16))[:20]
is_static_file = lambda url: extension(url).lower() in STATICFILE_EXTENSIONS  # TODO: the proper way is with MIME type detection, not using extension

urlencode = lambda s: s and quote(s, encoding='utf-8', errors='replace')
urldecode = lambda s: s and unquote(s)
htmlencode = lambda s: s and escape(s, quote=True)
htmldecode = lambda s: s and unescape(s)

short_ts = lambda ts: str(parse_date(ts).timestamp()).split('.')[0]
ts_to_date = lambda ts: ts and parse_date(ts).strftime('%Y-%m-%d %H:%M')
ts_to_iso = lambda ts: ts and parse_date(ts).isoformat()


URL_REGEX = re.compile(
    r'http[s]?://'                    # start matching from allowed schemes
    r'(?:[a-zA-Z]|[0-9]'              # followed by allowed alphanum characters
    r'|[$-_@.&+]|[!*\(\),]'           #    or allowed symbols
    r'|(?:%[0-9a-fA-F][0-9a-fA-F]))'  #    or allowed unicode bytes
    r'[^\]\[\(\)<>\""\'\s]+',         # stop parsing at these symbols
    re.IGNORECASE,
)


def enforce_types(func):
    """
    Enforce function arg and kwarg types at runtime using its python3 type hints
    """
    # TODO: check return type as well

    @wraps(func)
    def typechecked_function(*args, **kwargs):
        sig = signature(func)

        def check_argument_type(arg_key, arg_val):
            try:
                annotation = sig.parameters[arg_key].annotation
            except KeyError:
                annotation = None

            if annotation is not None and annotation.__class__ is type:
                if not isinstance(arg_val, annotation):
                    raise TypeError(
                        '{}(..., {}: {}) got unexpected {} argument {}={}'.format(
                            func.__name__,
                            arg_key,
                            annotation.__name__,
                            type(arg_val).__name__,
                            arg_key,
                            str(arg_val)[:64],
                        )
                    )

        # check args
        for arg_val, arg_key in zip(args, sig.parameters):
            check_argument_type(arg_key, arg_val)

        # check kwargs
        for arg_key, arg_val in kwargs.items():
            check_argument_type(arg_key, arg_val)

        return func(*args, **kwargs)

    return typechecked_function


def docstring(text: Optional[str]):
    """attach the given docstring to the decorated function"""
    def decorator(func):
        if text:
            func.__doc__ = text
        return func
    return decorator


@enforce_types
def str_between(string: str, start: str, end: str=None) -> str:
    """(<abc>12345</def>, <abc>, </def>)  ->  12345"""

    content = string.split(start, 1)[-1]
    if end is not None:
        content = content.rsplit(end, 1)[0]

    return content


@enforce_types
def parse_date(date: Any) -> Optional[datetime]:
    """Parse unix timestamps, iso format, and human-readable strings"""
    
    if date is None:
        return None

    if isinstance(date, datetime):
        return date
    
    if isinstance(date, (float, int)):
        date = str(date)

    if isinstance(date, str):
        if date.replace('.', '').isdigit():
            # this is a brittle attempt at unix timestamp parsing (which is
            # notoriously hard to do). It may lead to dates being off by
            # anything from hours to decades, depending on which app, OS,
            # and sytem time configuration was used for the original timestamp
            # more info: https://github.com/pirate/ArchiveBox/issues/119

            # Note: always always always store the original timestamp string
            # somewhere indepentendly of the parsed datetime, so that later
            # bugs dont repeatedly misparse and rewrite increasingly worse dates.
            # the correct date can always be re-derived from the timestamp str
            timestamp = float(date)

            EARLIEST_POSSIBLE = 473403600.0  # 1985
            LATEST_POSSIBLE = 1735707600.0   # 2025

            if EARLIEST_POSSIBLE < timestamp < LATEST_POSSIBLE:
                # number is seconds
                return datetime.fromtimestamp(timestamp)
                
            elif EARLIEST_POSSIBLE * 1000 < timestamp < LATEST_POSSIBLE * 1000:
                # number is milliseconds
                return datetime.fromtimestamp(timestamp / 1000)

            elif EARLIEST_POSSIBLE * 1000*1000 < timestamp < LATEST_POSSIBLE * 1000*1000:
                # number is microseconds
                return datetime.fromtimestamp(timestamp / (1000*1000))

            else:
                # continue to the end and raise a parsing failed error.
                # we dont want to even attempt parsing timestamp strings that
                # arent within these ranges
                pass

        if '-' in date:
            # 2019-04-07T05:44:39.227520
            try:
                return datetime.fromisoformat(date)
            except Exception:
                pass
            try:
                return datetime.strptime(date, '%Y-%m-%d %H:%M')
            except Exception:
                pass
    
    raise ValueError('Tried to parse invalid date! {}'.format(date))


@enforce_types
def download_url(url: str, timeout: int=TIMEOUT) -> str:
    """Download the contents of a remote url and return the text"""

    req = Request(url, headers={'User-Agent': WGET_USER_AGENT})

    if CHECK_SSL_VALIDITY:
        resp = urlopen(req, timeout=timeout)
    else:
        insecure = ssl._create_unverified_context()
        resp = urlopen(req, timeout=timeout, context=insecure)

    encoding = resp.headers.get_content_charset() or 'utf-8'  # type: ignore
    return resp.read().decode(encoding)


@enforce_types
def chrome_args(**options) -> List[str]:
    """helper to build up a chrome shell command with arguments"""

    options = {**CHROME_OPTIONS, **options}

    cmd_args = [options['CHROME_BINARY']]

    if options['CHROME_HEADLESS']:
        cmd_args += ('--headless',)
    
    if not options['CHROME_SANDBOX']:
        # dont use GPU or sandbox when running inside docker container
        cmd_args += ('--no-sandbox', '--disable-gpu')

    if not options['CHECK_SSL_VALIDITY']:
        cmd_args += ('--disable-web-security', '--ignore-certificate-errors')

    if options['CHROME_USER_AGENT']:
        cmd_args += ('--user-agent={}'.format(options['CHROME_USER_AGENT']),)

    if options['RESOLUTION']:
        cmd_args += ('--window-size={}'.format(options['RESOLUTION']),)

    if options['TIMEOUT']:
        cmd_args += ('--timeout={}'.format((options['TIMEOUT']) * 1000),)

    if options['CHROME_USER_DATA_DIR']:
        cmd_args.append('--user-data-dir={}'.format(options['CHROME_USER_DATA_DIR']))
    
    return cmd_args


class ExtendedEncoder(pyjson.JSONEncoder):
    """
    Extended json serializer that supports serializing several model
    fields and objects
    """

    def default(self, obj):
        cls_name = obj.__class__.__name__

        if hasattr(obj, '_asdict'):
            return obj._asdict()

        elif isinstance(obj, bytes):
            return obj.decode()

        elif isinstance(obj, datetime):
            return obj.isoformat()

        elif isinstance(obj, Exception):
            return '{}: {}'.format(obj.__class__.__name__, obj)

        elif cls_name in ('dict_items', 'dict_keys', 'dict_values'):
            return tuple(obj)

        return pyjson.JSONEncoder.default(self, obj)

