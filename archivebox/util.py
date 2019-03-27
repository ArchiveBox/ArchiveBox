import os
import re
import sys
import time

from json import JSONEncoder
from typing import List, Optional, Any
from inspect import signature, _empty
from functools import wraps
from hashlib import sha256
from urllib.request import Request, urlopen
from urllib.parse import urlparse, quote, unquote
from html import escape, unescape
from datetime import datetime
from multiprocessing import Process
from subprocess import (
    Popen,
    PIPE,
    DEVNULL, 
    CompletedProcess,
    TimeoutExpired,
    CalledProcessError,
)

from base32_crockford import encode as base32_encode

from schema import Link
from config import (
    ANSI,
    TERM_WIDTH,
    SOURCES_DIR,
    OUTPUT_PERMISSIONS,
    TIMEOUT,
    SHOW_PROGRESS,
    FETCH_TITLE,
    CHECK_SSL_VALIDITY,
    WGET_USER_AGENT,
    CHROME_OPTIONS,
    PYTHON_PATH,
)
from logs import pretty_path

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
fuzzy_url = lambda url: without_trailing_slash(without_www(without_scheme(url.lower())))

short_ts = lambda ts: str(parse_date(ts).timestamp()).split('.')[0]
ts_to_date = lambda ts: parse_date(ts).strftime('%Y-%m-%d %H:%M')
ts_to_iso = lambda ts: parse_date(ts).isoformat()

urlencode = lambda s: s and quote(s, encoding='utf-8', errors='replace')
urldecode = lambda s: s and unquote(s)
htmlencode = lambda s: s and escape(s, quote=True)
htmldecode = lambda s: s and unescape(s)

hashurl = lambda url: base32_encode(int(sha256(base_url(url).encode('utf-8')).hexdigest(), 16))[:20]

URL_REGEX = re.compile(
    r'http[s]?://'                    # start matching from allowed schemes
    r'(?:[a-zA-Z]|[0-9]'              # followed by allowed alphanum characters
    r'|[$-_@.&+]|[!*\(\),]'           #    or allowed symbols
    r'|(?:%[0-9a-fA-F][0-9a-fA-F]))'  #    or allowed unicode bytes
    r'[^\]\[\(\)<>\""\'\s]+',         # stop parsing at these symbols
    re.IGNORECASE,
)
HTML_TITLE_REGEX = re.compile(
    r'<title.*?>'                      # start matching text after <title> tag
    r'(.[^<>]+)',                      # get everything up to these symbols
    re.IGNORECASE | re.MULTILINE | re.DOTALL | re.UNICODE,
)
STATICFILE_EXTENSIONS = {
    # 99.999% of the time, URLs ending in these extentions are static files
    # that can be downloaded as-is, not html pages that need to be rendered
    'gif', 'jpeg', 'jpg', 'png', 'tif', 'tiff', 'wbmp', 'ico', 'jng', 'bmp',
    'svg', 'svgz', 'webp', 'ps', 'eps', 'ai',
    'mp3', 'mp4', 'm4a', 'mpeg', 'mpg', 'mkv', 'mov', 'webm', 'm4v', 
    'flv', 'wmv', 'avi', 'ogg', 'ts', 'm3u8',
    'pdf', 'txt', 'rtf', 'rtfd', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx',
    'atom', 'rss', 'css', 'js', 'json',
    'dmg', 'iso', 'img',
    'rar', 'war', 'hqx', 'zip', 'gz', 'bz2', '7z',

    # Less common extensions to consider adding later
    # jar, swf, bin, com, exe, dll, deb
    # ear, hqx, eot, wmlc, kml, kmz, cco, jardiff, jnlp, run, msi, msp, msm, 
    # pl pm, prc pdb, rar, rpm, sea, sit, tcl tk, der, pem, crt, xpi, xspf,
    # ra, mng, asx, asf, 3gpp, 3gp, mid, midi, kar, jad, wml, htc, mml

    # Thse are always treated as pages, not as static files, never add them:
    # html, htm, shtml, xhtml, xml, aspx, php, cgi
}



### Checks & Tests

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
                annotation = _empty

            if annotation is not _empty and annotation.__class__ is type:
                if not isinstance(arg_val, annotation):
                    raise TypeError(
                        '{}(..., {}: {}) got unexpected {} argument {}={}'.format(
                            func.__name__,
                            arg_key,
                            annotation.__name__,
                            type(arg_val).__name__,
                            arg_key,
                            arg_val,
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


def check_url_parsing_invariants() -> None:
    """Check that plain text regex URL parsing works as expected"""

    # this is last-line-of-defense to make sure the URL_REGEX isn't
    # misbehaving, as the consequences could be disastrous and lead to many
    # incorrect/badly parsed links being added to the archive

    test_urls = '''
    https://example1.com/what/is/happening.html?what=1#how-about-this=1
    https://example2.com/what/is/happening/?what=1#how-about-this=1
    HTtpS://example3.com/what/is/happening/?what=1#how-about-this=1f
    https://example4.com/what/is/happening.html
    https://example5.com/
    https://example6.com

    <test>http://example7.com</test>
    [https://example8.com/what/is/this.php?what=1]
    [and http://example9.com?what=1&other=3#and-thing=2]
    <what>https://example10.com#and-thing=2 "</about>
    abc<this["https://example11.com/what/is#and-thing=2?whoami=23&where=1"]that>def
    sdflkf[what](https://example12.com/who/what.php?whoami=1#whatami=2)?am=hi
    example13.bada
    and example14.badb
    <or>htt://example15.badc</that>
    '''
    # print('\n'.join(re.findall(URL_REGEX, test_urls)))
    assert len(re.findall(URL_REGEX, test_urls)) == 12


### Random Helpers

@enforce_types
def save_stdin_source(raw_text: str) -> str:
    if not os.path.exists(SOURCES_DIR):
        os.makedirs(SOURCES_DIR)

    ts = str(datetime.now().timestamp()).split('.', 1)[0]

    source_path = os.path.join(SOURCES_DIR, '{}-{}.txt'.format('stdin', ts))

    with open(source_path, 'w', encoding='utf-8') as f:
        f.write(raw_text)

    return source_path


@enforce_types
def save_remote_source(url: str, timeout: int=TIMEOUT) -> str:
    """download a given url's content into output/sources/domain-<timestamp>.txt"""

    if not os.path.exists(SOURCES_DIR):
        os.makedirs(SOURCES_DIR)

    ts = str(datetime.now().timestamp()).split('.', 1)[0]

    source_path = os.path.join(SOURCES_DIR, '{}-{}.txt'.format(domain(url), ts))

    print('{}[*] [{}] Downloading {}{}'.format(
        ANSI['green'],
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        url,
        ANSI['reset'],
    ))
    timer = TimedProgress(timeout, prefix='      ')
    try:
        downloaded_xml = download_url(url, timeout=timeout)
        timer.end()
    except Exception as e:
        timer.end()
        print('{}[!] Failed to download {}{}\n'.format(
            ANSI['red'],
            url,
            ANSI['reset'],
        ))
        print('    ', e)
        raise SystemExit(1)

    with open(source_path, 'w', encoding='utf-8') as f:
        f.write(downloaded_xml)

    print('    > {}'.format(pretty_path(source_path)))

    return source_path


@enforce_types
def fetch_page_title(url: str, timeout: int=10, progress: bool=SHOW_PROGRESS) -> Optional[str]:
    """Attempt to guess a page's title by downloading the html"""
    
    if not FETCH_TITLE:
        return None

    try:
        if progress:
            sys.stdout.write('.')
            sys.stdout.flush()

        html = download_url(url, timeout=timeout)

        match = re.search(HTML_TITLE_REGEX, html)
        return htmldecode(match.group(1).strip()) if match else None
    except Exception as err:  # noqa
        # print('[!] Failed to fetch title because of {}: {}'.format(
        #     err.__class__.__name__,
        #     err,
        # ))
        return None


@enforce_types
def wget_output_path(link: Link) -> Optional[str]:
    """calculate the path to the wgetted .html file, since wget may
    adjust some paths to be different than the base_url path.

    See docs on wget --adjust-extension (-E)
    """

    if is_static_file(link.url):
        return without_scheme(without_fragment(link.url))

    # Wget downloads can save in a number of different ways depending on the url:
    #    https://example.com
    #       > output/archive/<timestamp>/example.com/index.html
    #    https://example.com?v=zzVa_tX1OiI
    #       > output/archive/<timestamp>/example.com/index.html?v=zzVa_tX1OiI.html
    #    https://www.example.com/?v=zzVa_tX1OiI
    #       > output/archive/<timestamp>/example.com/index.html?v=zzVa_tX1OiI.html

    #    https://example.com/abc
    #       > output/archive/<timestamp>/example.com/abc.html
    #    https://example.com/abc/
    #       > output/archive/<timestamp>/example.com/abc/index.html
    #    https://example.com/abc?v=zzVa_tX1OiI.html
    #       > output/archive/<timestamp>/example.com/abc?v=zzVa_tX1OiI.html
    #    https://example.com/abc/?v=zzVa_tX1OiI.html
    #       > output/archive/<timestamp>/example.com/abc/index.html?v=zzVa_tX1OiI.html

    #    https://example.com/abc/test.html
    #       > output/archive/<timestamp>/example.com/abc/test.html
    #    https://example.com/abc/test?v=zzVa_tX1OiI
    #       > output/archive/<timestamp>/example.com/abc/test?v=zzVa_tX1OiI.html
    #    https://example.com/abc/test/?v=zzVa_tX1OiI
    #       > output/archive/<timestamp>/example.com/abc/test/index.html?v=zzVa_tX1OiI.html

    # There's also lots of complexity around how the urlencoding and renaming
    # is done for pages with query and hash fragments or extensions like shtml / htm / php / etc

    # Since the wget algorithm for -E (appending .html) is incredibly complex
    # and there's no way to get the computed output path from wget
    # in order to avoid having to reverse-engineer how they calculate it,
    # we just look in the output folder read the filename wget used from the filesystem
    full_path = without_fragment(without_query(path(link.url))).strip('/')
    search_dir = os.path.join(
        link.link_dir,
        domain(link.url),
        full_path,
    )

    for _ in range(4):
        if os.path.exists(search_dir):
            if os.path.isdir(search_dir):
                html_files = [
                    f for f in os.listdir(search_dir)
                    if re.search(".+\\.[Hh][Tt][Mm][Ll]?$", f, re.I | re.M)
                ]
                if html_files:
                    path_from_link_dir = search_dir.split(link.link_dir)[-1].strip('/')
                    return os.path.join(path_from_link_dir, html_files[0])

        # Move up one directory level
        search_dir = search_dir.rsplit('/', 1)[0]

        if search_dir == link.link_dir:
            break

    return None


@enforce_types
def read_js_script(script_name: str) -> str:
    script_path = os.path.join(PYTHON_PATH, 'scripts', script_name)

    with open(script_path, 'r') as f:
        return f.read().split('// INFO BELOW HERE')[0].strip()


### String Manipulation & Logging Helpers

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
    
    if isinstance(date, datetime):
        return date

    if date is None:
        return None
    
    if isinstance(date, (float, int)):
        date = str(date)

    if isinstance(date, str):
        if date.replace('.', '').isdigit():
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

        if '-' in date:
            try:
                return datetime.fromisoformat(date)
            except Exception:
                try:
                    return datetime.strptime(date, '%Y-%m-%d %H:%M')
                except Exception:
                    pass
    
    raise ValueError('Tried to parse invalid date! {}'.format(date))



### Link Helpers

@enforce_types
def merge_links(a: Link, b: Link) -> Link:
    """deterministially merge two links, favoring longer field values over shorter,
    and "cleaner" values over worse ones.
    """
    assert a.base_url == b.base_url, 'Cannot merge two links with different URLs'

    url = a.url if len(a.url) > len(b.url) else b.url

    possible_titles = [
        title
        for title in (a.title, b.title)
        if title and title.strip() and '://' not in title
    ]
    title = None
    if len(possible_titles) == 2:
        title = max(possible_titles, key=lambda t: len(t))
    elif len(possible_titles) == 1:
        title = possible_titles[0]

    timestamp = (
        a.timestamp
        if float(a.timestamp or 0) < float(b.timestamp or 0) else
        b.timestamp
    )

    tags_set = (
        set(tag.strip() for tag in (a.tags or '').split(','))
        | set(tag.strip() for tag in (b.tags or '').split(','))
    )
    tags = ','.join(tags_set) or None

    sources = list(set(a.sources + b.sources))

    all_methods = (set(a.history.keys()) | set(a.history.keys()))
    history = {
        method: (a.history.get(method) or []) + (b.history.get(method) or [])
        for method in all_methods
    }

    return Link(
        url=url,
        timestamp=timestamp,
        title=title,
        tags=tags,
        sources=sources,
        history=history,
    )


@enforce_types
def is_static_file(url: str) -> bool:
    """Certain URLs just point to a single static file, and 
       don't need to be re-archived in many formats
    """

    # TODO: the proper way is with MIME type detection, not using extension
    return extension(url) in STATICFILE_EXTENSIONS


@enforce_types
def derived_link_info(link: Link) -> dict:
    """extend link info with the archive urls and other derived data"""

    info = link._asdict(extended=True)
    info.update(link.canonical_outputs())

    return info



### Python / System Helpers

def run(*popenargs, input=None, capture_output=False, timeout=None, check=False, **kwargs):
    """Patched of subprocess.run to fix blocking io making timeout=innefective"""

    if input is not None:
        if 'stdin' in kwargs:
            raise ValueError('stdin and input arguments may not both be used.')
        kwargs['stdin'] = PIPE

    if capture_output:
        if ('stdout' in kwargs) or ('stderr' in kwargs):
            raise ValueError('stdout and stderr arguments may not be used '
                             'with capture_output.')
        kwargs['stdout'] = PIPE
        kwargs['stderr'] = PIPE

    with Popen(*popenargs, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except TimeoutExpired:
            process.kill()
            try:
                stdout, stderr = process.communicate(input, timeout=2)
            except:
                pass
            raise TimeoutExpired(popenargs[0][0], timeout)
        except BaseException:
            process.kill()
            # We don't call process.wait() as .__exit__ does that for us.
            raise 
        retcode = process.poll()
        if check and retcode:
            raise CalledProcessError(retcode, process.args,
                                     output=stdout, stderr=stderr)
    return CompletedProcess(process.args, retcode, stdout, stderr)


class TimedProgress:
    """Show a progress bar and measure elapsed time until .end() is called"""

    def __init__(self, seconds, prefix=''):
        if SHOW_PROGRESS:
            self.p = Process(target=progress_bar, args=(seconds, prefix))
            self.p.start()

        self.stats = {'start_ts': datetime.now(), 'end_ts': None}

    def end(self):
        """immediately end progress, clear the progressbar line, and save end_ts"""

        end_ts = datetime.now()
        self.stats['end_ts'] = end_ts
        if SHOW_PROGRESS:
            # protect from double termination
            #if p is None or not hasattr(p, 'kill'):
            #    return
            if self.p is not None:
                self.p.terminate()
            self.p = None

            sys.stdout.write('\r{}{}\r'.format((' ' * TERM_WIDTH()), ANSI['reset']))  # clear whole terminal line
            sys.stdout.flush()


@enforce_types
def progress_bar(seconds: int, prefix: str='') -> None:
    """show timer in the form of progress bar, with percentage and seconds remaining"""
    chunk = '█' if sys.stdout.encoding == 'UTF-8' else '#'
    chunks = TERM_WIDTH() - len(prefix) - 20  # number of progress chunks to show (aka max bar width)
    try:
        for s in range(seconds * chunks):
            chunks = TERM_WIDTH() - len(prefix) - 20
            progress = s / chunks / seconds * 100
            bar_width = round(progress/(100/chunks))

            # ████████████████████           0.9% (1/60sec)
            sys.stdout.write('\r{0}{1}{2}{3} {4}% ({5}/{6}sec)'.format(
                prefix,
                ANSI['green'],
                (chunk * bar_width).ljust(chunks),
                ANSI['reset'],
                round(progress, 1),
                round(s/chunks),
                seconds,
            ))
            sys.stdout.flush()
            time.sleep(1 / chunks)

        # ██████████████████████████████████ 100.0% (60/60sec)
        sys.stdout.write('\r{0}{1}{2}{3} {4}% ({5}/{6}sec)\n'.format(
            prefix,
            ANSI['red'],
            chunk * chunks,
            ANSI['reset'],
            100.0,
            seconds,
            seconds,
        ))
        sys.stdout.flush()
    except KeyboardInterrupt:
        print()
        pass


@enforce_types
def download_url(url: str, timeout: int=TIMEOUT) -> str:
    """Download the contents of a remote url and return the text"""

    req = Request(url, headers={'User-Agent': WGET_USER_AGENT})

    if CHECK_SSL_VALIDITY:
        resp = urlopen(req, timeout=timeout)
    else:
        import ssl
        insecure = ssl._create_unverified_context()
        resp = urlopen(req, timeout=timeout, context=insecure)

    encoding = resp.headers.get_content_charset() or 'utf-8'
    return resp.read().decode(encoding)


@enforce_types
def chmod_file(path: str, cwd: str='.', permissions: str=OUTPUT_PERMISSIONS, timeout: int=30) -> None:
    """chmod -R <permissions> <cwd>/<path>"""

    if not os.path.exists(os.path.join(cwd, path)):
        raise Exception('Failed to chmod: {} does not exist (did the previous step fail?)'.format(path))

    chmod_result = run(['chmod', '-R', permissions, path], cwd=cwd, stdout=DEVNULL, stderr=PIPE, timeout=timeout)
    if chmod_result.returncode == 1:
        print('     ', chmod_result.stderr.decode())
        raise Exception('Failed to chmod {}/{}'.format(cwd, path))


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


class ExtendedEncoder(JSONEncoder):
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

        return JSONEncoder.default(self, obj)
