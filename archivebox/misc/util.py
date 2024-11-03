__package__ = 'archivebox.misc'

import re
import requests
import json as pyjson
import http.cookiejar

from typing import List, Optional, Any, Callable
from pathlib import Path
from inspect import signature
from functools import wraps
from hashlib import sha256
from urllib.parse import urlparse, quote, unquote
from html import escape, unescape
from datetime import datetime, timezone
from dateparser import parse as dateparser
from requests.exceptions import RequestException, ReadTimeout

from base32_crockford import encode as base32_encode                            # type: ignore
from w3lib.encoding import html_body_declared_encoding, http_content_type_encoding
try:
    import chardet    # type:ignore
    detect_encoding = lambda rawdata: chardet.detect(rawdata)["encoding"]
except ImportError:
    detect_encoding = lambda rawdata: "utf-8"


from archivebox.config.constants import CONSTANTS

from .logging import COLOR_DICT


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

urlencode = lambda s: s and quote(s, encoding='utf-8', errors='replace')
urldecode = lambda s: s and unquote(s)
htmlencode = lambda s: s and escape(s, quote=True)
htmldecode = lambda s: s and unescape(s)

short_ts = lambda ts: str(parse_date(ts).timestamp()).split('.')[0]
ts_to_date_str = lambda ts: ts and parse_date(ts).strftime('%Y-%m-%d %H:%M')
ts_to_iso = lambda ts: ts and parse_date(ts).isoformat()

COLOR_REGEX = re.compile(r'\[(?P<arg_1>\d+)(;(?P<arg_2>\d+)(;(?P<arg_3>\d+))?)?m')


# https://mathiasbynens.be/demo/url-regex
URL_REGEX = re.compile(
    r'(?=('                          
    r'http[s]?://'                     # start matching from allowed schemes
    r'(?:[a-zA-Z]|[0-9]'               # followed by allowed alphanum characters
    r'|[-_$@.&+!*\(\),]'               #   or allowed symbols (keep hyphen first to match literal hyphen)
    r'|[^\u0000-\u007F])+'             #   or allowed unicode bytes
    r'[^\]\[<>"\'\s]+'                 # stop parsing at these symbols
    r'))',
    re.IGNORECASE | re.UNICODE,
)

def parens_are_matched(string: str, open_char='(', close_char=')'):
    """check that all parentheses in a string are balanced and nested properly"""
    count = 0
    for c in string:
        if c == open_char:
            count += 1
        elif c == close_char:
            count -= 1
        if count < 0:
            return False
    return count == 0

def fix_url_from_markdown(url_str: str) -> str:
    """
    cleanup a regex-parsed url that may contain dangling trailing parens from markdown link syntax
    helpful to fix URLs parsed from markdown e.g.
      input:  https://wikipedia.org/en/some_article_(Disambiguation).html?abc=def).somemoretext
      result: https://wikipedia.org/en/some_article_(Disambiguation).html?abc=def

    IMPORTANT ASSUMPTION: valid urls wont have unbalanced or incorrectly nested parentheses
    e.g. this will fail the user actually wants to ingest a url like 'https://example.com/some_wei)(rd_url'
         in that case it will return https://example.com/some_wei (truncated up to the first unbalanced paren)
    This assumption is true 99.9999% of the time, and for the rare edge case the user can use url_list parser.
    """
    trimmed_url = url_str

    # cut off one trailing character at a time
    # until parens are balanced e.g. /a(b)c).x(y)z -> /a(b)c
    while not parens_are_matched(trimmed_url):
        trimmed_url = trimmed_url[:-1]
    
    # make sure trimmed url is still valid
    if re.findall(URL_REGEX, trimmed_url):
        return trimmed_url
    
    return url_str

def find_all_urls(urls_str: str):
    for url in re.findall(URL_REGEX, urls_str):
        yield fix_url_from_markdown(url)


def is_static_file(url: str):
    # TODO: the proper way is with MIME type detection + ext, not only extension
    return extension(url).lower() in CONSTANTS.STATICFILE_EXTENSIONS


def enforce_types(func):
    """
    Enforce function arg and kwarg types at runtime using its python3 type hints
    Simpler version of pydantic @validate_call decorator
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
def parse_date(date: Any) -> datetime:
    """Parse unix timestamps, iso format, and human-readable strings"""
    
    if date is None:
        return None    # type: ignore

    if isinstance(date, datetime):
        if date.tzinfo is None:
            return date.replace(tzinfo=timezone.utc)

        assert date.tzinfo.utcoffset(datetime.now()).seconds == 0, 'Refusing to load a non-UTC date!'
        return date
    
    if isinstance(date, (float, int)):
        date = str(date)

    if isinstance(date, str):
        return dateparser(date, settings={'TIMEZONE': 'UTC'}).astimezone(timezone.utc)

    raise ValueError('Tried to parse invalid date! {}'.format(date))


@enforce_types
def download_url(url: str, timeout: int=None) -> str:
    """Download the contents of a remote url and return the text"""

    from archivebox.config.common import ARCHIVING_CONFIG

    timeout = timeout or ARCHIVING_CONFIG.TIMEOUT
    session = requests.Session()

    if ARCHIVING_CONFIG.COOKIES_FILE and Path(ARCHIVING_CONFIG.COOKIES_FILE).is_file():
        cookie_jar = http.cookiejar.MozillaCookieJar(ARCHIVING_CONFIG.COOKIES_FILE)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        for cookie in cookie_jar:
            session.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)

    response = session.get(
        url,
        headers={'User-Agent': ARCHIVING_CONFIG.USER_AGENT},
        verify=ARCHIVING_CONFIG.CHECK_SSL_VALIDITY,
        timeout=timeout,
    )

    content_type = response.headers.get('Content-Type', '')
    encoding = http_content_type_encoding(content_type) or html_body_declared_encoding(response.text)

    if encoding is not None:
        response.encoding = encoding

    try:
        return response.text
    except UnicodeDecodeError:
        # if response is non-test (e.g. image or other binary files), just return the filename instead
        return url.rsplit('/', 1)[-1]

@enforce_types
def get_headers(url: str, timeout: int | None=None) -> str:
    """Download the contents of a remote url and return the headers"""
    # TODO: get rid of this and use an abx pluggy hook instead
    
    from archivebox.config.common import ARCHIVING_CONFIG
    
    timeout = timeout or ARCHIVING_CONFIG.TIMEOUT

    try:
        response = requests.head(
            url,
            headers={'User-Agent': ARCHIVING_CONFIG.USER_AGENT},
            verify=ARCHIVING_CONFIG.CHECK_SSL_VALIDITY,
            timeout=timeout,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            raise RequestException
    except ReadTimeout:
        raise
    except RequestException:
        response = requests.get(
            url,
            headers={'User-Agent': ARCHIVING_CONFIG.USER_AGENT},
            verify=ARCHIVING_CONFIG.CHECK_SSL_VALIDITY,
            timeout=timeout,
            stream=True
        )
    
    return pyjson.dumps(
        {
            'URL': url,
            'Status-Code': response.status_code,
            'Elapsed': response.elapsed.total_seconds()*1000,
            'Encoding': str(response.encoding),
            'Apparent-Encoding': response.apparent_encoding,
            **dict(response.headers),
        },
        indent=4,
    )


@enforce_types
def ansi_to_html(text: str) -> str:
    """
    Based on: https://stackoverflow.com/questions/19212665/python-converting-ansi-color-codes-to-html
    Simple way to render colored CLI stdout/stderr in HTML properly, Textual/rich is probably better though.
    """

    TEMPLATE = '<span style="color: rgb{}"><br>'
    text = text.replace('[m', '</span>')

    def single_sub(match):
        argsdict = match.groupdict()
        if argsdict['arg_3'] is None:
            if argsdict['arg_2'] is None:
                _, color = 0, argsdict['arg_1']
            else:
                _, color = argsdict['arg_1'], argsdict['arg_2']
        else:
            _, color = argsdict['arg_3'], argsdict['arg_2']

        return TEMPLATE.format(COLOR_DICT[color][0])

    return COLOR_REGEX.sub(single_sub, text)


@enforce_types
def dedupe(options: List[str]) -> List[str]:
    """
    Deduplicates the given CLI args by key=value. Options that come later override earlier.
    """
    deduped = {}

    for option in options:
        key = option.split('=')[0]
        deduped[key] = option

    return list(deduped.values())



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
        
        elif isinstance(obj, Path):
            return str(obj)
        
        elif cls_name in ('dict_items', 'dict_keys', 'dict_values'):
            return tuple(obj)
        
        elif isinstance(obj, Callable):
            return str(obj)

        return pyjson.JSONEncoder.default(self, obj)


### URL PARSING TESTS / ASSERTIONS

# Check that plain text regex URL parsing works as expected
#   this is last-line-of-defense to make sure the URL_REGEX isn't
#   misbehaving due to some OS-level or environment level quirks (e.g. regex engine / cpython / locale differences)
#   the consequences of bad URL parsing could be disastrous and lead to many
#   incorrect/badly parsed links being added to the archive, so this is worth the cost of checking

assert fix_url_from_markdown('http://example.com/a(b)c).x(y)z') == 'http://example.com/a(b)c'
assert fix_url_from_markdown('https://wikipedia.org/en/some_article_(Disambiguation).html?abc=def).link(with)_trailingtext') == 'https://wikipedia.org/en/some_article_(Disambiguation).html?abc=def'

URL_REGEX_TESTS = [
    ('https://example.com', ['https://example.com']),
    ('http://abc-file234example.com/abc?def=abc&23423=sdfsdf#abc=234&234=a234', ['http://abc-file234example.com/abc?def=abc&23423=sdfsdf#abc=234&234=a234']),

    ('https://twitter.com/share?url=https://akaao.success-corp.co.jp&text=ア@サ!ト&hashtags=ア%オ,元+ア.ア-オ_イ*シ$ロ abc', ['https://twitter.com/share?url=https://akaao.success-corp.co.jp&text=ア@サ!ト&hashtags=ア%オ,元+ア.ア-オ_イ*シ$ロ', 'https://akaao.success-corp.co.jp&text=ア@サ!ト&hashtags=ア%オ,元+ア.ア-オ_イ*シ$ロ']),
    ('<a href="https://twitter.com/share#url=https://akaao.success-corp.co.jp&text=ア@サ!ト?hashtags=ア%オ,元+ア&abc=.ア-オ_イ*シ$ロ"> abc', ['https://twitter.com/share#url=https://akaao.success-corp.co.jp&text=ア@サ!ト?hashtags=ア%オ,元+ア&abc=.ア-オ_イ*シ$ロ', 'https://akaao.success-corp.co.jp&text=ア@サ!ト?hashtags=ア%オ,元+ア&abc=.ア-オ_イ*シ$ロ']),

    ('///a',                                                []),
    ('http://',                                             []),
    ('http://../',                                          ['http://../']),
    ('http://-error-.invalid/',                             ['http://-error-.invalid/']),
    ('https://a(b)c+1#2?3&4/',                              ['https://a(b)c+1#2?3&4/']),
    ('http://उदाहरण.परीक्षा',                                   ['http://उदाहरण.परीक्षा']),
    ('http://例子.测试',                                     ['http://例子.测试']),
    ('http://➡.ws/䨹 htps://abc.1243?234',                  ['http://➡.ws/䨹']),
    ('http://⌘.ws">https://exa+mple.com//:abc ',            ['http://⌘.ws', 'https://exa+mple.com//:abc']),
    ('http://مثال.إختبار/abc?def=ت&ب=abc#abc=234',          ['http://مثال.إختبار/abc?def=ت&ب=abc#abc=234']),
    ('http://-.~_!$&()*+,;=:%40:80%2f::::::@example.c\'om', ['http://-.~_!$&()*+,;=:%40:80%2f::::::@example.c']),
    
    ('http://us:pa@ex.co:42/http://ex.co:19/a?_d=4#-a=2.3', ['http://us:pa@ex.co:42/http://ex.co:19/a?_d=4#-a=2.3', 'http://ex.co:19/a?_d=4#-a=2.3']),
    ('http://code.google.com/events/#&product=browser',     ['http://code.google.com/events/#&product=browser']),
    ('http://foo.bar?q=Spaces should be encoded',           ['http://foo.bar?q=Spaces']),
    ('http://foo.com/blah_(wikipedia)#c(i)t[e]-1',          ['http://foo.com/blah_(wikipedia)#c(i)t']),
    ('http://foo.com/(something)?after=parens',             ['http://foo.com/(something)?after=parens']),
    ('http://foo.com/unicode_(✪)_in_parens) abc',           ['http://foo.com/unicode_(✪)_in_parens']),
    ('http://foo.bar/?q=Test%20URL-encoded%20stuff',        ['http://foo.bar/?q=Test%20URL-encoded%20stuff']),

    ('[xyz](http://a.b/?q=(Test)%20U)RL-encoded%20stuff',   ['http://a.b/?q=(Test)%20U']),
    ('[xyz](http://a.b/?q=(Test)%20U)-ab https://abc+123',  ['http://a.b/?q=(Test)%20U', 'https://abc+123']),
    ('[xyz](http://a.b/?q=(Test)%20U) https://a(b)c+12)3',  ['http://a.b/?q=(Test)%20U', 'https://a(b)c+12']),
    ('[xyz](http://a.b/?q=(Test)a\nabchttps://a(b)c+12)3',  ['http://a.b/?q=(Test)a', 'https://a(b)c+12']),
    ('http://foo.bar/?q=Test%20URL-encoded%20stuff',        ['http://foo.bar/?q=Test%20URL-encoded%20stuff']),
]
for urls_str, expected_url_matches in URL_REGEX_TESTS:
    url_matches = list(find_all_urls(urls_str))
    assert url_matches == expected_url_matches, 'FAILED URL_REGEX CHECK!'


# More test cases
_test_url_strs = {
    'example.com': 0,
    '/example.com': 0,
    '//example.com': 0,
    ':/example.com': 0,
    '://example.com': 0,
    'htt://example8.com': 0,
    '/htt://example.com': 0,
    'https://example': 1,
    'https://localhost/2345': 1,
    'https://localhost:1234/123': 1,
    '://': 0,
    'https://': 0,
    'http://': 0,
    'ftp://': 0,
    'ftp://example.com': 0,
    'https://example.com': 1,
    'https://example.com/': 1,
    'https://a.example.com': 1,
    'https://a.example.com/': 1,
    'https://a.example.com/what/is/happening.html': 1,
    'https://a.example.com/what/ís/happening.html': 1,
    'https://a.example.com/what/is/happening.html?what=1&2%20b#höw-about-this=1a': 1,
    'https://a.example.com/what/is/happéning/?what=1&2%20b#how-aboüt-this=1a': 1,
    'HTtpS://a.example.com/what/is/happening/?what=1&2%20b#how-about-this=1af&2f%20b': 1,
    'https://example.com/?what=1#how-about-this=1&2%20baf': 1,
    'https://example.com?what=1#how-about-this=1&2%20baf': 1,
    '<test>http://example7.com</test>': 1,
    'https://<test>': 0,
    'https://[test]': 0,
    'http://"test"': 0,
    'http://\'test\'': 0,
    '[https://example8.com/what/is/this.php?what=1]': 1,
    '[and http://example9.com?what=1&other=3#and-thing=2]': 1,
    '<what>https://example10.com#and-thing=2 "</about>': 1,
    'abc<this["https://example11.com/what/is#and-thing=2?whoami=23&where=1"]that>def': 1,
    'sdflkf[what](https://example12.com/who/what.php?whoami=1#whatami=2)?am=hi': 1,
    '<or>http://examplehttp://15.badc</that>': 2,
    'https://a.example.com/one.html?url=http://example.com/inside/of/another?=http://': 2,
    '[https://a.example.com/one.html?url=http://example.com/inside/of/another?=](http://a.example.com)': 3,
}
for url_str, num_urls in _test_url_strs.items():
    assert len(list(find_all_urls(url_str))) == num_urls, (
        f'{url_str} does not contain {num_urls} urls')
