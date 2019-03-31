import os

from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from datetime import datetime

from .schema import Link, ArchiveResult, ArchiveOutput
from .index import (
    write_link_index,
    patch_links_index,
    load_json_link_index,
)
from .config import (
    CURL_BINARY,
    GIT_BINARY,
    WGET_BINARY,
    YOUTUBEDL_BINARY,
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
    SUBMIT_ARCHIVE_DOT_ORG,
    TIMEOUT,
    MEDIA_TIMEOUT,
    GIT_DOMAINS,
    VERSION,
    WGET_USER_AGENT,
    CHECK_SSL_VALIDITY,
    COOKIES_FILE,
    CURL_VERSION,
    WGET_VERSION,
    CHROME_VERSION,
    GIT_VERSION,
    YOUTUBEDL_VERSION,
    WGET_AUTO_COMPRESSION,
)
from .util import (
    enforce_types,
    domain,
    extension,
    without_query,
    without_fragment,
    fetch_page_title,
    is_static_file,
    TimedProgress,
    chmod_file,
    wget_output_path,
    chrome_args,
    run, PIPE, DEVNULL,
)
from .logs import (
    log_link_archiving_started,
    log_link_archiving_finished,
    log_archive_method_started,
    log_archive_method_finished,
)


class ArchiveError(Exception):
    def __init__(self, message, hints=None):
        super().__init__(message)
        self.hints = hints


@enforce_types
def archive_link(link: Link, link_dir: Optional[str]=None) -> Link:
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    ARCHIVE_METHODS = (
        ('title', should_fetch_title, fetch_title),
        ('favicon', should_fetch_favicon, fetch_favicon),
        ('wget', should_fetch_wget, fetch_wget),
        ('pdf', should_fetch_pdf, fetch_pdf),
        ('screenshot', should_fetch_screenshot, fetch_screenshot),
        ('dom', should_fetch_dom, fetch_dom),
        ('git', should_fetch_git, fetch_git),
        ('media', should_fetch_media, fetch_media),
        ('archive_org', should_fetch_archive_dot_org, archive_dot_org),
    )
    
    link_dir = link_dir or link.link_dir
    try:
        is_new = not os.path.exists(link_dir)
        if is_new:
            os.makedirs(link_dir)

        link = load_json_link_index(link, link_dir=link_dir)
        log_link_archiving_started(link, link_dir, is_new)
        link = link.overwrite(updated=datetime.now())
        stats = {'skipped': 0, 'succeeded': 0, 'failed': 0}

        for method_name, should_run, method_function in ARCHIVE_METHODS:
            try:
                if method_name not in link.history:
                    link.history[method_name] = []
                
                if should_run(link, link_dir):
                    log_archive_method_started(method_name)

                    result = method_function(link=link, link_dir=link_dir)

                    link.history[method_name].append(result)

                    stats[result.status] += 1
                    log_archive_method_finished(result)
                else:
                    stats['skipped'] += 1
            except Exception as e:
                raise Exception('Exception in archive_methods.fetch_{}(Link(url={}))'.format(
                    method_name,
                    link.url,
                )) from e

        # print('    ', stats)

        # If any changes were made, update the link index json and html
        write_link_index(link, link_dir=link.link_dir)
        
        was_changed = stats['succeeded'] or stats['failed']
        if was_changed:
            patch_links_index(link)

        log_link_archiving_finished(link, link.link_dir, is_new, stats)

    except KeyboardInterrupt:
        try:
            write_link_index(link, link_dir=link.link_dir)
        except:
            pass
        raise

    except Exception as err:
        print('    ! Failed to archive link: {}: {}'.format(err.__class__.__name__, err))
        raise

    return link


### Archive Method Functions

@enforce_types
def should_fetch_title(link: Link, link_dir: Optional[str]=None) -> bool:
    # if link already has valid title, skip it
    if link.title and not link.title.lower().startswith('http'):
        return False

    if is_static_file(link.url):
        return False

    return FETCH_TITLE

@enforce_types
def fetch_title(link: Link, link_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """try to guess the page's title from its content"""

    output: ArchiveOutput = None
    cmd = [
        CURL_BINARY,
        link.url,
        '|',
        'grep',
        '<title',
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        output = fetch_page_title(link.url, timeout=timeout, progress=False)
        if not output:
            raise ArchiveError('Unable to detect page title')
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=link_dir,
        cmd_version=CURL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )


@enforce_types
def should_fetch_favicon(link: Link, link_dir: Optional[str]=None) -> bool:
    link_dir = link_dir or link.link_dir
    if os.path.exists(os.path.join(link_dir, 'favicon.ico')):
        return False

    return FETCH_FAVICON
    
@enforce_types
def fetch_favicon(link: Link, link_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download site favicon from google's favicon api"""

    link_dir = link_dir or link.link_dir
    output: ArchiveOutput = 'favicon.ico'
    cmd = [
        CURL_BINARY,
        '--max-time', str(timeout),
        '--location',
        '--output', str(output),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
        'https://www.google.com/s2/favicons?domain={}'.format(domain(link.url)),
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        run(cmd, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)
        chmod_file(output, cwd=link_dir)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=link_dir,
        cmd_version=CURL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )

@enforce_types
def should_fetch_wget(link: Link, link_dir: Optional[str]=None) -> bool:
    output_path = wget_output_path(link)
    link_dir = link_dir or link.link_dir
    if output_path and os.path.exists(os.path.join(link_dir, output_path)):
        return False

    return FETCH_WGET


@enforce_types
def fetch_wget(link: Link, link_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download full site using wget"""

    link_dir = link_dir or link.link_dir
    if FETCH_WARC:
        warc_dir = os.path.join(link_dir, 'warc')
        os.makedirs(warc_dir, exist_ok=True)
        warc_path = os.path.join('warc', str(int(datetime.now().timestamp())))

    # WGET CLI Docs: https://www.gnu.org/software/wget/manual/wget.html
    output: ArchiveOutput = None
    cmd = [
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
        *([] if FETCH_WARC else ['--timestamping']),
        *(['--warc-file={}'.format(warc_path)] if FETCH_WARC else []),
        *(['--page-requisites'] if FETCH_WGET_REQUISITES else []),
        *(['--user-agent={}'.format(WGET_USER_AGENT)] if WGET_USER_AGENT else []),
        *(['--load-cookies', COOKIES_FILE] if COOKIES_FILE else []),
        *(['--compression=auto'] if WGET_AUTO_COMPRESSION else []),
        *([] if CHECK_SSL_VALIDITY else ['--no-check-certificate', '--no-hsts']),
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)
        output = wget_output_path(link)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:]
            if line.strip()
        ]
        files_downloaded = (
            int(output_tail[-1].strip().split(' ', 2)[1] or 0)
            if 'Downloaded:' in output_tail[-1]
            else 0
        )

        # Check for common failure cases
        if result.returncode > 0 and files_downloaded < 1:
            hints = (
                'Got wget response code: {}.'.format(result.returncode),
                *output_tail,
            )
            if b'403: Forbidden' in result.stderr:
                raise ArchiveError('403 Forbidden (try changing WGET_USER_AGENT)', hints)
            if b'404: Not Found' in result.stderr:
                raise ArchiveError('404 Not Found', hints)
            if b'ERROR 500: Internal Server Error' in result.stderr:
                raise ArchiveError('500 Internal Server Error', hints)
            raise ArchiveError('Got an error from the server', hints)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=link_dir,
        cmd_version=WGET_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )

@enforce_types
def should_fetch_pdf(link: Link, link_dir: Optional[str]=None) -> bool:
    link_dir = link_dir or link.link_dir
    if is_static_file(link.url):
        return False
    
    if os.path.exists(os.path.join(link_dir, 'output.pdf')):
        return False

    return FETCH_PDF


@enforce_types
def fetch_pdf(link: Link, link_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """print PDF of site to file using chrome --headless"""

    link_dir = link_dir or link.link_dir
    output: ArchiveOutput = 'output.pdf'
    cmd = [
        *chrome_args(TIMEOUT=timeout),
        '--print-to-pdf',
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)

        if result.returncode:
            hints = (result.stderr or result.stdout).decode()
            raise ArchiveError('Failed to print PDF', hints)
        
        chmod_file('output.pdf', cwd=link_dir)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=link_dir,
        cmd_version=CHROME_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )

@enforce_types
def should_fetch_screenshot(link: Link, link_dir: Optional[str]=None) -> bool:
    link_dir = link_dir or link.link_dir
    if is_static_file(link.url):
        return False
    
    if os.path.exists(os.path.join(link_dir, 'screenshot.png')):
        return False

    return FETCH_SCREENSHOT

@enforce_types
def fetch_screenshot(link: Link, link_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """take screenshot of site using chrome --headless"""
    
    link_dir = link_dir or link.link_dir
    output: ArchiveOutput = 'screenshot.png'
    cmd = [
        *chrome_args(TIMEOUT=timeout),
        '--screenshot',
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)

        if result.returncode:
            hints = (result.stderr or result.stdout).decode()
            raise ArchiveError('Failed to take screenshot', hints)

        chmod_file(output, cwd=link_dir)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=link_dir,
        cmd_version=CHROME_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )

@enforce_types
def should_fetch_dom(link: Link, link_dir: Optional[str]=None) -> bool:
    link_dir = link_dir or link.link_dir
    if is_static_file(link.url):
        return False
    
    if os.path.exists(os.path.join(link_dir, 'output.html')):
        return False

    return FETCH_DOM
    
@enforce_types
def fetch_dom(link: Link, link_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """print HTML of site to file using chrome --dump-html"""

    link_dir = link_dir or link.link_dir
    output: ArchiveOutput = 'output.html'
    output_path = os.path.join(link_dir, str(output))
    cmd = [
        *chrome_args(TIMEOUT=timeout),
        '--dump-dom',
        link.url
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        with open(output_path, 'w+') as f:
            result = run(cmd, stdout=f, stderr=PIPE, cwd=link_dir, timeout=timeout)

        if result.returncode:
            hints = result.stderr.decode()
            raise ArchiveError('Failed to fetch DOM', hints)

        chmod_file(output, cwd=link_dir)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=link_dir,
        cmd_version=CHROME_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )

@enforce_types
def should_fetch_git(link: Link, link_dir: Optional[str]=None) -> bool:
    link_dir = link_dir or link.link_dir
    if is_static_file(link.url):
        return False

    if os.path.exists(os.path.join(link_dir, 'git')):
        return False

    is_clonable_url = (
        (domain(link.url) in GIT_DOMAINS)
        or (extension(link.url) == 'git')
    )
    if not is_clonable_url:
        return False

    return FETCH_GIT


@enforce_types
def fetch_git(link: Link, link_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download full site using git"""

    link_dir = link_dir or link.link_dir
    output: ArchiveOutput = 'git'
    output_path = os.path.join(link_dir, str(output))
    os.makedirs(output_path, exist_ok=True)
    cmd = [
        GIT_BINARY,
        'clone',
        '--mirror',
        '--recursive',
        *([] if CHECK_SSL_VALIDITY else ['-c', 'http.sslVerify=false']),
        without_query(without_fragment(link.url)),
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, stdout=PIPE, stderr=PIPE, cwd=output_path, timeout=timeout + 1)

        if result.returncode == 128:
            # ignore failed re-download when the folder already exists
            pass
        elif result.returncode > 0:
            hints = 'Got git response code: {}.'.format(result.returncode)
            raise ArchiveError('Failed git download', hints)

    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=link_dir,
        cmd_version=GIT_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )


@enforce_types
def should_fetch_media(link: Link, link_dir: Optional[str]=None) -> bool:
    link_dir = link_dir or link.link_dir

    if is_static_file(link.url):
        return False

    if os.path.exists(os.path.join(link_dir, 'media')):
        return False

    return FETCH_MEDIA

@enforce_types
def fetch_media(link: Link, link_dir: Optional[str]=None, timeout: int=MEDIA_TIMEOUT) -> ArchiveResult:
    """Download playlists or individual video, audio, and subtitles using youtube-dl"""

    link_dir = link_dir or link.link_dir
    output: ArchiveOutput = 'media'
    output_path = os.path.join(link_dir, str(output))
    os.makedirs(output_path, exist_ok=True)
    cmd = [
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
        *([] if CHECK_SSL_VALIDITY else ['--no-check-certificate']),
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, stdout=PIPE, stderr=PIPE, cwd=output_path, timeout=timeout + 1)
        chmod_file(output, cwd=link_dir)
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
                    'Got youtube-dl response code: {}.'.format(result.returncode),
                    *result.stderr.decode().split('\n'),
                )
                raise ArchiveError('Failed to download media', hints)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=link_dir,
        cmd_version=YOUTUBEDL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )


@enforce_types
def should_fetch_archive_dot_org(link: Link, link_dir: Optional[str]=None) -> bool:
    link_dir = link_dir or link.link_dir
    if is_static_file(link.url):
        return False

    if os.path.exists(os.path.join(link_dir, 'archive.org.txt')):
        # if open(path, 'r').read().strip() != 'None':
        return False

    return SUBMIT_ARCHIVE_DOT_ORG

@enforce_types
def archive_dot_org(link: Link, link_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """submit site to archive.org for archiving via their service, save returned archive url"""

    link_dir = link_dir or link.link_dir
    output: ArchiveOutput = 'archive.org.txt'
    archive_org_url = None
    submit_url = 'https://web.archive.org/save/{}'.format(link.url)
    cmd = [
        CURL_BINARY,
        '--location',
        '--head',
        '--user-agent', 'ArchiveBox/{} (+https://github.com/pirate/ArchiveBox/)'.format(VERSION),  # be nice to the Archive.org people and show them where all this ArchiveBox traffic is coming from
        '--max-time', str(timeout),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
        submit_url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, stdout=PIPE, stderr=DEVNULL, cwd=link_dir, timeout=timeout)
        content_location, errors = parse_archive_dot_org_response(result.stdout)
        if content_location:
            archive_org_url = 'https://web.archive.org{}'.format(content_location[0])
        elif len(errors) == 1 and 'RobotAccessControlException' in errors[0]:
            archive_org_url = None
            # raise ArchiveError('Archive.org denied by {}/robots.txt'.format(domain(link.url)))
        elif errors:
            raise ArchiveError(', '.join(errors))
        else:
            raise ArchiveError('Failed to find "content-location" URL header in Archive.org response.')
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    if output and not isinstance(output, Exception):
        # instead of writing None when archive.org rejects the url write the
        # url to resubmit it to archive.org. This is so when the user visits
        # the URL in person, it will attempt to re-archive it, and it'll show the
        # nicer error message explaining why the url was rejected if it fails.
        archive_org_url = archive_org_url or submit_url
        with open(os.path.join(link_dir, str(output)), 'w', encoding='utf-8') as f:
            f.write(archive_org_url)
        chmod_file('archive.org.txt', cwd=link_dir)
        output = archive_org_url

    return ArchiveResult(
        cmd=cmd,
        pwd=link_dir,
        cmd_version=CURL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )

@enforce_types
def parse_archive_dot_org_response(response: bytes) -> Tuple[List[str], List[str]]:
    # Parse archive.org response headers
    headers: Dict[str, List[str]] = defaultdict(list)

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
