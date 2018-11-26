import os
import re
import sys
import time
import json
import requests

from datetime import datetime
from subprocess import run, PIPE, DEVNULL
from multiprocessing import Process
from urllib.parse import quote

from config import (
    IS_TTY,
    OUTPUT_PERMISSIONS,
    REPO_DIR,
    SOURCES_DIR,
    OUTPUT_DIR,
    ARCHIVE_DIR,
    TIMEOUT,
    TERM_WIDTH,
    SHOW_PROGRESS,
    ANSI,
    CHROME_BINARY,
    FETCH_WGET,
    FETCH_PDF,
    FETCH_SCREENSHOT,
    FETCH_DOM,
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
base_url = lambda url: without_scheme(url)  # uniq base url used to dedupe links

short_ts = lambda ts: ts.split('.')[0]


def check_dependencies():
    """Check that all necessary dependencies are installed, and have valid versions"""

    python_vers = float('{}.{}'.format(sys.version_info.major, sys.version_info.minor))
    if python_vers < 3.5:
        print('{}[X] Python version is not new enough: {} (>3.5 is required){}'.format(ANSI['red'], python_vers, ANSI['reset']))
        print('    See https://github.com/pirate/bookmark-archiver#troubleshooting for help upgrading your Python installation.')
        raise SystemExit(1)

    if FETCH_PDF or FETCH_SCREENSHOT or FETCH_DOM:
        if run(['which', CHROME_BINARY], stdout=DEVNULL).returncode:
            print('{}[X] Missing dependency: {}{}'.format(ANSI['red'], CHROME_BINARY, ANSI['reset']))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

        # parse chrome --version e.g. Google Chrome 61.0.3114.0 canary / Chromium 59.0.3029.110 built on Ubuntu, running on Ubuntu 16.04
        try:
            result = run([CHROME_BINARY, '--version'], stdout=PIPE)
            version_str = result.stdout.decode('utf-8')
            version_lines = re.sub("(Google Chrome|Chromium) (\\d+?)\\.(\\d+?)\\.(\\d+?).*?$", "\\2", version_str).split('\n')
            version = [l for l in version_lines if l.isdigit()][-1]
            if int(version) < 59:
                print(version_lines)
                print('{red}[X] Chrome version must be 59 or greater for headless PDF, screenshot, and DOM saving{reset}'.format(**ANSI))
                print('    See https://github.com/pirate/bookmark-archiver for help.')
                raise SystemExit(1)
        except (IndexError, TypeError, OSError):
            print('{red}[X] Failed to parse Chrome version, is it installed properly?{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_WGET:
        if run(['which', 'wget'], stdout=DEVNULL).returncode or run(['wget', '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: wget{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format('wget'))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_FAVICON or SUBMIT_ARCHIVE_DOT_ORG:
        if run(['which', 'curl'], stdout=DEVNULL).returncode or run(['curl', '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: curl{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format('curl'))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_AUDIO or FETCH_VIDEO:
        if run(['which', 'youtube-dl'], stdout=DEVNULL).returncode or run(['youtube-dl', '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: youtube-dl{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format('youtube-dl'))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)


def chmod_file(path, cwd='.', permissions=OUTPUT_PERMISSIONS, timeout=30):
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
        nonlocal p
        if p is None: # protect from double termination
            return

        p.terminate()
        p = None

        sys.stdout.write('\r{}{}\r'.format((' ' * TERM_WIDTH), ANSI['reset']))  # clear whole terminal line
        sys.stdout.flush()

    return end

def pretty_path(path):
    """convert paths like .../bookmark-archiver/archiver/../output/abc into output/abc"""
    return path.replace(REPO_DIR + '/', '')


def download_url(url):
    """download a given url's content into downloads/domain.txt"""

    if not os.path.exists(SOURCES_DIR):
        os.makedirs(SOURCES_DIR)

    ts = str(datetime.now().timestamp()).split('.', 1)[0]

    source_path = os.path.join(SOURCES_DIR, '{}-{}.txt'.format(domain(url), ts))

    print('[*] [{}] Downloading {} > {}'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        url,
        pretty_path(source_path),
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

    with open(source_path, 'w', encoding='utf-8') as f:
        f.write(downloaded_xml)

    return source_path

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

def merge_links(a, b):
    """deterministially merge two links, favoring longer field values over shorter,
    and "cleaner" values over worse ones.
    """
    longer = lambda key: a[key] if len(a[key]) > len(b[key]) else b[key]
    earlier = lambda key: a[key] if a[key] < b[key] else b[key]
    
    url = longer('url')
    longest_title = longer('title')
    cleanest_title = a['title'] if '://' not in a['title'] else b['title']
    link = {
        'timestamp': earlier('timestamp'),
        'url': url,
        'domain': domain(url),
        'base_url': base_url(url),
        'tags': longer('tags'),
        'title': longest_title if '://' not in longest_title else cleanest_title,
        'sources': list(set(a.get('sources', []) + b.get('sources', []))),
    }
    link['type'] = get_link_type(link)
    return link

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
            if link['domain'] in os.listdir(os.path.join(ARCHIVE_DIR, folder)):
                return link      # careful now, this isn't safe for most ppl
            if link['domain'] in parse_url(folder):
                return link
    return None


def parse_url(folder):
    """for a given archive folder, figure out what url it's for"""
    link_json = os.path.join(ARCHIVE_DIR, folder, 'index.json')
    if os.path.exists(link_json):
        with open(link_json, 'r') as f:
            try:
                link_json = f.read().strip()
                if link_json:
                    link = json.loads(link_json)
                    return link['base_url']
            except ValueError:
                print('File contains invalid JSON: {}!'.format(link_json))

    archive_org_txt = os.path.join(ARCHIVE_DIR, folder, 'archive.org.txt')
    if os.path.exists(archive_org_txt):
        with open(archive_org_txt, 'r') as f:
            original_link = f.read().strip().split('/http', 1)[-1]
            with_scheme = 'http{}'.format(original_link)
            return with_scheme

    return ''

def manually_merge_folders(source, target):
    """prompt for user input to resolve a conflict between two archive folders"""

    if not IS_TTY:
        return

    fname = lambda path: path.split('/')[-1]

    print('    {} and {} have conflicting files, which do you want to keep?'.format(fname(source), fname(target)))
    print('      - [enter]: do nothing (keep both)')
    print('      - a:       prefer files from {}'.format(source))
    print('      - b:       prefer files from {}'.format(target))
    print('      - q:       quit and resolve the conflict manually')
    try:
        answer = input('> ').strip().lower()
    except KeyboardInterrupt:
        answer = 'q'

    assert answer in ('', 'a', 'b', 'q'), 'Invalid choice.'

    if answer == 'q':
        print('\nJust run Bookmark Archiver again to pick up where you left off.')
        raise SystemExit(0)
    elif answer == '':
        return

    files_in_source = set(os.listdir(source))
    files_in_target = set(os.listdir(target))
    for file in files_in_source:
        if file in files_in_target:
            to_delete = target if answer == 'a' else source
            run(['rm', '-Rf', os.path.join(to_delete, file)])
        run(['mv', os.path.join(source, file), os.path.join(target, file)])

    if not set(os.listdir(source)):
        run(['rm', '-Rf', source])

def fix_folder_path(archive_path, link_folder, link):
    """given a folder, merge it to the canonical 'correct' path for the given link object"""
    source = os.path.join(archive_path, link_folder)
    target = os.path.join(archive_path, link['timestamp'])

    url_in_folder = parse_url(source)
    if not (url_in_folder in link['base_url']
            or link['base_url'] in url_in_folder):
        raise ValueError('The link does not match the url for this folder.')

    if not os.path.exists(target):
        # target doesn't exist so nothing needs merging, simply move A to B
        run(['mv', source, target])
    else:
        # target folder exists, check for conflicting files and attempt manual merge
        files_in_source = set(os.listdir(source))
        files_in_target = set(os.listdir(target))
        conflicting_files = files_in_source & files_in_target

        if not conflicting_files:
            for file in files_in_source:
                run(['mv', os.path.join(source, file), os.path.join(target, file)])

    if os.path.exists(source):
        files_in_source = set(os.listdir(source))
        if files_in_source:
            manually_merge_folders(source, target)
        else:
            run(['rm', '-R', source])


def migrate_data():
    # migrate old folder to new OUTPUT folder
    old_dir = os.path.join(REPO_DIR, 'html')
    if os.path.exists(old_dir):
        print('[!] WARNING: Moved old output folder "html" to new location: {}'.format(OUTPUT_DIR))
        run(['mv', old_dir, OUTPUT_DIR], timeout=10)


def cleanup_archive(archive_path, links):
    """move any incorrectly named folders to their canonical locations"""
    
    # for each folder that exists, see if we can match it up with a known good link
    # if we can, then merge the two folders (TODO: if not, move it to lost & found)

    unmatched = []
    bad_folders = []

    if not os.path.exists(archive_path):
        return

    for folder in os.listdir(archive_path):
        try:
            files = os.listdir(os.path.join(archive_path, folder))
        except NotADirectoryError:
            continue
        
        if files:
            link = find_link(folder, links)
            if link is None:
                unmatched.append(folder)
                continue
            
            if folder != link['timestamp']:
                bad_folders.append((folder, link))
        else:
            # delete empty folders
            run(['rm', '-R', os.path.join(archive_path, folder)])
    
    if bad_folders and IS_TTY and input('[!] Cleanup archive? y/[n]: ') == 'y':
        print('[!] Fixing {} improperly named folders in archive...'.format(len(bad_folders)))
        for folder, link in bad_folders:
            fix_folder_path(archive_path, folder, link)
    elif bad_folders:
        print('[!] Warning! {} folders need to be merged, fix by running bookmark archiver.'.format(len(bad_folders)))

    if unmatched:
        print('[!] Warning! {} unrecognized folders in html/archive/'.format(len(unmatched)))
        print('    '+ '\n    '.join(unmatched))


def wget_output_path(link, look_in=None):
    """calculate the path to the wgetted .html file, since wget may
    adjust some paths to be different than the base_url path.

    See docs on wget --adjust-extension (-E)
    """

    # if we have it stored, always prefer the actual output path to computed one
    if link.get('latest', {}).get('wget'):
        return link['latest']['wget']

    urlencode = lambda s: quote(s, encoding='utf-8', errors='replace')

    if link['type'] in ('PDF', 'image'):
        return urlencode(link['base_url'])

    # Since the wget algorithm to for -E (appending .html) is incredibly complex
    # instead of trying to emulate it here, we just look in the output folder
    # to see what html file wget actually created as the output
    wget_folder = link['base_url'].rsplit('/', 1)[0].split('/')
    look_in = os.path.join(ARCHIVE_DIR, link['timestamp'], *wget_folder)

    if look_in and os.path.exists(look_in):
        html_files = [
            f for f in os.listdir(look_in)
            if re.search(".+\\.[Hh][Tt][Mm][Ll]?$", f, re.I | re.M)
        ]
        if html_files:
            return urlencode(os.path.join(*wget_folder, html_files[0]))

    return None

    # If finding the actual output file didn't work, fall back to the buggy
    # implementation of the wget .html appending algorithm
    # split_url = link['url'].split('#', 1)
    # query = ('%3F' + link['url'].split('?', 1)[-1]) if '?' in link['url'] else ''

    # if re.search(".+\\.[Hh][Tt][Mm][Ll]?$", split_url[0], re.I | re.M):
    #     # already ends in .html
    #     return urlencode(link['base_url'])
    # else:
    #     # .html needs to be appended
    #     without_scheme = split_url[0].split('://', 1)[-1].split('?', 1)[0]
    #     if without_scheme.endswith('/'):
    #         if query:
    #             return urlencode('#'.join([without_scheme + 'index.html' + query + '.html', *split_url[1:]]))
    #         return urlencode('#'.join([without_scheme + 'index.html', *split_url[1:]]))
    #     else:
    #         if query:
    #             return urlencode('#'.join([without_scheme + '/index.html' + query + '.html', *split_url[1:]]))
    #         elif '/' in without_scheme:
    #             return urlencode('#'.join([without_scheme + '.html', *split_url[1:]]))
    #         return urlencode(link['base_url'] + '/index.html')


def derived_link_info(link):
    """extend link info with the archive urls and other derived data"""

    link_info = {
        **link,
        'date': datetime.fromtimestamp(float(link['timestamp'])).strftime('%Y-%m-%d %H:%M'),
        'google_favicon_url': 'https://www.google.com/s2/favicons?domain={domain}'.format(**link),
        'favicon_url': 'archive/{timestamp}/favicon.ico'.format(**link),
        'files_url': 'archive/{timestamp}/index.html'.format(**link),
        'archive_url': 'archive/{}/{}'.format(link['timestamp'], wget_output_path(link) or 'index.html'),
        'pdf_link': 'archive/{timestamp}/output.pdf'.format(**link),
        'screenshot_link': 'archive/{timestamp}/screenshot.png'.format(**link),
        'dom_link': 'archive/{timestamp}/output.html'.format(**link),
        'archive_org_url': 'https://web.archive.org/web/{base_url}'.format(**link),
    }

    # PDF and images are handled slightly differently
    # wget, screenshot, & pdf urls all point to the same file
    if link['type'] in ('PDF', 'image'):
        link_info.update({
            'archive_url': 'archive/{timestamp}/{base_url}'.format(**link),
            'pdf_link': 'archive/{timestamp}/{base_url}'.format(**link),
            'screenshot_link': 'archive/{timestamp}/{base_url}'.format(**link),
            'dom_link': 'archive/{timestamp}/{base_url}'.format(**link),
            'title': '{title} ({type})'.format(**link),
        })
    return link_info
