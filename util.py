import os
import re
import sys
import time
import json
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

# URL helpers
without_scheme = lambda url: url.replace('http://', '').replace('https://', '').replace('ftp://', '')
without_query = lambda url: url.split('?', 1)[0]
without_hash = lambda url: url.split('#', 1)[0]
without_path = lambda url: url.split('/', 1)[0]
domain = lambda url: without_hash(without_query(without_path(without_scheme(url))))
base_url = lambda url: without_query(without_scheme(url))

short_ts = lambda ts: ts.split('.')[0]


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
    """download a given url's content into downloads/domain.txt"""

    download_dir = os.path.join(ARCHIVE_DIR, 'downloads')

    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    url_domain = url.split('/', 3)[2]
    output_path = os.path.join(download_dir, '{}.txt'.format(url_domain))
    
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

def str_between(string, start, end=None):
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


def find_link(folder, links):
    """for a given archive folder, find the corresponding link object in links"""
    url = parse_url(folder)
    if url:
        for link in links:
            if (link['base_url'] in url) or (url in link['url']):
                return link

    timestamp = folder.split('.')[0]
    for link in links:
        if link['timestamp'].startswith(timestamp):
            if link['domain'] in os.listdir('./html/archive/' + folder):
                return link      # careful now, this isn't safe for most ppl
            if link['domain'] in parse_url(folder):
                return link
    return None


def parse_url(folder):
    """for a given archive folder, figure out what url it's for"""
    link_json = os.path.join('./html/archive/' + folder, 'index.json')
    if os.path.exists(link_json):
        with open(link_json, 'r') as f:
            link = json.load(f)
            return link['base_url']

    archive_org_txt = os.path.join('./html/archive/' + folder, 'archive.org.txt')
    if os.path.exists(archive_org_txt):
        with open(archive_org_txt, 'r') as f:
            original_link = f.read().strip().split('/http', 1)[-1]
            with_scheme = 'http{}'.format(original_link)
            return with_scheme

    return ''


def merge_folders(folder, link):
    """given a folder, merge it to the canonical 'correct' path for the given link object"""
    base_url = parse_url(folder)
    if not (base_url in link['base_url']
            or link['base_url'] in base_url):
        print(base_url, link['base_url'])
        assert False
    print('{} > {}'.format(folder, link['timestamp']))


def cleanup_archive(path, links):
    """move any incorrectly named folders to their canonical locations"""
    
    # for each folder that exists, see if we can match it up with a known good link
    # if we can, then merge the two folders, if not, move it to lost & found

    # for each timestamp, find similar timestamped folders
    # check each folder for a "domain.com" folder or 

    unmatched = []

    for folder in os.listdir(path):
        link = find_link(folder, links)
        if link is None:
            unmatched.append(folder)
            continue
        
        if folder != link['timestamp']:
            merge_folders(folder, link)

    if unmatched:
        print('[!] Warning! {} unrecognized folders in html/archive/'.format(len(unmatched)))
        print('\n    '.join(unmatched))


def html_appended_url(link):
    """calculate the path to the wgetted .html file, since wget may
    adjust some paths to be different than the base_url path.

    See docs on wget --adjust-extension.
    """

    if link['type'] in ('PDF', 'image'):
        return link['base_url']

    split_url = link['url'].split('#', 1)
    query = ('%3F' + link['url'].split('?', 1)[-1]) if '?' in link['url'] else ''

    if re.search(".+\\.[Hh][Tt][Mm][Ll]?$", split_url[0], re.I | re.M):
        # already ends in .html
        return link['base_url']
    else:
        # .html needs to be appended
        without_scheme = split_url[0].split('://', 1)[-1].split('?', 1)[0]
        if without_scheme.endswith('/'):
            if query:
                return '#'.join([without_scheme + 'index.html' + query + '.html', *split_url[1:]])
            return '#'.join([without_scheme + 'index.html', *split_url[1:]])
        else:
            if query:
                return '#'.join([without_scheme + '/index.html' + query + '.html', *split_url[1:]])
            elif '/' in without_scheme:
                return '#'.join([without_scheme + '.html', *split_url[1:]])
            return link['base_url'] + '/index.html'


def derived_link_info(link):
    """extend link info with the archive urls and other derived data"""

    link_info = {
        **link,
        'date': datetime.fromtimestamp(float(link['timestamp'])).strftime('%Y-%m-%d %H:%M'),
        'google_favicon_url': 'https://www.google.com/s2/favicons?domain={domain}'.format(**link),
        'favicon_url': './archive/{timestamp}/favicon.ico'.format(**link),
        'files_url': './archive/{timestamp}/index.html'.format(**link),
        'archive_url': './archive/{}/{}'.format(link['timestamp'], html_appended_url(link)),
        'pdf_link': './archive/{timestamp}/output.pdf'.format(**link),
        'screenshot_link': './archive/{timestamp}/screenshot.png'.format(**link),
        'archive_org_url': 'https://web.archive.org/web/{base_url}'.format(**link),
    }

    # PDF and images are handled slightly differently
    # wget, screenshot, & pdf urls all point to the same file
    if link['type'] in ('PDF', 'image'):
        link_info.update({
            'archive_url': 'archive/{timestamp}/{base_url}'.format(**link),
            'pdf_link': 'archive/{timestamp}/{base_url}'.format(**link),
            'screenshot_link': 'archive/{timestamp}/{base_url}'.format(**link),
            'title': '{title} ({type})'.format(**link),
        })
    return link_info
