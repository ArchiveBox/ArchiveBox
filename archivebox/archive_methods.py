import os

from functools import wraps
from collections import defaultdict
from datetime import datetime

from index import (
    parse_json_link_index,
    write_link_index,
    update_main_index,
)
from config import (
    CURL_BINARY,
    GIT_BINARY,
    WGET_BINARY,
    YOUTUBEDL_BINARY,
    CHROME_BINARY,
    FETCH_FAVICON,
    FETCH_TITLE,
    FETCH_WGET,
    FETCH_WGET_REQUISITES,
    FETCH_PDF,
    FETCH_SCREENSHOT,
    FETCH_DOM,
    FETCH_WARC,
    FETCH_GIT,
    FETCH_MEDIA,
    RESOLUTION,
    CHECK_SSL_VALIDITY,
    SUBMIT_ARCHIVE_DOT_ORG,
    COOKIES_FILE,
    WGET_USER_AGENT,
    CHROME_USER_AGENT,
    CHROME_USER_DATA_DIR,
    CHROME_HEADLESS,
    CHROME_SANDBOX,
    TIMEOUT,
    MEDIA_TIMEOUT,
    ANSI,
    ARCHIVE_DIR,
    GIT_DOMAINS,
    GIT_SHA,
)
from util import (
    domain,
    without_query,
    without_fragment,
    fetch_page_title,
    progress,
    chmod_file,
    pretty_path,
    print_error_hints,
    check_link_structure,
    wget_output_path,
    run, PIPE, DEVNULL,
)


_RESULTS_TOTALS = {   # globals are bad, mmkay
    'skipped': 0,
    'succeded': 0,
    'failed': 0,
}

def load_link_index(link_dir, link):
    """check for an existing link archive in the given directory, 
       and load+merge it into the given link dict
    """
    is_new = not os.path.exists(link_dir)
    if is_new:
        os.makedirs(link_dir)
    else:
        link = {
            **parse_json_link_index(link_dir),
            **link,
        }

    check_link_structure(link)
    print_link_status_line(link_dir, link, is_new)

    return link


class ArchiveError(Exception):
    def __init__(self, message, hints=None):
        super().__init__(message)
        self.hints = hints


def archive_link(link_dir, link, overwrite=True):
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    ARCHIVE_METHODS = (
        (FETCH_TITLE, fetch_title),
        (FETCH_FAVICON, fetch_favicon),
        (FETCH_WGET, fetch_wget),
        (FETCH_PDF, fetch_pdf),
        (FETCH_SCREENSHOT, fetch_screenshot),
        (FETCH_DOM, fetch_dom),
        (FETCH_GIT, fetch_git),
        (FETCH_MEDIA, fetch_media),
        (SUBMIT_ARCHIVE_DOT_ORG, archive_dot_org),
    )
    active_methods = [method for toggle, method in ARCHIVE_METHODS if toggle]
    
    try:
        link = load_link_index(link_dir, link)

        for archive_method in active_methods:
            archive_method(link_dir, link, overwrite=overwrite)


        write_link_index(link_dir, link)
        update_main_index(link)

    except Exception as err:
        print('    ! Failed to archive link: {}: {}'.format(err.__class__.__name__, err))
    
    return link

def print_link_status_line(link_dir, link, is_new):
    print('[{symbol_color}{symbol}{reset}] [{now}] "{title}"\n    {blue}{url}{reset}'.format(
        symbol='+' if is_new else '*',
        symbol_color=ANSI['green' if is_new else 'black'],
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        **{**link, 'title': link['title'] or link['url']},
        **ANSI,
    ))

    print('    > {}{}'.format(pretty_path(link_dir), ' (new)' if is_new else ''))



def attach_result_to_link(method):
    """
    Instead of returning a result={output:'...', status:'success'} object,
    attach that result to the links's history & latest fields, then return
    the updated link object.
    """
    def decorator(fetch_func):
        @wraps(fetch_func)
        def timed_fetch_func(link_dir, link, overwrite=False, **kwargs):
            # initialize methods and history json field on link
            link['latest'] = link.get('latest') or {}
            link['latest'][method] = link['latest'].get(method) or None
            link['history'] = link.get('history') or {}
            link['history'][method] = link['history'].get(method) or []

            start_ts = datetime.now().timestamp()

            # if a valid method output is already present, dont run the fetch function
            if link['latest'][method] and not overwrite:
                print('      √ {}'.format(method))
                result = None
            else:
                print('      > {}'.format(method))
                result = fetch_func(link_dir, link, **kwargs)

            end_ts = datetime.now().timestamp()
            duration = str(end_ts * 1000 - start_ts * 1000).split('.')[0]

            # append a history item recording fail/success
            history_entry = {
                'timestamp': str(start_ts).split('.')[0],
            }
            if result is None:
                history_entry['status'] = 'skipped'
            elif isinstance(result.get('output'), Exception):
                history_entry['status'] = 'failed'
                history_entry['duration'] = duration
                history_entry.update(result or {})
                link['history'][method].append(history_entry)
            else:
                history_entry['status'] = 'succeded'
                history_entry['duration'] = duration
                history_entry.update(result or {})
                link['history'][method].append(history_entry)
                link['latest'][method] = result['output']

            _RESULTS_TOTALS[history_entry['status']] += 1
            
            return link
        return timed_fetch_func
    return decorator


@attach_result_to_link('wget')
def fetch_wget(link_dir, link, requisites=FETCH_WGET_REQUISITES, warc=FETCH_WARC, timeout=TIMEOUT):
    """download full site using wget"""

    domain_dir = os.path.join(link_dir, domain(link['url']))
    existing_file = wget_output_path(link)
    if os.path.exists(domain_dir) and existing_file:
        return {'output': existing_file, 'status': 'skipped'}

    if warc:
        warc_dir = os.path.join(link_dir, 'warc')
        os.makedirs(warc_dir, exist_ok=True)
        warc_path = os.path.join('warc', str(int(datetime.now().timestamp())))

    # WGET CLI Docs: https://www.gnu.org/software/wget/manual/wget.html
    CMD = [
        WGET_BINARY,
        # '--server-response',  # print headers for better error parsing
        '--no-verbose',
        '--adjust-extension',
        '--convert-links',
        '--force-directories',
        '--backup-converted',
        '--span-hosts',
        '--no-parent',
        '-e', 'robots=off',
        '--restrict-file-names=unix',
        '--timeout={}'.format(timeout),
        *(() if warc else ('--timestamping',)),
        *(('--warc-file={}'.format(warc_path),) if warc else ()),
        *(('--page-requisites',) if FETCH_WGET_REQUISITES else ()),
        *(('--user-agent={}'.format(WGET_USER_AGENT),) if WGET_USER_AGENT else ()),
        *(('--load-cookies', COOKIES_FILE) if COOKIES_FILE else ()),
        *((() if CHECK_SSL_VALIDITY else ('--no-check-certificate', '--no-hsts'))),
        link['url'],
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)
        end()
        output = wget_output_path(link)

        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:]
            if line.strip()
        ]

        # parse out number of files downloaded from "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        files_downloaded = (
            int(output_tail[-1].strip().split(' ', 2)[1] or 0)
            if 'Downloaded:' in output_tail[-1]
            else 0
        )

        # Check for common failure cases
        if result.returncode > 0 and files_downloaded < 1:
            hints = (
                'Got wget response code {}:\n'.format(result.returncode),
                *output_tail,
            )
            if b'403: Forbidden' in result.stderr:
                raise ArchiveError('403 Forbidden (try changing WGET_USER_AGENT)', hints)
            if b'404: Not Found' in result.stderr:
                raise ArchiveError('404 Not Found', hints)
            if b'ERROR 500: Internal Server Error' in result.stderr:
                raise ArchiveError('500 Internal Server Error', hints)
            raise ArchiveError('Got an error from the server', hints)
    except Exception as e:
        end()
        output = e
        print_error_hints(cmd=CMD, pwd=link_dir, err=e)

    return {
        'cmd': CMD,
        'output': output,
    }


@attach_result_to_link('pdf')
def fetch_pdf(link_dir, link, timeout=TIMEOUT, **chrome_kwargs):
    """print PDF of site to file using chrome --headless"""

    if is_static_file(link['url']):
        return {'output': wget_output_path(link), 'status': 'skipped'}
    
    output = 'output.pdf'
    if os.path.exists(os.path.join(link_dir, output)):
        return {'output': output, 'status': 'skipped'}

    CMD = [
        *chrome_headless(timeout=timeout, **chrome_kwargs),
        '--print-to-pdf',
        link['url']
    ]
    end = progress(timeout, prefix='      ')
    hints = None
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)
        end()

        if result.returncode:
            hints = (result.stderr or result.stdout).decode()
            raise ArchiveError('Failed to print PDF', hints)
        
        chmod_file('output.pdf', cwd=link_dir)
    except Exception as e:
        end()
        output = e
        print_error_hints(cmd=CMD, pwd=link_dir, err=e, hints=hints)

    return {
        'cmd': CMD,
        'output': output,
    }

@attach_result_to_link('screenshot')
def fetch_screenshot(link_dir, link, timeout=TIMEOUT, **chrome_kwargs):
    """take screenshot of site using chrome --headless"""

    if is_static_file(link['url']):
        return {'output': wget_output_path(link), 'status': 'skipped'}
    
    output = 'screenshot.png'
    if os.path.exists(os.path.join(link_dir, output)):
        return {'output': output, 'status': 'skipped'}

    CMD = [
        *chrome_headless(timeout=timeout, **chrome_kwargs),
        '--screenshot',
        link['url'],
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)
        end()
        if result.returncode:
            hints = (result.stderr or result.stdout).decode()
            raise ArchiveError('Failed to take screenshot', hints)

        chmod_file(output, cwd=link_dir)
    except Exception as e:
        end()
        output = e
        print_error_hints(cmd=CMD, pwd=link_dir, err=e)

    return {
        'cmd': CMD,
        'output': output,
    }
    
@attach_result_to_link('dom')
def fetch_dom(link_dir, link, timeout=TIMEOUT, **chrome_kwargs):
    """print HTML of site to file using chrome --dump-html"""

    if is_static_file(link['url']):
        return {'output': wget_output_path(link), 'status': 'skipped'}
    
    output = 'output.html'
    if os.path.exists(os.path.join(link_dir, output)):
        return {'output': output, 'status': 'skipped'}

    CMD = [
        *chrome_headless(timeout=timeout, **chrome_kwargs),
        '--dump-dom',
        link['url']
    ]
    end = progress(timeout, prefix='      ')
    try:
        with open(output_path, 'w+') as f:
            result = run(CMD, stdout=f, stderr=PIPE, cwd=link_dir, timeout=timeout)
        end()
        if result.returncode:
            hints = result.stderr.decode()
            raise ArchiveError('Failed to fetch DOM', hints)

        chmod_file(output, cwd=link_dir)
    except Exception as e:
        end()
        output = e
        print_error_hints(cmd=CMD, pwd=link_dir, err=e)

    return {
        'cmd': CMD,
        'output': output,
    }

def parse_archive_dot_org_response(response):
    # Parse archive.org response headers
    headers = defaultdict(list)

    # lowercase all the header names and store in dict
    for header in response.splitlines():
        if b':' not in header or not header.strip():
            continue
        name, val = header.decode().split(':', 1)
        headers[name.lower().strip()].append(val.strip())

    # Get successful archive url in "content-location" header or any errors
    content_location = headers['content-location']
    errors = headers['x-archive-wayback-runtime-error']
    return content_location, errors

@attach_result_to_link('archive_org')
def archive_dot_org(link_dir, link, timeout=TIMEOUT):
    """submit site to archive.org for archiving via their service, save returned archive url"""

    output = 'archive.org.txt'
    archive_org_url = None

    path = os.path.join(link_dir, output)
    if os.path.exists(path):
        archive_org_url = open(path, 'r').read().strip()
        return {'output': archive_org_url, 'status': 'skipped'}

    submit_url = 'https://web.archive.org/save/{}'.format(link['url'])
    CMD = [
        CURL_BINARY,
        '--location',
        '--head',
        '--user-agent', 'ArchiveBox/{} (+https://github.com/pirate/ArchiveBox/)'.format(GIT_SHA),  # be nice to the Archive.org people and show them where all this ArchiveBox traffic is coming from
        '--max-time', str(timeout),
        *(() if CHECK_SSL_VALIDITY else ('--insecure',)),
        submit_url,
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=DEVNULL, cwd=link_dir, timeout=timeout)
        end()
        content_location, errors = parse_archive_dot_org_response(result.stdout)
        if content_location:
            archive_org_url = 'https://web.archive.org{}'.format(content_location[0])
        elif len(errors) == 1 and 'RobotAccessControlException' in errors[0]:
            archive_org_url = None
            # raise ArchiveError('Archive.org denied by {}/robots.txt'.format(domain(link['url'])))
        elif errors:
            raise ArchiveError(', '.join(errors))
        else:
            raise ArchiveError('Failed to find "content-location" URL header in Archive.org response.')
    except Exception as e:
        end()
        output = e
        print_error_hints(cmd=CMD, pwd=link_dir, err=e)

    if not isinstance(output, Exception):
        # instead of writing None when archive.org rejects the url write the
        # url to resubmit it to archive.org. This is so when the user visits
        # the URL in person, it will attempt to re-archive it, and it'll show the
        # nicer error message explaining why the url was rejected if it fails.
        archive_org_url = archive_org_url or submit_url
        with open(os.path.join(link_dir, output), 'w', encoding='utf-8') as f:
            f.write(archive_org_url)
        chmod_file('archive.org.txt', cwd=link_dir)
        output = archive_org_url

    return {
        'cmd': CMD,
        'output': output,
    }

@attach_result_to_link('favicon')
def fetch_favicon(link_dir, link, timeout=TIMEOUT):
    """download site favicon from google's favicon api"""

    output = 'favicon.ico'
    if os.path.exists(os.path.join(link_dir, output)):
        return {'output': output, 'status': 'skipped'}

    CMD = [
        CURL_BINARY,
        '--max-time', str(timeout),
        '--location',
        '--output', output,
        *(() if CHECK_SSL_VALIDITY else ('--insecure',)),
        'https://www.google.com/s2/favicons?domain={}'.format(domain(link['url'])),
    ]
    end = progress(timeout, prefix='      ')
    try:
        run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)
        end()
        chmod_file(output, cwd=link_dir)
    except Exception as e:
        end()
        output = e
        print_error_hints(cmd=CMD, pwd=link_dir, err=e)

    return {
        'cmd': CMD,
        'output': output,
    }

@attach_result_to_link('title')
def fetch_title(link_dir, link, timeout=TIMEOUT):
    """try to guess the page's title from its content"""

    # if link already has valid title, skip it
    if link['title'] and not link['title'].lower().startswith('http'):
        return {'output': link['title'], 'status': 'skipped'}

    if is_static_file(link['url']):
        return {'output': None, 'status': 'skipped'}

    end = progress(timeout, prefix='      ')
    try:
        title = fetch_page_title(link['url'], timeout=timeout, progress=False)
        end()
        output = title
    except Exception as e:
        end()
        output = e
        print('        {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))

    if title and title.strip():
        link['title'] = title
        output = title

    return {
        'cmd': 'fetch_page_title("{}")'.format(link['url']),
        'output': output,
    }

@attach_result_to_link('media')
def fetch_media(link_dir, link, timeout=MEDIA_TIMEOUT, overwrite=False):
    """Download playlists or individual video, audio, and subtitles using youtube-dl"""

    output = 'media'
    output_path = os.path.join(link_dir, 'media')

    if os.path.exists(output_path) and not overwrite:
        return {'output': output, 'status': 'skipped'}

    os.makedirs(output_path, exist_ok=True)
    CMD = [
        YOUTUBEDL_BINARY,
        '--write-description',
        '--write-info-json',
        '--write-annotations',
        '--yes-playlist',
        '--write-thumbnail',
        '--no-call-home',
        '--no-check-certificate',
        '--user-agent',
        '--all-subs',
        '--extract-audio',
        '--keep-video',
        '--ignore-errors',
        '--geo-bypass',
        '--audio-format', 'mp3',
        '--audio-quality', '320K',
        '--embed-thumbnail',
        '--add-metadata',
        *(() if CHECK_SSL_VALIDITY else ('--no-check-certificate',)),
        link['url'],
    ]

    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=output_path, timeout=timeout + 1)
        chmod_file(output, cwd=link_dir)
        end()
        if result.returncode:
            if (b'ERROR: Unsupported URL' in result.stderr
                or b'HTTP Error 404' in result.stderr
                or b'HTTP Error 403' in result.stderr
                or b'URL could be a direct video link' in result.stderr
                or b'Unable to extract container ID' in result.stderr):
                # These happen too frequently on non-media pages to warrant printing to console
                pass
            else:
                hints = (
                    'got youtubedl response code {}:'.format(result.returncode)),
                    *result.stderr.decode().split('\n'),
                )
                raise ArchiveError('Failed to download media', hints)
    except Exception as e:
        end()
        output = e
        print_error_hints(cmd=CMD, pwd=link_dir, err=e)

    return {
        'cmd': CMD,
        'output': output,
    }


@attach_result_to_link('git')
def fetch_git(link_dir, link, timeout=TIMEOUT):
    """download full site using git"""

    url_is_clonable = (
        domain(link['url']) in GIT_DOMAINS
        or link['url'].endswith('.git')
    )
    if not url_is_clonable or is_static_file(link['url']):
        return {'output': None, 'status': 'skipped'}

    output = 'git'
    output_path = os.path.join(link_dir, 'git')

    if os.path.exists(output_path):
        return {'output': output, 'status': 'skipped'}

    os.makedirs(output_path, exist_ok=True)
    CMD = [
        GIT_BINARY,
        'clone',
        '--mirror',
        '--recursive',
        *(() if CHECK_SSL_VALIDITY else ('-c', 'http.sslVerify=false')),
        without_query(without_fragment(link['url'])),
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=output_path, timeout=timeout + 1)
        end()

        if result.returncode == 128:
            # ignore failed re-download when the folder already exists
            pass
        elif result.returncode > 0:
            hints = 'got git response code {}:'.format(result.returncode)
            raise ArchiveError('Failed git download', hints)
    except Exception as e:
        end()
        output = e
        print_error_hints(cmd=CMD, pwd=link_dir, err=e)

    return {
        'cmd': CMD,
        'output': output,
    }

def chrome_headless(binary=CHROME_BINARY, user_data_dir=CHROME_USER_DATA_DIR, headless=CHROME_HEADLESS, sandbox=CHROME_SANDBOX, check_ssl_validity=CHECK_SSL_VALIDITY, user_agent=CHROME_USER_AGENT, resolution=RESOLUTION, timeout=TIMEOUT):
    global CACHED_USER_DATA_DIR
    user_data_dir = user_data_dir or CACHED_USER_DATA_DIR
    cmd_args = [binary]

    if headless:
        cmd_args += ('--headless',)
    
    if not sandbox:
        # dont use GPU or sandbox when running inside docker container
        cmd_args += ('--no-sandbox', '--disable-gpu')

    if not check_ssl_validity:
        cmd_args += ('--disable-web-security', '--ignore-certificate-errors')

    if user_agent:
        cmd_args += ('--user-agent={}'.format(user_agent),)

    if resolution:
        cmd_args += ('--window-size={}'.format(RESOLUTION),)

    if timeout:
        cmd_args += ('--timeout={}'.format((timeout) * 1000),)

    # Find chrome user data directory
    default_profile_paths = (
        '~/.config/chromium',
        '~/.config/google-chrome',
        '~/.config/google-chrome-beta',
        '~/.config/google-chrome-unstable',
        '~/Library/Application Support/Chromium',
        '~/Library/Application Support/Google/Chrome',
        '~/Library/Application Support/Google/Chrome Canary',
        '~/AppData/Local/Chromium/User Data',
        '~/AppData/Local/Google/Chrome/User Data',
        '~/AppData/Local/Google/Chrome SxS/User Data',
    )
    if user_data_dir:
        cmd_args.append('--user-data-dir={}'.format(user_data_dir))
    else:
        for path in default_profile_paths:
            full_path = os.path.expanduser(path)
            if os.path.exists(full_path):
                CACHED_USER_DATA_DIR = full_path
                cmd_args.append('--user-data-dir={}'.format(full_path))
                break
    
    return cmd_args


CACHED_USER_DATA_DIR = CHROME_USER_DATA_DIR
