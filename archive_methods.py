import os

from functools import wraps
from datetime import datetime
from subprocess import run, PIPE, DEVNULL

from index import html_appended_url, parse_json_link_index, write_link_index
from links import links_after_timestamp
from config import (
    ARCHIVE_DIR,
    CHROME_BINARY,
    FETCH_WGET,
    FETCH_WGET_REQUISITES,
    FETCH_PDF,
    FETCH_SCREENSHOT,
    RESOLUTION,
    SUBMIT_ARCHIVE_DOT_ORG,
    FETCH_AUDIO,
    FETCH_VIDEO,
    FETCH_FAVICON,
    WGET_USER_AGENT,
    TIMEOUT,
    ANSI,
)
from util import (
    check_dependencies,
    progress,
    chmod_file,
)


_RESULTS_TOTALS = {   # globals are bad, mmkay
    'skipped': 0,
    'succeded': 0,
    'failed': 0,
}


def archive_links(out_dir, links, export_path, resume=None):
    check_dependencies()

    to_archive = links_after_timestamp(links, resume)
    try:
        for idx, link in enumerate(to_archive):
            out_dir = os.path.join(out_dir, link['timestamp'])
            archive_link(out_dir, link)
    
    except (KeyboardInterrupt, SystemExit, Exception) as e:
        print('{red}[X] Archive update stopped on #{idx} out of {total} links{reset}'.format(
            **ANSI,
            idx=idx,
            total=len(list(to_archive)),
        ))
        print('    Continue where you left off by running:')
        print('       ./archive.py {} {}'.format(
            export_path,
            link['timestamp'],
        ))
        if not isinstance(e, KeyboardInterrupt):
            raise e
        raise SystemExit(1)


def archive_link(out_dir, link, overwrite=False):
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
        with open(os.path.join(out_dir, 'test.txt'), 'w') as f:
            f.write('ffuuuuuuuuck')

    link = {**parse_json_link_index(out_dir), **link}
    log_link_archive(out_dir, link)

    if FETCH_WGET:
        link = fetch_wget(out_dir, link, overwrite=overwrite)

    if FETCH_PDF:
        link = fetch_pdf(out_dir, link, overwrite=overwrite)

    if FETCH_SCREENSHOT:
        link = fetch_screenshot(out_dir, link, overwrite=overwrite)

    if SUBMIT_ARCHIVE_DOT_ORG:
        link = archive_dot_org(out_dir, link, overwrite=overwrite)

    # if FETCH_AUDIO:
    #     link = fetch_audio(out_dir, link, overwrite=overwrite)

    # if FETCH_VIDEO:
    #     link = fetch_video(out_dir, link, overwrite=overwrite)

    if FETCH_FAVICON:
        link = fetch_favicon(out_dir, link, overwrite=overwrite)

    write_link_index(out_dir, link)
    
    return link


def attach_result_to_link(method):
    """
    Instead of returning a result={output:'...', status:'success'} object,
    attach that result to the links's history & latest fields, then return
    the updated link object.
    """
    def decorator(fetch_func):
        @wraps(fetch_func)
        def timed_fetch_func(out_dir, link, overwrite=False, **kwargs):
            # initialize methods and history json field on link
            link['latest'] = link.get('latest') or {}
            link['latest'][method] = link['latest'].get(method) or None
            link['history'] = link.get('history') or {}
            link['history'][method] = link['history'].get(method) or []

            start_ts = datetime.now().timestamp()

            # if a valid method output is already present, dont run the fetch function
            if link['latest'][method] and not overwrite:
                print('    √ Skipping: {}'.format(method))
                result = None
            else:
                print('    - Fetching: {}'.format(method))
                result = fetch_func(out_dir, link, **kwargs)

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
def fetch_wget(out_dir, link, requisites=FETCH_WGET_REQUISITES, timeout=TIMEOUT):
    """download full site using wget"""

    if os.path.exists(os.path.join(out_dir, link['domain'])):
        return {'output': html_appended_url(link), 'status': 'skipped'}

    CMD = [
        *'wget --timestamping --adjust-extension --no-parent'.split(' '),                # Docs: https://www.gnu.org/software/wget/manual/wget.html
        *(('--page-requisites', '--convert-links') if FETCH_WGET_REQUISITES else ()),
        *(('--user-agent="{}"'.format(WGET_USER_AGENT),) if WGET_USER_AGENT else ()),
        link['url'],
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=out_dir, timeout=timeout + 1)  # index.html
        end()
        output = html_appended_url(link)
        if result.returncode > 0:
            print('       got wget response code {}:'.format(result.returncode))
            print('\n'.join('         ' + line for line in (result.stderr or result.stdout).decode().rsplit('\n', 10)[-10:] if line.strip()))
            # raise Exception('Failed to wget download')
    except Exception as e:
        end()
        print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
        print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        output = e

    return {
        'cmd': CMD,
        'output': output,
    }


@attach_result_to_link('pdf')
def fetch_pdf(out_dir, link, timeout=TIMEOUT):
    """print PDF of site to file using chrome --headless"""

    if link['type'] in ('PDF', 'image'):
        return {'output': html_appended_url(link)}
    
    if os.path.exists(os.path.join(out_dir, 'output.pdf')):
        return {'output': 'output.pdf', 'status': 'skipped'}

    CMD = [
        CHROME_BINARY,
        *'--headless --disable-gpu --print-to-pdf'.split(' '),
        link['url']
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=out_dir, timeout=timeout + 1)  # output.pdf
        end()
        if result.returncode:
            print('     ', (result.stderr or result.stdout).decode())
            raise Exception('Failed to print PDF')
        output = 'output.pdf'
    except Exception as e:
        end()
        print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
        print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        output = e

    return {
        'cmd': CMD,
        'output': output,
    }


@attach_result_to_link('screenshot')
def fetch_screenshot(out_dir, link, timeout=TIMEOUT, resolution=RESOLUTION):
    """take screenshot of site using chrome --headless"""

    if link['type'] in ('PDF', 'image'):
        return {'output': html_appended_url(link)}
    
    if os.path.exists(os.path.join(out_dir, 'screenshot.png')):
        return {'output': 'screenshot.png', 'status': 'skipped'}

    CMD = [
        CHROME_BINARY,
        *'--headless --disable-gpu --screenshot'.split(' '),
        '--window-size={}'.format(resolution),
        link['url']
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=out_dir, timeout=timeout + 1)  # sreenshot.png
        end()
        if result.returncode:
            print('     ', (result.stderr or result.stdout).decode())
            raise Exception('Failed to take screenshot')
        chmod_file('screenshot.png', cwd=out_dir)
        output = 'screenshot.png'
    except Exception as e:
        end()
        print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
        print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        output = e

    return {
        'cmd': CMD,
        'output': output,
    }
    

@attach_result_to_link('archive_org')
def archive_dot_org(out_dir, link, timeout=TIMEOUT):
    """submit site to archive.org for archiving via their service, save returned archive url"""

    path = os.path.join(out_dir, 'archive.org.txt')
    if os.path.exists(path):
        archive_org_url = open(path, 'r').read().strip()
        return {'output': archive_org_url, 'status': 'skipped'}

    submit_url = 'https://web.archive.org/save/{}'.format(link['url'].split('?', 1)[0])

    success = False
    CMD = ['curl', '-I', submit_url]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=DEVNULL, cwd=out_dir, timeout=timeout + 1)  # archive.org.txt
        end()

        # Parse archive.org response headers
        headers = result.stdout.splitlines()
        content_location = [h for h in headers if b'Content-Location: ' in h]
        errors = [h for h in headers if h and b'X-Archive-Wayback-Runtime-Error: ' in h]

        if content_location:
            archive_path = content_location[0].split(b'Content-Location: ', 1)[-1].decode('utf-8')
            saved_url = 'https://web.archive.org{}'.format(archive_path)
            success = True

        elif len(errors) == 1 and b'RobotAccessControlException' in errors[0]:
            output = submit_url
            # raise Exception('Archive.org denied by {}/robots.txt'.format(link['domain']))
        elif errors:
            raise Exception(', '.join(e.decode() for e in errors))
        else:
            raise Exception('Failed to find "Content-Location" URL header in Archive.org response.')
    except Exception as e:
        end()
        print('       Visit url to see output:', ' '.join(CMD))
        print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        output = e

    if success:
        with open(os.path.join(out_dir, 'archive.org.txt'), 'w', encoding='utf-8') as f:
            f.write(saved_url)
        chmod_file('archive.org.txt', cwd=out_dir)
        output = saved_url

    return {
        'cmd': CMD,
        'output': output,
    }

@attach_result_to_link('favicon')
def fetch_favicon(out_dir, link, timeout=TIMEOUT):
    """download site favicon from google's favicon api"""

    if os.path.exists(os.path.join(out_dir, 'favicon.ico')):
        return {'output': 'favicon.ico', 'status': 'skipped'}

    CMD = ['curl', 'https://www.google.com/s2/favicons?domain={domain}'.format(**link)]
    fout = open('{}/favicon.ico'.format(out_dir), 'w')
    end = progress(timeout, prefix='      ')
    try:
        run(CMD, stdout=fout, stderr=DEVNULL, cwd=out_dir, timeout=timeout + 1)  # favicon.ico
        fout.close()
        end()
        chmod_file('favicon.ico', cwd=out_dir)
        output = 'favicon.ico'
    except Exception as e:
        fout.close()
        end()
        print('       Run to see full output:', ' '.join(CMD))
        print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        output = e

    return {
        'cmd': CMD,
        'output': output,
    }

# @attach_result_to_link('audio')
# def fetch_audio(out_dir, link, timeout=TIMEOUT):
#     """Download audio rip using youtube-dl"""

#     if link['type'] not in ('soundcloud',)\
#        and 'audio' not in link['tags']:
#         return

#     path = os.path.join(out_dir, 'audio')

#     if not os.path.exists(path) or overwrite:
#         print('    - Downloading audio')
#         CMD = [
#             "youtube-dl -x --audio-format mp3 --audio-quality 0 -o '%(title)s.%(ext)s'",
#             link['url'],
#         ]
#         end = progress(timeout, prefix='      ')
#         try:
#             result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=timeout + 1)  # audio/audio.mp3
#             end()
#             if result.returncode:
#                 print('     ', result.stderr.decode())
#                 raise Exception('Failed to download audio')
#             chmod_file('audio.mp3', cwd=out_dir)
#             return 'audio.mp3'
#         except Exception as e:
#             end()
#             print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
#             print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
#             raise
#     else:
#         print('    √ Skipping audio download')

# @attach_result_to_link('video')
# def fetch_video(out_dir, link, timeout=TIMEOUT):
#     """Download video rip using youtube-dl"""

#     if link['type'] not in ('youtube', 'youku', 'vimeo')\
#        and 'video' not in link['tags']:
#         return

#     path = os.path.join(out_dir, 'video')

#     if not os.path.exists(path) or overwrite:
#         print('    - Downloading video')
#         CMD = [
#             "youtube-dl -x --video-format mp4 --audio-quality 0 -o '%(title)s.%(ext)s'",
#             link['url'],
#         ]
#         end = progress(timeout, prefix='      ')
#         try:
#             result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=timeout + 1)  # video/movie.mp4
#             end()
#             if result.returncode:
#                 print('     ', result.stderr.decode())
#                 raise Exception('Failed to download video')
#             chmod_file('video.mp4', cwd=out_dir)
#             return 'video.mp4'
#         except Exception as e:
#             end()
#             print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
#             print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
#             raise
#     else:
#         print('    √ Skipping video download')



def log_link_archive(out_dir, link):
    update_existing = os.path.exists(out_dir)
    if not update_existing:
        os.makedirs(out_dir)
    
    print('[{symbol_color}{symbol}{reset}] [{timestamp}] "{title}": {blue}{base_url}{reset}'.format(
        symbol='*' if update_existing else '+',
        symbol_color=ANSI['black' if update_existing else 'green'],
        **link,
        **ANSI,
    ))
    if link['type']:
        print('    i Type: {}'.format(link['type']))
