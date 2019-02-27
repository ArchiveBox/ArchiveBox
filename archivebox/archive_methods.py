import os

from functools import wraps
from collections import defaultdict
from datetime import datetime

from index import (
    wget_output_path,
    parse_json_link_index,
    write_link_index,
    patch_index_title_hack,
)
from config import (
    OUTPUT_DIR,
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
    CHROME_USER_DATA_DIR,
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
    check_link_structure,
    run, PIPE, DEVNULL,
)


_RESULTS_TOTALS = {   # globals are bad, mmkay
    'skipped': 0,
    'succeded': 0,
    'failed': 0,
}


def archive_link(link_dir, link, overwrite=True):
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    check_link_structure(link)

    try:
        update_existing = os.path.exists(link_dir)
        if update_existing:
            link = {
                **parse_json_link_index(link_dir),
                **link,
            }
        else:
            os.makedirs(link_dir)
        
        print_link_status_line(link_dir, link, update_existing)

        if FETCH_FAVICON:
            link = fetch_favicon(link_dir, link, overwrite=overwrite)

        if FETCH_TITLE:
            link = fetch_title(link_dir, link, overwrite=overwrite)

        if FETCH_WGET:
            link = fetch_wget(link_dir, link, overwrite=overwrite)

        if FETCH_PDF:
            link = fetch_pdf(link_dir, link, overwrite=overwrite)

        if FETCH_SCREENSHOT:
            link = fetch_screenshot(link_dir, link, overwrite=overwrite)

        if FETCH_DOM:
            link = fetch_dom(link_dir, link, overwrite=overwrite)

        if SUBMIT_ARCHIVE_DOT_ORG:
            link = archive_dot_org(link_dir, link, overwrite=overwrite)

        if FETCH_GIT:
            link = fetch_git(link_dir, link, overwrite=overwrite)

        if FETCH_MEDIA:
            link = fetch_media(link_dir, link, overwrite=overwrite)

        write_link_index(link_dir, link)

    except Exception as err:
        print('    ! Failed to archive link: {}: {}'.format(err.__class__.__name__, err))
    
    return link

def print_link_status_line(link_dir, link, update_existing):
    print('[{symbol_color}{symbol}{reset}] [{now}] "{title}"\n    {blue}{url}{reset}'.format(
        symbol='*' if update_existing else '+',
        symbol_color=ANSI['black' if update_existing else 'green'],
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        **{**link, 'title': link['title'] or link['url']},
        **ANSI,
    ))

    print('    > {}{}'.format(pretty_path(link_dir), '' if update_existing else ' (new)'))
    # if link['type']:
    #     print('      i {}'.format(link['type']))



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
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)  # index.html
        end()
        output = wget_output_path(link, look_in=domain_dir)

        output_tail = ['          ' + line for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:] if line.strip()]

        # parse out number of files downloaded from "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        files_downloaded = (
            int(output_tail[-1].strip().split(' ', 2)[1] or 0)
            if 'Downloaded:' in output_tail[-1]
            else 0
        )

        # Check for common failure cases
        if result.returncode > 0 and files_downloaded < 1:
            print('        Got wget response code {}:'.format(result.returncode))
            print('\n'.join(output_tail))
            if b'403: Forbidden' in result.stderr:
                raise Exception('403 Forbidden (try changing WGET_USER_AGENT)')
            if b'404: Not Found' in result.stderr:
                raise Exception('404 Not Found')
            if b'ERROR 500: Internal Server Error' in result.stderr:
                raise Exception('500 Internal Server Error')
            raise Exception('Got an error from the server')
    except Exception as e:
        end()

        # to let the user copy-paste the command and run it safely we have
        # to quote some of the arguments that could have spaces in them
        quoted_cmd = ' '.join(CMD)
        quoted_cmd = quoted_cmd.replace(WGET_USER_AGENT, '"{}"'.format(WGET_USER_AGENT))
        if COOKIES_FILE:
            quoted_cmd = quoted_cmd.replace(COOKIES_FILE, '"{}"'.format(COOKIES_FILE))

        print('        {}Some resources were skipped: {}{}'.format(ANSI['lightyellow'], e, ANSI['reset']))
        print('        Run to see full output:')
        print('            cd {};'.format(link_dir))
        print('            {}'.format(quoted_cmd))
        output = e
    return {
        'cmd': CMD,
        'output': output,
    }


@attach_result_to_link('pdf')
def fetch_pdf(link_dir, link, timeout=TIMEOUT, user_data_dir=CHROME_USER_DATA_DIR):
    """print PDF of site to file using chrome --headless"""

    if link['type'] in ('PDF', 'image'):
        return {'output': wget_output_path(link)}
    
    if os.path.exists(os.path.join(link_dir, 'output.pdf')):
        return {'output': 'output.pdf', 'status': 'skipped'}

    CMD = [
        *chrome_headless(user_data_dir=user_data_dir),
        '--print-to-pdf',
        '--hide-scrollbars',
        '--timeout={}'.format((timeout) * 1000),
        *(() if CHECK_SSL_VALIDITY else ('--disable-web-security', '--ignore-certificate-errors')),
        link['url']
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)  # output.pdf
        end()
        if result.returncode:
            print('     ', (result.stderr or result.stdout).decode())
            raise Exception('Failed to print PDF')
        chmod_file('output.pdf', cwd=link_dir)
        output = 'output.pdf'
    except Exception as e:
        end()
        print('        {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        print('        Run to see full output:')
        print('            cd {};'.format(link_dir))
        print('            {}'.format(' '.join(CMD)))
        output = e

    return {
        'cmd': CMD,
        'output': output,
    }

@attach_result_to_link('screenshot')
def fetch_screenshot(link_dir, link, timeout=TIMEOUT, user_data_dir=CHROME_USER_DATA_DIR, resolution=RESOLUTION):
    """take screenshot of site using chrome --headless"""

    if link['type'] in ('PDF', 'image'):
        return {'output': wget_output_path(link)}
    
    if os.path.exists(os.path.join(link_dir, 'screenshot.png')):
        return {'output': 'screenshot.png', 'status': 'skipped'}

    CMD = [
        *chrome_headless(user_data_dir=user_data_dir),
        '--screenshot',
        '--window-size={}'.format(resolution),
        '--hide-scrollbars',
        '--timeout={}'.format((timeout) * 1000),
        *(() if CHECK_SSL_VALIDITY else ('--disable-web-security', '--ignore-certificate-errors')),
        # '--full-page',   # TODO: make this actually work using ./bin/screenshot fullPage: true
        link['url'],
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout)  # sreenshot.png
        end()
        if result.returncode:
            print('     ', (result.stderr or result.stdout).decode())
            raise Exception('Failed to take screenshot')
        chmod_file('screenshot.png', cwd=link_dir)
        output = 'screenshot.png'
    except Exception as e:
        end()
        print('        {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        print('        Run to see full output:')
        print('            cd {};'.format(link_dir))
        print('            {}'.format(' '.join(CMD)))
        output = e

    return {
        'cmd': CMD,
        'output': output,
    }
    
@attach_result_to_link('dom')
def fetch_dom(link_dir, link, timeout=TIMEOUT, user_data_dir=CHROME_USER_DATA_DIR):
    """print HTML of site to file using chrome --dump-html"""

    if link['type'] in ('PDF', 'image'):
        return {'output': wget_output_path(link)}
    
    output_path = os.path.join(link_dir, 'output.html')

    if os.path.exists(output_path):
        return {'output': 'output.html', 'status': 'skipped'}

    CMD = [
        *chrome_headless(user_data_dir=user_data_dir),
        '--dump-dom',
        '--timeout={}'.format((timeout) * 1000),
        link['url']
    ]
    end = progress(timeout, prefix='      ')
    try:
        with open(output_path, 'w+') as f:
            result = run(CMD, stdout=f, stderr=PIPE, cwd=link_dir, timeout=timeout)  # output.html
        end()
        if result.returncode:
            print('     ', (result.stderr).decode())
            raise Exception('Failed to fetch DOM')
        chmod_file('output.html', cwd=link_dir)
        output = 'output.html'
    except Exception as e:
        end()
        print('        {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        print('        Run to see full output:')
        print('            cd {};'.format(link_dir))
        print('            {}'.format(' '.join(CMD)))
        output = e

    return {
        'cmd': CMD,
        'output': output,
    }

@attach_result_to_link('archive_org')
def archive_dot_org(link_dir, link, timeout=TIMEOUT):
    """submit site to archive.org for archiving via their service, save returned archive url"""

    path = os.path.join(link_dir, 'archive.org.txt')
    if os.path.exists(path):
        archive_org_url = open(path, 'r').read().strip()
        return {'output': archive_org_url, 'status': 'skipped'}

    submit_url = 'https://web.archive.org/save/{}'.format(link['url'])

    success = False
    CMD = [
        CURL_BINARY,
        '--location',
        '--head',
        '--user-agent', 'ArchiveBox/{} (+https://github.com/pirate/ArchiveBox/)'.format(GIT_SHA),
        '--max-time', str(timeout),
        '--get',
        *(() if CHECK_SSL_VALIDITY else ('--insecure',)),
        submit_url,
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=DEVNULL, cwd=link_dir, timeout=timeout)  # archive.org.txt
        end()

        # Parse archive.org response headers
        headers = defaultdict(list)

        # lowercase all the header names and store in dict
        for header in result.stdout.splitlines():
            if b':' not in header or not header.strip():
                continue
            name, val = header.decode().split(':', 1)
            headers[name.lower().strip()].append(val.strip())

        # Get successful archive url in "content-location" header or any errors
        content_location = headers['content-location']
        errors = headers['x-archive-wayback-runtime-error']

        if content_location:
            saved_url = 'https://web.archive.org{}'.format(content_location[0])
            success = True
        elif len(errors) == 1 and 'RobotAccessControlException' in errors[0]:
            output = submit_url
            # raise Exception('Archive.org denied by {}/robots.txt'.format(domain(link['url'])))
        elif errors:
            raise Exception(', '.join(errors))
        else:
            raise Exception('Failed to find "content-location" URL header in Archive.org response.')
    except Exception as e:
        end()
        print('        {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        print('        Run to see full output:')
        print('            {}'.format(' '.join(CMD)))
        output = e

    if success:
        with open(os.path.join(link_dir, 'archive.org.txt'), 'w', encoding='utf-8') as f:
            f.write(saved_url)
        chmod_file('archive.org.txt', cwd=link_dir)
        output = saved_url

    return {
        'cmd': CMD,
        'output': output,
    }

@attach_result_to_link('favicon')
def fetch_favicon(link_dir, link, timeout=TIMEOUT):
    """download site favicon from google's favicon api"""

    if os.path.exists(os.path.join(link_dir, 'favicon.ico')):
        return {'output': 'favicon.ico', 'status': 'skipped'}

    CMD = [
        CURL_BINARY,
        '--max-time', str(timeout),
        *(() if CHECK_SSL_VALIDITY else ('--insecure',)),
        'https://www.google.com/s2/favicons?domain={}'.format(domain(link['url'])),
    ]
    fout = open('{}/favicon.ico'.format(link_dir), 'w')
    end = progress(timeout, prefix='      ')
    try:
        run(CMD, stdout=fout, stderr=DEVNULL, cwd=link_dir, timeout=timeout)  # favicon.ico
        fout.close()
        end()
        chmod_file('favicon.ico', cwd=link_dir)
        output = 'favicon.ico'
    except Exception as e:
        fout.close()
        end()
        print('        {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        print('        Run to see full output:')
        print('            {}'.format(' '.join(CMD)))
        output = e

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

    end = progress(timeout, prefix='      ')
    try:
        title = fetch_page_title(link['url'], timeout=timeout, progress=False)
        end()
        output = title
    except Exception as e:
        end()
        print('        {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        output = e

    # titles should show up in the global index immediatley for better UX,
    # do a hacky immediate replacement to add them in as we're archiving
    # TODO: figure out how to do this without gnarly string replacement
    if title:
        link['title'] = title
        patch_index_title_hack(link['url'], title)

    return {
        'cmd': 'fetch_page_title("{}")'.format(link['url']),
        'output': output,
    }

@attach_result_to_link('media')
def fetch_media(link_dir, link, timeout=MEDIA_TIMEOUT, overwrite=False):
    """Download playlists or individual video, audio, and subtitles using youtube-dl"""


    # import ipdb; ipdb.set_trace()
    output = os.path.join(link_dir, 'media')
    already_done = os.path.exists(output)  # and os.listdir(output)
    if already_done and not overwrite:
        return {'output': 'media', 'status': 'skipped'}

    os.makedirs(output, exist_ok=True)
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
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=output, timeout=timeout + 1)  # audio/audio.mp3
        chmod_file('media', cwd=link_dir)
        output = 'media'
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
                print('        got youtubedl response code {}:'.format(result.returncode))
                print(result.stderr)
                raise Exception('Failed to download media')
    except Exception as e:
        end()
        print('        {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        print('        Run to see full output:')
        print('            cd {};'.format(link_dir))
        print('            {}'.format(' '.join(CMD)))
        output = e

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
        or link['type'] == 'git'
    )
    
    if not url_is_clonable:
        return {'output': None, 'status': 'skipped'}

    git_dir = os.path.join(link_dir, 'git')
    if os.path.exists(git_dir):
        return {'output': 'git', 'status': 'skipped'}

    os.makedirs(git_dir, exist_ok=True)
    output = 'git'
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
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=git_dir, timeout=timeout + 1)  # git/<reponame>
        end()

        if result.returncode == 128:
            # ignore failed re-download when the folder already exists
            pass
        elif result.returncode > 0:
            print('        got git response code {}:'.format(result.returncode))
            raise Exception('Failed git download')
    except Exception as e:
        end()
        print('        {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        print('        Run to see full output:')
        print('            cd {};'.format(link_dir))
        print('            {}'.format(' '.join(CMD)))
        output = e

    return {
        'cmd': CMD,
        'output': output,
    }

def chrome_headless(binary=CHROME_BINARY, user_data_dir=CHROME_USER_DATA_DIR):
    args = [binary, '--headless']  # '--disable-gpu'
    if not CHROME_SANDBOX:
        args.append('--no-sandbox')
    default_profile = os.path.expanduser('~/Library/Application Support/Google/Chrome')
    if user_data_dir:
        args.append('--user-data-dir={}'.format(user_data_dir))
    elif os.path.exists(default_profile):
        args.append('--user-data-dir={}'.format(default_profile))
    return args
