import os
import json

from datetime import datetime
from subprocess import run, PIPE, DEVNULL

from parse import derived_link_info
from config import (
    ARCHIVE_PERMISSIONS,
    FETCH_WGET,
    FETCH_WGET_REQUISITES,
    FETCH_PDF,
    FETCH_SCREENSHOT,
    RESOLUTION,
    SUBMIT_ARCHIVE_DOT_ORG,
    FETCH_AUDIO,
    FETCH_VIDEO,
    FETCH_FAVICON,
)


def chmod_file(path, cwd='.', permissions='755', timeout=30):
    if not os.path.exists(os.path.join(cwd, path)):
        raise Exception('Failed to chmod: {} does not exist (did the previous step fail?)'.format(path))

    chmod_result = run(['chmod', '-R', permissions, path], cwd=cwd, stdout=DEVNULL, stderr=PIPE, timeout=timeout)
    if chmod_result.returncode == 1:
        print('     ', chmod_result.stderr.decode())
        raise Exception('Failed to chmod {}/{}'.format(cwd, path))

def fetch_wget(out_dir, link, overwrite=False, requisites=True, timeout=60):
    """download full site using wget"""

    domain = link['base_url'].split('/', 1)[0]
    if not os.path.exists('{}/{}'.format(out_dir, domain)) or overwrite:
        print('    - Downloading Full Site')
        CMD = [
            *'wget --timestamping --adjust-extension --no-parent'.split(' '),                # Docs: https://www.gnu.org/software/wget/manual/wget.html
            *(('--page-requisites', '--convert-links') if requisites else ()),
            link['url'],
        ]
        try:
            result = run(CMD, stdout=PIPE, stderr=PIPE, cwd=out_dir, timeout=timeout)  # dom.html
            if result.returncode > 0:
                print('     ', result.stderr.decode().split('\n')[-1])
                raise Exception('Failed to wget download')
            chmod_file(domain, cwd=out_dir)
        except Exception as e:
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       Failed: {} {}'.format(e.__class__.__name__, e))
    else:
        print('    √ Skipping site download')

def fetch_pdf(out_dir, link, overwrite=False, timeout=60, chrome_binary='chromium-browser'):
    """print PDF of site to file using chrome --headless"""

    if (not os.path.exists('{}/output.pdf'.format(out_dir)) or overwrite) and link['type'] not in ('PDF', 'image'):
        print('    - Printing PDF')
        CMD = [
            chrome_binary,
            *'--headless --disable-gpu --print-to-pdf'.split(' '),
            link['url']
        ]
        try:
            result = run(CMD, stdout=DEVNULL, stderr=PIPE, cwd=out_dir, timeout=timeout)  # output.pdf
            if result.returncode:
                print('     ', result.stderr.decode())
                raise Exception('Failed to print PDF')
            chmod_file('output.pdf', cwd=out_dir)
        except Exception as e:
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       Failed: {} {}'.format(e.__class__.__name__, e))
    else:
        print('    √ Skipping PDF print')

def fetch_screenshot(out_dir, link, overwrite=False, timeout=60, chrome_binary='chromium-browser', resolution='1440,900'):
    """take screenshot of site using chrome --headless"""

    if (not os.path.exists('{}/screenshot.png'.format(out_dir)) or overwrite) and link['type'] not in ('PDF', 'image'):
        print('    - Snapping Screenshot')
        CMD = [
            chrome_binary,
            *'--headless --disable-gpu --screenshot'.split(' '),
            '--window-size={}'.format(resolution),
            link['url']
        ]
        try:
            result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=timeout)  # sreenshot.png
            if result.returncode:
                print('     ', result.stderr.decode())
                raise Exception('Failed to take screenshot')
            chmod_file('screenshot.png', cwd=out_dir)
        except Exception as e:
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       Failed: {} {}'.format(e.__class__.__name__, e))
    else:
        print('    √ Skipping screenshot')

def archive_dot_org(out_dir, link, overwrite=False, timeout=60):
    """submit site to archive.org for archiving via their service, save returned archive url"""
    if (not os.path.exists('{}/archive.org.txt'.format(out_dir)) or overwrite):
        print('    - Submitting to archive.org')
        submit_url = 'https://web.archive.org/save/{}'.format(link['url'].split('?', 1)[0])

        success = False
        CMD = ['curl', '-I', submit_url]
        try:
            result = run(CMD, stdout=PIPE, stderr=DEVNULL, cwd=out_dir, timeout=timeout)  # archive.org
            headers = result.stdout.splitlines()
            content_location = [h for h in headers if b'Content-Location: ' in h]
            if content_location:
                archive_path = content_location[0].split(b'Content-Location: ', 1)[-1].decode('utf-8')
                saved_url = 'https://web.archive.org{}'.format(archive_path)
                success = True
            else:
                raise Exception('Failed to find "Content-Location" URL header in Archive.org response.')
        except Exception as e:
            print('       Visit url to see output:', ' '.join(CMD))
            print('       Failed: {} {}'.format(e.__class__.__name__, e))

        if success:
            with open('{}/archive.org.txt'.format(out_dir), 'w') as f:
                f.write(saved_url)
            chmod_file('archive.org.txt', cwd=out_dir)

    else:
        print('    √ Skipping archive.org')

def fetch_favicon(out_dir, link, overwrite=False, timeout=60):
    """download site favicon from google's favicon api"""

    if not os.path.exists('{}/favicon.ico'.format(out_dir)) or overwrite:
        print('    - Fetching Favicon')
        CMD = 'curl https://www.google.com/s2/favicons?domain={domain}'.format(**link).split(' ')
        fout = open('{}/favicon.ico'.format(out_dir), 'w')
        try:
            run([*CMD], stdout=fout, stderr=DEVNULL, cwd=out_dir, timeout=timeout)  # favicon.ico
            chmod_file('favicon.ico', cwd=out_dir)
        except Exception as e:
            print('       Run to see full output:', ' '.join(CMD))
            print('       Failed: {} {}'.format(e.__class__.__name__, e))
        fout.close()
    else:
        print('    √ Skipping favicon')

def fetch_audio(out_dir, link, overwrite=False, timeout=60):
    """Download audio rip using youtube-dl"""

    if link['type'] not in ('soundcloud',):
        return

    if (not os.path.exists('{}/audio'.format(out_dir)) or overwrite):
        print('    - Downloading audio')
        CMD = [
            "youtube-dl -x --audio-format mp3 --audio-quality 0 -o '%(title)s.%(ext)s'",
            link['url'],
        ]
        try:
            result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=timeout)  # sreenshot.png
            if result.returncode:
                print('     ', result.stderr.decode())
                raise Exception('Failed to download audio')
            chmod_file('audio', cwd=out_dir)
        except Exception as e:
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       Failed: {} {}'.format(e.__class__.__name__, e))
    else:
        print('    √ Skipping audio download')

def fetch_video(out_dir, link, overwrite=False, timeout=60):
    """Download video rip using youtube-dl"""

    if link['type'] not in ('youtube', 'youku', 'vimeo'):
        return


    if (not os.path.exists('{}/video'.format(out_dir)) or overwrite):
        print('    - Downloading video')
        CMD = [
            "youtube-dl -x --audio-format mp3 --audio-quality 0 -o '%(title)s.%(ext)s'",
            link['url'],
        ]
        try:
            result = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=timeout)  # sreenshot.png
            if result.returncode:
                print('     ', result.stderr.decode())
                raise Exception('Failed to download video')
            chmod_file('video', cwd=out_dir)
        except Exception as e:
            print('       Run to see full output:', 'cd {}; {}'.format(out_dir, ' '.join(CMD)))
            print('       Failed: {} {}'.format(e.__class__.__name__, e))
    else:
        print('    √ Skipping video download')

def dump_link_info(out_dir, link, update=True):
    """write a json file with some info about the link"""

    info_file_path = os.path.join(out_dir, 'link.json')

    if (not os.path.exists(info_file_path) or update):
        print('    - Creating link info file')
        try:
            link_json = derived_link_info(link)
            link_json['archived_timstamp'] = str(datetime.now().timestamp()).split('.')[0]

            with open(info_file_path, 'w') as link_file:
                link_file.write(json.dumps(
                    link_json,
                    indent=4,
                    default=str) + '\n')

            chmod_file('link.json', cwd=out_dir)
        except Exception as e:
            print('       Failed: {} {}'.format(e.__class__.__name__, e))
    else:
        print('    √ Skipping link info file')


def dump_website(link, service, overwrite=False, permissions=ARCHIVE_PERMISSIONS):
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    print('[+] [{timestamp} ({time})] "{title}": {base_url}'.format(**link))

    out_dir = os.path.join(service, 'archive', link['timestamp'])
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    run(['chmod', permissions, out_dir], timeout=5)

    if link['type']:
        print('    i Type: {}'.format(link['type']))

    if not (link['url'].startswith('http') or link['url'].startswith('ftp')):
        print('    X Skipping: invalid link.')
        return

    if FETCH_WGET:
        fetch_wget(out_dir, link, overwrite=overwrite, requisites=FETCH_WGET_REQUISITES)

    if FETCH_PDF:
        fetch_pdf(out_dir, link, overwrite=overwrite)

    if FETCH_SCREENSHOT:
        fetch_screenshot(out_dir, link, overwrite=overwrite, resolution=RESOLUTION)

    if SUBMIT_ARCHIVE_DOT_ORG:
        archive_dot_org(out_dir, link, overwrite=overwrite)

    if FETCH_AUDIO:
        fetch_audio(out_dir, link, overwrite=overwrite)

    if FETCH_VIDEO:
        fetch_video(out_dir, link, overwrite=overwrite)

    if FETCH_FAVICON:
        fetch_favicon(out_dir, link, overwrite=overwrite)

    dump_link_info(out_dir, link)
