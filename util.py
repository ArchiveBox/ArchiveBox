import os
import sys
import time
import requests

from datetime import datetime
from subprocess import run, PIPE, DEVNULL
from multiprocessing import Process

from config import (
    ARCHIVE_PERMISSIONS,
    ARCHIVE_DIR,
    TIMEOUT,
    TERM_WIDTH,
    SHOW_PROGRESS,
    ANSI,
    CHROME_BINARY,
    FETCH_WGET,
    FETCH_PDF,
    FETCH_SCREENSHOT,
    FETCH_FAVICON,
    FETCH_AUDIO,
    FETCH_VIDEO,
    SUBMIT_ARCHIVE_DOT_ORG,
)

def check_dependencies():
    """Check that all necessary dependencies are installed, and have valid versions"""

    print('[*] Checking Dependencies:')

    python_vers = float('{}.{}'.format(sys.version_info.major, sys.version_info.minor))
    if python_vers < 3.5:
        print('{}[X] Python version is not new enough: {} (>3.5 is required){}'.format(ANSI['red'], python_vers, ANSI['reset']))
        print('    See https://github.com/pirate/bookmark-archiver#troubleshooting for help upgrading your Python installation.')
        raise SystemExit(1)

    if FETCH_PDF or FETCH_SCREENSHOT:
        if run(['which', CHROME_BINARY]).returncode:
            print('{}[X] Missing dependency: {}{}'.format(ANSI['red'], CHROME_BINARY, ANSI['reset']))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

        # parse chrome --version e.g. Google Chrome 61.0.3114.0 canary / Chromium 59.0.3029.110 built on Ubuntu, running on Ubuntu 16.04
        try:
            result = run([CHROME_BINARY, '--version'], stdout=PIPE)
            version = result.stdout.decode('utf-8').replace('Google Chrome ', '').replace('Chromium ', '').split(' ', 1)[0].split('.', 1)[0]  # TODO: regex might be better
            if int(version) < 59:
                print('{red}[X] Chrome version must be 59 or greater for headless PDF and screenshot saving{reset}'.format(**ANSI))
                print('    See https://github.com/pirate/bookmark-archiver for help.')
                raise SystemExit(1)
        except (TypeError, OSError):
            print('{red}[X] Failed to parse Chrome version, is it installed properly?{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_WGET:
        if run(['which', 'wget']).returncode or run(['wget', '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: wget{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format('wget'))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_FAVICON or SUBMIT_ARCHIVE_DOT_ORG:
        if run(['which', 'curl']).returncode or run(['curl', '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: curl{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format('curl'))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_AUDIO or FETCH_VIDEO:
        if run(['which', 'youtube-dl']).returncode or run(['youtube-dl', '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: youtube-dl{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format('youtube-dl'))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)


def chmod_file(path, cwd='.', permissions=ARCHIVE_PERMISSIONS, timeout=30):
    """chmod -R <permissions> <cwd>/<path>"""

    if not os.path.exists(os.path.join(cwd, path)):
        raise Exception('Failed to chmod: {} does not exist (did the previous step fail?)'.format(path))

    chmod_result = run(['chmod', '-R', permissions, path], cwd=cwd, stdout=DEVNULL, stderr=PIPE, timeout=timeout)
    if chmod_result.returncode == 1:
        print('     ', chmod_result.stderr.decode())
        raise Exception('Failed to chmod {}/{}'.format(cwd, path))


def progress(seconds=TIMEOUT, prefix=''):
    """Show a (subprocess-controlled) progress bar with a <seconds> timeout,
       returns end() function to instantly finish the progress
    """

    if not SHOW_PROGRESS:
        return lambda: None

    chunk = '█' if sys.stdout.encoding == 'UTF-8' else '#'
    chunks = TERM_WIDTH - len(prefix) - 20  # number of progress chunks to show (aka max bar width)

    def progress_bar(seconds=seconds, prefix=prefix):
        """show timer in the form of progress bar, with percentage and seconds remaining"""
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

    p = Process(target=progress_bar)
    p.start()

    def end():
        """immediately finish progress and clear the progressbar line"""
        p.terminate()
        sys.stdout.write('\r{}{}\r'.format((' ' * TERM_WIDTH), ANSI['reset']))  # clear whole terminal line
        sys.stdout.flush()

    return end


def download_url(url):
    if not os.path.exists(os.path.join(ARCHIVE_DIR, 'downloads')):
        os.makedirs(os.path.join(ARCHIVE_DIR, 'downloads'))

    url_domain = url.split('/', 3)[2]
    output_path = os.path.join(ARCHIVE_DIR, 'downloads', '{}.txt'.format(url_domain))
    
    print('[*] [{}] Downloading {} > {}'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        url,
        output_path,
    ))
    end = progress(TIMEOUT, prefix='      ')
    try:
        downloaded_xml = requests.get(url).content.decode()
        end()
    except Exception as e:
        end()
        print('[!] Failed to download {}\n'.format(url))
        print('    ', e)
        raise SystemExit(1)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(downloaded_xml)
    return output_path


def get_str_between(string, start, end=None):
    """(<abc>12345</def>, <abc>, </def>)  ->  12345"""

    content = string.split(start, 1)[-1]
    if end is not None:
        content = content.rsplit(end, 1)[0]

    return content




def get_link_type(link):
    """Certain types of links need to be handled specially, this figures out when that's the case"""

    if link['base_url'].endswith('.pdf'):
        return 'PDF'
    elif link['base_url'].rsplit('.', 1) in ('pdf', 'png', 'jpg', 'jpeg', 'svg', 'bmp', 'gif', 'tiff', 'webp'):
        return 'image'
    elif 'wikipedia.org' in link['domain']:
        return 'wiki'
    elif 'youtube.com' in link['domain']:
        return 'youtube'
    elif 'soundcloud.com' in link['domain']:
        return 'soundcloud'
    elif 'youku.com' in link['domain']:
        return 'youku'
    elif 'vimeo.com' in link['domain']:
        return 'vimeo'
    return None


# URL helpers
without_scheme = lambda url: url.replace('http://', '').replace('https://', '').replace('ftp://', '')
without_query = lambda url: url.split('?', 1)[0]
without_hash = lambda url: url.split('#', 1)[0] 
without_path = lambda url: url.split('/', 1)[0]
domain = lambda url: without_hash(without_query(without_path(without_scheme(url))))
base_url = lambda url: without_query(without_scheme(url))
