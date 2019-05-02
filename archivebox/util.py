import os
import re
import sys
import time

from urllib.request import Request, urlopen
from urllib.parse import urlparse, quote
from decimal import Decimal
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

from config import (
    ANSI,
    TERM_WIDTH,
    SOURCES_DIR,
    ARCHIVE_DIR,
    OUTPUT_PERMISSIONS,
    TIMEOUT,
    SHOW_PROGRESS,
    FETCH_TITLE,
    ARCHIVE_DIR_NAME,
    CHECK_SSL_VALIDITY,
    WGET_USER_AGENT,
    CHROME_OPTIONS,
)
from logs import pretty_path

### Parsing Helpers

# Url Parsing: https://docs.python.org/3/library/urllib.parse.html#url-parsing
scheme = lambda url: urlparse(url).scheme
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

short_ts = lambda ts: ts.split('.')[0]
urlencode = lambda s: quote(s, encoding='utf-8', errors='replace')

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
    # 99.999% of the time, URLs ending in these extensions are static files
    # that can be downloaded as-is, not html pages that need to be rendered
    'gif', 'jpeg', 'jpg', 'png', 'tif', 'tiff', 'wbmp', 'ico', 'jng', 'bmp',
    'svg', 'svgz', 'webp', 'ps', 'eps', 'ai',
    'mp3', 'mp4', 'm4a', 'mpeg', 'mpg', 'mkv', 'mov', 'webm', 'm4v', 'flv', 'wmv', 'avi', 'ogg', 'ts', 'm3u8',
    'pdf', 'txt', 'rtf', 'rtfd', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx',
    'atom', 'rss', 'css', 'js', 'json',
    'dmg', 'iso', 'img',
    'rar', 'war', 'hqx', 'zip', 'gz', 'bz2', '7z',

    # Less common extensions to consider adding later
    # jar, swf, bin, com, exe, dll, deb
    # ear, hqx, eot, wmlc, kml, kmz, cco, jardiff, jnlp, run, msi, msp, msm, 
    # pl pm, prc pdb, rar, rpm, sea, sit, tcl tk, der, pem, crt, xpi, xspf,
    # ra, mng, asx, asf, 3gpp, 3gp, mid, midi, kar, jad, wml, htc, mml

    # These are always treated as pages, not as static files, never add them:
    # html, htm, shtml, xhtml, xml, aspx, php, cgi
}

### Checks & Tests

def check_link_structure(link):
    """basic sanity check invariants to make sure the data is valid"""
    assert isinstance(link, dict)
    assert isinstance(link.get('url'), str)
    assert len(link['url']) > 2
    assert len(re.findall(URL_REGEX, link['url'])) == 1
    if 'history' in link:
        assert isinstance(link['history'], dict), 'history must be a Dict'
        for key, val in link['history'].items():
            assert isinstance(key, str)
            assert isinstance(val, list), 'history must be a Dict[str, List], got: {}'.format(link['history'])
    
def check_links_structure(links):
    """basic sanity check invariants to make sure the data is valid"""
    assert isinstance(links, list)
    if links:
        check_link_structure(links[0])

def check_url_parsing_invariants():
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

def save_stdin_source(raw_text):
    if not os.path.exists(SOURCES_DIR):
        os.makedirs(SOURCES_DIR)

    ts = str(datetime.now().timestamp()).split('.', 1)[0]

    source_path = os.path.join(SOURCES_DIR, '{}-{}.txt'.format('stdin', ts))

    with open(source_path, 'w', encoding='utf-8') as f:
        f.write(raw_text)

    return source_path

def save_remote_source(url, timeout=TIMEOUT):
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

def fetch_page_title(url, timeout=10, progress=SHOW_PROGRESS):
    """Attempt to guess a page's title by downloading the html"""
    
    if not FETCH_TITLE:
        return None

    try:
        if progress:
            sys.stdout.write('.')
            sys.stdout.flush()

        html = download_url(url, timeout=timeout)

        match = re.search(HTML_TITLE_REGEX, html)
        return match.group(1).strip() if match else None
    except Exception as err:  # noqa
        # print('[!] Failed to fetch title because of {}: {}'.format(
        #     err.__class__.__name__,
        #     err,
        # ))
        return None

def wget_output_path(link):
    """calculate the path to the wgetted .html file, since wget may
    adjust some paths to be different than the base_url path.

    See docs on wget --adjust-extension (-E)
    """

    if is_static_file(link['url']):
        return without_scheme(without_fragment(link['url']))

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
    link_dir = os.path.join(ARCHIVE_DIR, link['timestamp'])
    full_path = without_fragment(without_query(path(link['url']))).strip('/')
    search_dir = os.path.join(
        link_dir,
        domain(link['url']),
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
                    path_from_link_dir = search_dir.split(link_dir)[-1].strip('/')
                    return os.path.join(path_from_link_dir, html_files[0])

        # Move up one directory level
        search_dir = search_dir.rsplit('/', 1)[0]

        if search_dir == link_dir:
            break

    return None


### String Manipulation & Logging Helpers

def str_between(string, start, end=None):
    """(<abc>12345</def>, <abc>, </def>)  ->  12345"""

    content = string.split(start, 1)[-1]
    if end is not None:
        content = content.rsplit(end, 1)[0]

    return content


### Link Helpers

def merge_links(a, b):
    """deterministically merge two links, favoring longer field values over shorter,
    and "cleaner" values over worse ones.
    """
    longer = lambda key: (a[key] if len(a[key]) > len(b[key]) else b[key]) if (a[key] and b[key]) else (a[key] or b[key])
    earlier = lambda key: a[key] if a[key] < b[key] else b[key]
    
    url = longer('url')
    longest_title = longer('title')
    cleanest_title = a['title'] if '://' not in (a['title'] or '') else b['title']
    return {
        'url': url,
        'timestamp': earlier('timestamp'),
        'title': longest_title if '://' not in (longest_title or '') else cleanest_title,
        'tags': longer('tags'),
        'sources': list(set(a.get('sources', []) + b.get('sources', []))),
    }

def is_static_file(url):
    """Certain URLs just point to a single static file, and 
       don't need to be re-archived in many formats
    """

    # TODO: the proper way is with MIME type detection, not using extension
    return extension(url) in STATICFILE_EXTENSIONS

def derived_link_info(link):
    """extend link info with the archive urls and other derived data"""

    url = link['url']

    to_date_str = lambda ts: datetime.fromtimestamp(Decimal(ts)).strftime('%Y-%m-%d %H:%M')

    extended_info = {
        **link,
        'link_dir': '{}/{}'.format(ARCHIVE_DIR_NAME, link['timestamp']),
        'bookmarked_date': to_date_str(link['timestamp']),
        'updated_date': to_date_str(link['updated']) if 'updated' in link else None,
        'domain': domain(url),
        'path': path(url),
        'basename': basename(url),
        'extension': extension(url),
        'base_url': base_url(url),
        'is_static': is_static_file(url),
        'is_archived': os.path.exists(os.path.join(
            ARCHIVE_DIR,
            link['timestamp'],
            domain(url),
        )),
        'num_outputs': len([entry for entry in latest_output(link).values() if entry]),
    }

    # Archive Method Output URLs
    extended_info.update({
        'index_url': 'index.html',
        'favicon_url': 'favicon.ico',
        'google_favicon_url': 'https://www.google.com/s2/favicons?domain={domain}'.format(**extended_info),
        'archive_url': wget_output_path(link),
        'warc_url': 'warc',
        'pdf_url': 'output.pdf',
        'screenshot_url': 'screenshot.png',
        'dom_url': 'output.html',
        'archive_org_url': 'https://web.archive.org/web/{base_url}'.format(**extended_info),
        'git_url': 'git',
        'media_url': 'media',
    })
    # static binary files like PDF and images are handled slightly differently.
    # they're just downloaded once and aren't archived separately multiple times, 
    # so the wget, screenshot, & pdf urls should all point to the same file
    if is_static_file(url):
        extended_info.update({
            'title': basename(url),
            'archive_url': base_url(url),
            'pdf_url': base_url(url),
            'screenshot_url': base_url(url),
            'dom_url': base_url(url),
        })

    return extended_info


def latest_output(link, status=None):
    """get the latest output that each archive method produced for link"""
    
    latest = {
        'title': None,
        'favicon': None,
        'wget': None,
        'warc': None,
        'pdf': None,
        'screenshot': None,
        'dom': None,
        'git': None,
        'media': None,
        'archive_org': None,
    }
    for archive_method in latest.keys():
        # get most recent succesful result in history for each archive method
        history = link.get('history', {}).get(archive_method) or []
        history = filter(lambda result: result['output'], reversed(history))
        if status is not None:
            history = filter(lambda result: result['status'] == status, history)

        history = list(history)
        if history:
            latest[archive_method] = history[0]['output']

    return latest


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


def progress_bar(seconds, prefix):
    """show timer in the form of progress bar, with percentage and seconds remaining"""
    chunk = '█' if sys.stdout.encoding == 'UTF-8' else '#'
    chunks = TERM_WIDTH - len(prefix) - 20  # number of progress chunks to show (aka max bar width)
    try:
        for s in range(seconds * chunks):
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

class TimedProgress:
    """Show a progress bar and measure elapsed time until .end() is called"""

    def __init__(self, seconds, prefix=''):
        if SHOW_PROGRESS:
            self.p = Process(target=progress_bar, args=(seconds, prefix))
            self.p.start()

        self.stats = {
            'start_ts': datetime.now(),
            'end_ts': None,
            'duration': None,
        }

    def end(self):
        """immediately end progress, clear the progressbar line, and save end_ts"""

        end_ts = datetime.now()
        self.stats.update({
            'end_ts': end_ts,
            'duration': (end_ts - self.stats['start_ts']).seconds,
        })

        if SHOW_PROGRESS:
            # protect from double termination
            #if p is None or not hasattr(p, 'kill'):
            #    return
            if self.p is not None:
                self.p.terminate()
            self.p = None

            sys.stdout.write('\r{}{}\r'.format((' ' * TERM_WIDTH), ANSI['reset']))  # clear whole terminal line
            sys.stdout.flush()

def download_url(url, timeout=TIMEOUT):
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

def chmod_file(path, cwd='.', permissions=OUTPUT_PERMISSIONS, timeout=30):
    """chmod -R <permissions> <cwd>/<path>"""

    if not os.path.exists(os.path.join(cwd, path)):
        raise Exception('Failed to chmod: {} does not exist (did the previous step fail?)'.format(path))

    chmod_result = run(['chmod', '-R', permissions, path], cwd=cwd, stdout=DEVNULL, stderr=PIPE, timeout=timeout)
    if chmod_result.returncode == 1:
        print('     ', chmod_result.stderr.decode())
        raise Exception('Failed to chmod {}/{}'.format(cwd, path))


def chrome_args(**options):
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
