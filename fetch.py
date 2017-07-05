import os
import json

from datetime import datetime
from subprocess import run, PIPE, DEVNULL

from parse import derived_link_info
from config import (
    ARCHIVE_PERMISSIONS,
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
    TIMEOUT,
    ANSI,
    progress,
    chmod_file,
)


def fetch_wget(out_dir, link, overwrite=False, requisites=True, timeout=TIMEOUT):
    """download full site using wget"""

    if not os.path.exists(os.path.join(out_dir, link['domain'])) or overwrite:
        print('    - Downloading full site')
        CMD = [
            *'wget --timestamping --adjust-extension --no-parent'.split(' '),                # Docs: https://www.gnu.org/software/wget/manual/wget.html
            *(('--page-requisites', '--convert-links') if requisites else ()),
            link['url'],
        ]
        end = progress(timeout, prefix='      ')
        try:
            result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=out_dir, timeout=timeout + 1)  # index.html
            end()
            if result.returncode > 0:
                print('       wget output:')
                print('\n'.join('         ' + line for line in result.stderr.decode().rsplit('\n', 10)[-10:] if line.strip()))
                raise Exception('Failed to wget download')
            chmod_file(link['domain'], cwd=out_dir)
        except Exception as e:
            end()
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
    else:
        print('    √ Skipping site download')

def fetch_pdf(out_dir, link, overwrite=False, timeout=TIMEOUT, chrome_binary=CHROME_BINARY):
    """print PDF of site to file using chrome --headless"""

    path = os.path.join(out_dir, 'output.pdf')

    if (not os.path.exists(path) or overwrite) and link['type'] not in ('PDF', 'image'):
        print('    - Printing PDF')
        CMD = [
            chrome_binary,
            *'--headless --disable-gpu --print-to-pdf'.split(' '),
            link['url']
        ]
        end = progress(timeout, prefix='      ')
        try:
            result = run(CMD, stdout=DEVNULL, stderr=PIPE, cwd=out_dir, timeout=timeout + 1)  # output.pdf
            end()
            if result.returncode:
                print('     ', result.stderr.decode())
                raise Exception('Failed to print PDF')
            chmod_file('output.pdf', cwd=out_dir)
        except Exception as e:
            end()
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
    else:
        print('    √ Skipping PDF print')

def fetch_screenshot(out_dir, link, overwrite=False, timeout=TIMEOUT, chrome_binary=CHROME_BINARY, resolution=RESOLUTION):
    """take screenshot of site using chrome --headless"""

    path = os.path.join(out_dir, 'screenshot.png')

    if (not os.path.exists(path) or overwrite) and link['type'] not in ('PDF', 'image'):
        print('    - Snapping Screenshot')
        CMD = [
            chrome_binary,
            *'--headless --disable-gpu --screenshot'.split(' '),
            '--window-size={}'.format(resolution),
            link['url']
        ]
        end = progress(timeout, prefix='      ')
        try:
            result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=timeout + 1)  # sreenshot.png
            end()
            if result.returncode:
                print('     ', result.stderr.decode())
                raise Exception('Failed to take screenshot')
            chmod_file('screenshot.png', cwd=out_dir)
        except Exception as e:
            end()
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
    else:
        print('    √ Skipping screenshot')

def archive_dot_org(out_dir, link, overwrite=False, timeout=TIMEOUT):
    """submit site to archive.org for archiving via their service, save returned archive url"""

    path = os.path.join(out_dir, 'archive.org.txt')

    if not os.path.exists(path) or overwrite:
        print('    - Submitting to archive.org')
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
            errors = [h for h in headers if b'X-Archive-Wayback-Runtime-Error: ' in h]

            if content_location:
                archive_path = content_location[0].split(b'Content-Location: ', 1)[-1].decode('utf-8')
                saved_url = 'https://web.archive.org{}'.format(archive_path)
                success = True

            elif len(errors) == 1 and b'RobotAccessControlException' in errors[0]:
                raise ValueError('Archive.org denied by {}/robots.txt'.format(link['domain']))
            elif errors:
                raise Exception(', '.join(e.decode() for e in errors))
            else:
                raise Exception('Failed to find "Content-Location" URL header in Archive.org response.')
        except Exception as e:
            end()
            print('       Visit url to see output:', ' '.join(CMD))
            print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))

        if success:
            with open(os.path.join(out_dir, 'archive.org.txt'), 'w', encoding='utf-8') as f:
                f.write(saved_url)
            chmod_file('archive.org.txt', cwd=out_dir)

    else:
        print('    √ Skipping archive.org')

def fetch_favicon(out_dir, link, overwrite=False, timeout=TIMEOUT):
    """download site favicon from google's favicon api"""

    path = os.path.join(out_dir, 'favicon.ico')

    if not os.path.exists(path) or overwrite:
        print('    - Fetching Favicon')
        CMD = ['curl', 'https://www.google.com/s2/favicons?domain={domain}'.format(**link)]
        fout = open('{}/favicon.ico'.format(out_dir), 'w')
        end = progress(timeout, prefix='      ')
        try:
            run(CMD, stdout=fout, stderr=DEVNULL, cwd=out_dir, timeout=timeout + 1)  # favicon.ico
            end()
            chmod_file('favicon.ico', cwd=out_dir)
        except Exception as e:
            end()
            print('       Run to see full output:', ' '.join(CMD))
            print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
        fout.close()
    else:
        print('    √ Skipping favicon')

def fetch_audio(out_dir, link, overwrite=False, timeout=TIMEOUT):
    """Download audio rip using youtube-dl"""

    if link['type'] not in ('soundcloud',):
        return

    path = os.path.join(out_dir, 'audio')

    if not os.path.exists(path) or overwrite:
        print('    - Downloading audio')
        CMD = [
            "youtube-dl -x --audio-format mp3 --audio-quality 0 -o '%(title)s.%(ext)s'",
            link['url'],
        ]
        end = progress(timeout, prefix='      ')
        try:
            result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=timeout + 1)  # audio/audio.mp3
            end()
            if result.returncode:
                print('     ', result.stderr.decode())
                raise Exception('Failed to download audio')
            chmod_file('audio', cwd=out_dir)
        except Exception as e:
            end()
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
    else:
        print('    √ Skipping audio download')

def fetch_video(out_dir, link, overwrite=False, timeout=TIMEOUT):
    """Download video rip using youtube-dl"""

    if link['type'] not in ('youtube', 'youku', 'vimeo'):
        return

    path = os.path.join(out_dir, 'video')

    if not os.path.exists(path) or overwrite:
        print('    - Downloading video')
        CMD = [
            "youtube-dl -x --video-format mp4 --audio-quality 0 -o '%(title)s.%(ext)s'",
            link['url'],
        ]
        end = progress(timeout, prefix='      ')
        try:
            result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=timeout + 1)  # video/movie.mp4
            end()
            if result.returncode:
                print('     ', result.stderr.decode())
                raise Exception('Failed to download video')
            chmod_file('video', cwd=out_dir)
        except Exception as e:
            end()
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
    else:
        print('    √ Skipping video download')

def dump_link_info(out_dir, link, overwrite=False):
    """write a json file with some info about the link"""

    info_file_path = os.path.join(out_dir, 'link.json')

    if (not os.path.exists(info_file_path) or overwrite):
        print('    - Creating link info file')
        try:
            link_json = derived_link_info(link)
            link_json['archived_timstamp'] = str(datetime.now().timestamp()).split('.')[0]

            with open(info_file_path, 'w', encoding='utf-8') as link_file:
                link_file.write(json.dumps(
                    link_json,
                    indent=4,
                    default=str) + '\n')

            chmod_file('link.json', cwd=out_dir)
        except Exception as e:
            print('       {}Failed: {} {}{}'.format(ANSI['red'], e.__class__.__name__, e, ANSI['reset']))
    else:
        print('    √ Skipping link info file')


def dump_website(link, service, overwrite=False, permissions=ARCHIVE_PERMISSIONS):
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    print('[{green}+{reset}] [{timestamp} ({time})] "{title}": {blue}{base_url}{reset}'.format(**link, **ANSI))

    out_dir = os.path.join(service, 'archive', link['timestamp'])
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    run(['chmod', permissions, out_dir], timeout=5)

    if link['type']:
        print('    i Type: {}'.format(link['type']))

    if not (link['url'].startswith('http') or link['url'].startswith('ftp')):
        print('    {}X Skipping: invalid link.{}', ANSI['red'], ANSI['yellow'])
        return

    if FETCH_WGET:
        fetch_wget(out_dir, link, overwrite=overwrite, requisites=FETCH_WGET_REQUISITES)

    if FETCH_PDF:
        fetch_pdf(out_dir, link, overwrite=overwrite, chrome_binary=CHROME_BINARY)

    if FETCH_SCREENSHOT:
        fetch_screenshot(out_dir, link, overwrite=overwrite, chrome_binary=CHROME_BINARY, resolution=RESOLUTION)

    if SUBMIT_ARCHIVE_DOT_ORG:
        archive_dot_org(out_dir, link, overwrite=overwrite)

    if FETCH_AUDIO:
        fetch_audio(out_dir, link, overwrite=overwrite)

    if FETCH_VIDEO:
        fetch_video(out_dir, link, overwrite=overwrite)

    if FETCH_FAVICON:
        fetch_favicon(out_dir, link, overwrite=overwrite)

    dump_link_info(out_dir, link, overwrite=overwrite)
