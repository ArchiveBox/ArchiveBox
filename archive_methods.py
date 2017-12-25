import os

from functools import wraps
from datetime import datetime
from subprocess import run, PIPE, DEVNULL
import requests
import re

from index import html_appended_url, parse_json_link_index, write_link_index
from links import links_after_timestamp
from config import (
    ARCHIVE_DIR,
    CHROME_BINARY,
    FETCH_WGET,
    FETCH_TITLE,
    FETCH_WGET_REQUISITES,
    FETCH_PDF,
    FETCH_SCREENSHOT,
    RESOLUTION,
    SUBMIT_ARCHIVE_DOT_ORG,
    FETCH_AUDIO,
    FETCH_VIDEO,
    FETCH_FAVICON,
    WGET_USER_AGENT,
    CHROME_USER_DATA_DIR,
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

def archive_links(archive_path, links, source=None, resume=None):
    check_dependencies()

    to_archive = links_after_timestamp(links, resume)
    try:
        for idx, link in enumerate(to_archive):
            link_dir = os.path.join(archive_path, link['timestamp'])
            archive_link(link_dir, link)
    
    except (KeyboardInterrupt, SystemExit, Exception) as e:
        print('{red}[X] Index is up-to-date, archive update paused on link {idx}/{total}{reset}'.format(
            **ANSI,
            idx=idx,
            total=len(list(to_archive)),
        ))
        print('    Continue where you left off by running:')
        print('       ./archive.py {} {}'.format(
            source,
            link['timestamp'],
        ))
        if not isinstance(e, KeyboardInterrupt):
            raise e
        raise SystemExit(1)


def archive_link(link_dir, link, overwrite=False):
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    update_existing = os.path.exists(link_dir)
    if update_existing:
        link = {
            **parse_json_link_index(link_dir),
            **link,
        }
    else:
        os.makedirs(link_dir)
    
    log_link_archive(link_dir, link, update_existing)

    if FETCH_TITLE and link["title"] is None:
        link = fetch_title(link_dir, link, overwrite=overwrite)

    if FETCH_WGET:
        link = fetch_wget(link_dir, link, overwrite=overwrite)

    if FETCH_PDF:
        link = fetch_pdf(link_dir, link, overwrite=overwrite)

    if FETCH_SCREENSHOT:
        link = fetch_screenshot(link_dir, link, overwrite=overwrite)

    if SUBMIT_ARCHIVE_DOT_ORG:
        link = archive_dot_org(link_dir, link, overwrite=overwrite)

    # if FETCH_AUDIO:
    #     link = fetch_audio(link_dir, link, overwrite=overwrite)

    # if FETCH_VIDEO:
    #     link = fetch_video(link_dir, link, overwrite=overwrite)

    if FETCH_FAVICON:
        link = fetch_favicon(link_dir, link, overwrite=overwrite)

    write_link_index(link_dir, link)
    
    return link

def log_link_archive(link_dir, link, update_existing):
    print('[{symbol_color}{symbol}{reset}] [{timestamp}] "{title}": {blue}{base_url}{reset}'.format(
        symbol='*' if update_existing else '+',
        symbol_color=ANSI['black' if update_existing else 'green'],
        **link,
        **ANSI,
    ))
    if link['type']:
        print('    i Type: {}'.format(link['type']))

    print('    {} ({})'.format(link_dir, 'updating' if update_existing else 'creating'))



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
                print('    √ Skipping: {}'.format(method))
                result = None
            else:
                print('    - Fetching: {}'.format(method))
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


@attach_result_to_link('title')
def fetch_title(link_dir, link):
    try:
        n = requests.get(link["url"]).text
        link["title"] = re.search('<title>(.*?)</title>', n).group(1)  # Or alternatively parse the HTML
    except:
        print('       {}Failed to get title{}'.format(ANSI['red'], ANSI['reset']))
    return {'cmd': '', 'output': link["title"]}


@attach_result_to_link('wget')
def fetch_wget(link_dir, link, requisites=FETCH_WGET_REQUISITES, timeout=TIMEOUT):
    """download full site using wget"""
    domain_path = os.path.join(link_dir, link['domain'])
    if os.path.exists(domain_path):
        return {'output': html_appended_url(link), 'status': 'skipped'}

    CMD = [
        *'wget --timestamping --adjust-extension --no-parent'.split(' '),                # Docs: https://www.gnu.org/software/wget/manual/wget.html
        *(('--page-requisites', '--convert-links') if requisites else ()),
        *(('--user-agent="{}"'.format(WGET_USER_AGENT),) if WGET_USER_AGENT else ()),
        link['url'],
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout + 1)  # index.html
        end()
        output = html_appended_url(link)
        if not requisites:
            # Move wget output as if requisites was passed
            output1 = html_appended_url(link, True)
            folder = os.path.join(link_dir, os.path.dirname(output))
            os.makedirs(folder)
            os.rename(os.path.join(link_dir, output1), os.path.join(link_dir, output))
        if result.returncode > 0:
            print('       got wget response code {}:'.format(result.returncode))
            print('\n'.join('         ' + line for line in (result.stderr or result.stdout).decode().rsplit('\n', 10)[-10:] if line.strip()))
            # raise Exception('Failed to wget download')
    except Exception as e:
        end()
        print('       Run to see full output:', 'cd {}; {}'.format(link_dir, ' '.join(CMD)))
        print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        output = e
    return {
        'cmd': CMD,
        'output': output,
    }


@attach_result_to_link('pdf')
def fetch_pdf(link_dir, link, timeout=TIMEOUT, user_data_dir=CHROME_USER_DATA_DIR):
    """print PDF of site to file using chrome --headless"""

    if link['type'] in ('PDF', 'image'):
        return {'output': html_appended_url(link)}

    if os.path.exists(os.path.join(link_dir, 'output.pdf')):
        return {'output': 'output.pdf', 'status': 'skipped'}

    CMD = [
        *chrome_headless(user_data_dir=user_data_dir),
        '--print-to-pdf',
        link['url']
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout + 1)  # output.pdf
        end()
        if result.returncode:
            print('     ', (result.stderr or result.stdout).decode())
            raise Exception('Failed to print PDF')
        output = 'output.pdf'
    except Exception as e:
        end()
        print('       Run to see full output:', 'cd {}; {}'.format(link_dir, ' '.join(CMD)))
        print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        output = e

    return {
        'cmd': CMD,
        'output': output,
    }


@attach_result_to_link('screenshot')
def fetch_screenshot(link_dir, link, timeout=TIMEOUT, user_data_dir=CHROME_USER_DATA_DIR, resolution=RESOLUTION):
    """take screenshot of site using chrome --headless"""

    if link['type'] in ('PDF', 'image'):
        return {'output': html_appended_url(link)}

    if os.path.exists(os.path.join(link_dir, 'screenshot.png')):
        return {'output': 'screenshot.png', 'status': 'skipped'}

    CMD = [
        *chrome_headless(user_data_dir=user_data_dir),
        '--screenshot',
        '--window-size={}'.format(resolution),
        link['url']
    ]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=link_dir, timeout=timeout + 1)  # sreenshot.png
        end()
        if result.returncode:
            print('     ', (result.stderr or result.stdout).decode())
            raise Exception('Failed to take screenshot')
        chmod_file('screenshot.png', cwd=link_dir)
        output = 'screenshot.png'
    except Exception as e:
        end()
        print('       Run to see full output:', 'cd {}; {}'.format(link_dir, ' '.join(CMD)))
        print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
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

    submit_url = 'https://web.archive.org/save/{}'.format(link['url'].split('?', 1)[0])

    success = False
    CMD = ['curl', '-I', submit_url]
    end = progress(timeout, prefix='      ')
    try:
        result = run(CMD, stdout=PIPE, stderr=DEVNULL, cwd=link_dir, timeout=timeout + 1)  # archive.org.txt
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

    CMD = ['curl', 'https://www.google.com/s2/favicons?domain={domain}'.format(**link)]
    fout = open('{}/favicon.ico'.format(link_dir), 'w')
    end = progress(timeout, prefix='      ')
    try:
        run(CMD, stdout=fout, stderr=DEVNULL, cwd=link_dir, timeout=timeout + 1)  # favicon.ico
        fout.close()
        end()
        chmod_file('favicon.ico', cwd=link_dir)
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
# def fetch_audio(link_dir, link, timeout=TIMEOUT):
#     """Download audio rip using youtube-dl"""

#     if link['type'] not in ('soundcloud',)\
#        and 'audio' not in link['tags']:
#         return

#     path = os.path.join(link_dir, 'audio')

#     if not os.path.exists(path) or overwrite:
#         print('    - Downloading audio')
#         CMD = [
#             "youtube-dl -x --audio-format mp3 --audio-quality 0 -o '%(title)s.%(ext)s'",
#             link['url'],
#         ]
#         end = progress(timeout, prefix='      ')
#         try:
#             result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=link_dir, timeout=timeout + 1)  # audio/audio.mp3
#             end()
#             if result.returncode:
#                 print('     ', result.stderr.decode())
#                 raise Exception('Failed to download audio')
#             chmod_file('audio.mp3', cwd=link_dir)
#             return 'audio.mp3'
#         except Exception as e:
#             end()
#             print('       Run to see full output:', 'cd {}; {}'.format(link_dir, ' '.join(CMD)))
#             print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
#             raise
#     else:
#         print('    √ Skipping audio download')

# @attach_result_to_link('video')
# def fetch_video(link_dir, link, timeout=TIMEOUT):
#     """Download video rip using youtube-dl"""

#     if link['type'] not in ('youtube', 'youku', 'vimeo')\
#        and 'video' not in link['tags']:
#         return

#     path = os.path.join(link_dir, 'video')

#     if not os.path.exists(path) or overwrite:
#         print('    - Downloading video')
#         CMD = [
#             "youtube-dl -x --video-format mp4 --audio-quality 0 -o '%(title)s.%(ext)s'",
#             link['url'],
#         ]
#         end = progress(timeout, prefix='      ')
#         try:
#             result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=link_dir, timeout=timeout + 1)  # video/movie.mp4
#             end()
#             if result.returncode:
#                 print('     ', result.stderr.decode())
#                 raise Exception('Failed to download video')
#             chmod_file('video.mp4', cwd=link_dir)
#             return 'video.mp4'
#         except Exception as e:
#             end()
#             print('       Run to see full output:', 'cd {}; {}'.format(link_dir, ' '.join(CMD)))
#             print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
#             raise
#     else:
#         print('    √ Skipping video download')


def chrome_headless(binary=CHROME_BINARY, user_data_dir=CHROME_USER_DATA_DIR):
    args = [binary, '--headless', '--disable-gpu']
    default_profile = os.path.expanduser('~/Library/Application Support/Google/Chrome/Default')
    if user_data_dir:
        args.append('--user-data-dir={}'.format(user_data_dir))
    elif os.path.exists(default_profile):
        args.append('--user-data-dir={}'.format(default_profile))
    return args
