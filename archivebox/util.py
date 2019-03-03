import os
import re
import sys
import time
import json
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from decimal import Decimal
from urllib.parse import quote
from datetime import datetime
from subprocess import TimeoutExpired, Popen, PIPE, DEVNULL, CompletedProcess, CalledProcessError
from multiprocessing import Process

from config import (
    ANSI,
    IS_TTY,
    TERM_WIDTH,
    REPO_DIR,
    OUTPUT_DIR,
    SOURCES_DIR,
    ARCHIVE_DIR,
    OUTPUT_PERMISSIONS,
    TIMEOUT,
    SHOW_PROGRESS,
    CHECK_SSL_VALIDITY,
    WGET_USER_AGENT,
    CURL_BINARY,
    WGET_BINARY,
    CHROME_BINARY,
    GIT_BINARY,
    YOUTUBEDL_BINARY,
    FETCH_TITLE,
    FETCH_FAVICON,
    FETCH_WGET,
    FETCH_WARC,
    FETCH_PDF,
    FETCH_SCREENSHOT,
    FETCH_DOM,
    FETCH_GIT,
    FETCH_MEDIA,
    SUBMIT_ARCHIVE_DOT_ORG,
)

# URL helpers: https://docs.python.org/3/library/urllib.parse.html#url-parsing
scheme = lambda url: urlparse(url).scheme
without_scheme = lambda url: urlparse(url)._replace(scheme='').geturl().strip('//')
without_query = lambda url: urlparse(url)._replace(query='').geturl().strip('//')
without_fragment = lambda url: urlparse(url)._replace(fragment='').geturl().strip('//')
without_path = lambda url: urlparse(url)._replace(path='', fragment='', query='').geturl().strip('//')
path = lambda url: urlparse(url).path
basename = lambda url: urlparse(url).path.rsplit('/', 1)[-1]
domain = lambda url: urlparse(url).netloc
query = lambda url: urlparse(url).query
fragment = lambda url: urlparse(url).fragment
extension = lambda url: basename(url).rsplit('.', 1)[-1].lower() if '.' in basename(url) else ''
base_url = lambda url: without_scheme(url)  # uniq base url used to dedupe links

short_ts = lambda ts: ts.split('.')[0]

URL_REGEX = re.compile(
    r'http[s]?://'                    # start matching from allowed schemes
    r'(?:[a-zA-Z]|[0-9]'              # followed by allowed alphanum characters
    r'|[$-_@.&+]|[!*\(\),]'           #    or allowed symbols
    r'|(?:%[0-9a-fA-F][0-9a-fA-F]))'  #    or allowed unicode bytes
    r'[^\]\[\(\)<>\""\'\s]+',         # stop parsing at these symbols
    re.IGNORECASE,
)
HTML_TITLE_REGEX = re.compile(
    r'<title>'                         # start matching text after <title> tag
    r'(.[^<>]+)',                      # get everything up to these symbols
    re.IGNORECASE,
)


def check_dependencies():
    """Check that all necessary dependencies are installed, and have valid versions"""

    python_vers = float('{}.{}'.format(sys.version_info.major, sys.version_info.minor))
    if python_vers < 3.5:
        print('{}[X] Python version is not new enough: {} (>3.5 is required){}'.format(ANSI['red'], python_vers, ANSI['reset']))
        print('    See https://github.com/pirate/ArchiveBox#troubleshooting for help upgrading your Python installation.')
        raise SystemExit(1)

    if FETCH_FAVICON or SUBMIT_ARCHIVE_DOT_ORG:
        if run(['which', CURL_BINARY], stdout=DEVNULL).returncode or run([CURL_BINARY, '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: curl{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(CURL_BINARY))
            print('    See https://github.com/pirate/ArchiveBox for help.')
            raise SystemExit(1)

    if FETCH_WGET or FETCH_WARC:
        if run(['which', WGET_BINARY], stdout=DEVNULL).returncode or run([WGET_BINARY, '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: wget{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(WGET_BINARY))
            print('    See https://github.com/pirate/ArchiveBox for help.')
            raise SystemExit(1)

    if FETCH_PDF or FETCH_SCREENSHOT or FETCH_DOM:
        if run(['which', CHROME_BINARY], stdout=DEVNULL).returncode:
            print('{}[X] Missing dependency: {}{}'.format(ANSI['red'], CHROME_BINARY, ANSI['reset']))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/ArchiveBox for help.')
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
                print('    See https://github.com/pirate/ArchiveBox for help.')
                raise SystemExit(1)
        except (IndexError, TypeError, OSError):
            print('{red}[X] Failed to parse Chrome version, is it installed properly?{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/ArchiveBox for help.')
            raise SystemExit(1)

    if FETCH_GIT:
        if run(['which', GIT_BINARY], stdout=DEVNULL).returncode or run([GIT_BINARY, '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: git{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(GIT_BINARY))
            print('    See https://github.com/pirate/ArchiveBox for help.')
            raise SystemExit(1)

    if FETCH_MEDIA:
        if run(['which', YOUTUBEDL_BINARY], stdout=DEVNULL).returncode or run([YOUTUBEDL_BINARY, '--version'], stdout=DEVNULL).returncode:
            print('{red}[X] Missing dependency: youtube-dl{reset}'.format(**ANSI))
            print('    Run ./setup.sh, then confirm it was installed with: {} --version'.format(YOUTUBEDL_BINARY))
            print('    See https://github.com/pirate/ArchiveBox for help.')
            raise SystemExit(1)


def check_url_parsing():
    """Check that plain text regex URL parsing works as expected"""
    test_urls = '''
    https://example1.com/what/is/happening.html?what=1#how-about-this=1
    https://example2.com/what/is/happening/?what=1#how-about-this=1
    HTtpS://example3.com/what/is/happening/?what=1#how-about-this=1f
    https://example4.com/what/is/happening.html
    https://example5.com/
    https://example6.com

    <test>http://example7.com</test>
    [https://example8.com/what/is/this.php?what=1]
    [and http://example9.com?what=1&other=3#and-thing=2]
    <what>https://example10.com#and-thing=2 "</about>
    abc<this["https://example11.com/what/is#and-thing=2?whoami=23&where=1"]that>def
    sdflkf[what](https://example12.com/who/what.php?whoami=1#whatami=2)?am=hi
    example13.bada
    and example14.badb
    <or>htt://example15.badc</that>
    '''
    # print('\n'.join(re.findall(URL_REGEX, test_urls)))
    assert len(re.findall(URL_REGEX, test_urls)) == 12


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

    def progress_bar(seconds, prefix):
        """show timer in the form of progress bar, with percentage and seconds remaining"""
        chunk = '█' if sys.stdout.encoding == 'UTF-8' else '#'
        chunks = TERM_WIDTH - len(prefix) - 20  # number of progress chunks to show (aka max bar width)
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

    p = Process(target=progress_bar, args=(seconds, prefix))
    p.start()

    def end():
        """immediately finish progress and clear the progressbar line"""

        # protect from double termination
        #if p is None or not hasattr(p, 'kill'):
        #    return
        nonlocal p
        if p is not None:
            p.terminate()
        p = None

        sys.stdout.write('\r{}{}\r'.format((' ' * TERM_WIDTH), ANSI['reset']))  # clear whole terminal line
        sys.stdout.flush()

    return end

def pretty_path(path):
    """convert paths like .../ArchiveBox/archivebox/../output/abc into output/abc"""
    return path.replace(REPO_DIR + '/', '')


def save_stdin_source(raw_text):
    if not os.path.exists(SOURCES_DIR):
        os.makedirs(SOURCES_DIR)

    ts = str(datetime.now().timestamp()).split('.', 1)[0]

    source_path = os.path.join(SOURCES_DIR, '{}-{}.txt'.format('stdin', ts))

    with open(source_path, 'w', encoding='utf-8') as f:
        f.write(raw_text)

    return source_path


def fetch_page_content(url, timeout=TIMEOUT):
    req = Request(url, headers={'User-Agent': WGET_USER_AGENT})

    if CHECK_SSL_VALIDITY:
        resp = urlopen(req, timeout=timeout)
    else:
        import ssl
        insecure = ssl._create_unverified_context()
        resp = urlopen(req, timeout=timeout, context=insecure)

    encoding = resp.headers.get_content_charset() or 'utf-8'
    return resp.read().decode(encoding)


def save_remote_source(url, timeout=TIMEOUT):
    """download a given url's content into downloads/domain.txt"""

    if not os.path.exists(SOURCES_DIR):
        os.makedirs(SOURCES_DIR)

    ts = str(datetime.now().timestamp()).split('.', 1)[0]

    source_path = os.path.join(SOURCES_DIR, '{}-{}.txt'.format(domain(url), ts))

    print('{}[*] [{}] Downloading {}{}'.format(
        ANSI['green'],
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        url,
        ANSI['reset'],
    ))
    end = progress(TIMEOUT, prefix='      ')
    try:
        downloaded_xml = fetch_page_content(url, timeout=timeout)
        end()
    except Exception as e:
        end()
        print('{}[!] Failed to download {}{}\n'.format(
            ANSI['red'],
            url,
            ANSI['reset'],
        ))
        print('    ', e)
        raise SystemExit(1)

    with open(source_path, 'w', encoding='utf-8') as f:
        f.write(downloaded_xml)

    print('    > {}'.format(pretty_path(source_path)))

    return source_path


def fetch_page_title(url, timeout=10, progress=SHOW_PROGRESS):
    """Attempt to guess a page's title by downloading the html"""
    if not FETCH_TITLE:
        return None

    try:
        if progress:
            sys.stdout.write('.')
            sys.stdout.flush()

        html = fetch_page_content(url, timeout=timeout)

        match = re.search(HTML_TITLE_REGEX, html)
        return match.group(1).strip() if match else None
    except Exception as err:
        # print('[!] Failed to fetch title because of {}: {}'.format(
        #     err.__class__.__name__,
        #     err,
        # ))
        return None


def str_between(string, start, end=None):
    """(<abc>12345</def>, <abc>, </def>)  ->  12345"""

    content = string.split(start, 1)[-1]
    if end is not None:
        content = content.rsplit(end, 1)[0]

    return content

def get_link_type(link):
    """Certain types of links need to be handled specially, this figures out when that's the case"""

    if extension(link['url']) == 'pdf':
        return 'PDF'
    elif extension(link['url']) in ('pdf', 'png', 'jpg', 'jpeg', 'svg', 'bmp', 'gif', 'tiff', 'webp'):
        return 'image'
    elif 'wikipedia.org' in domain(link['url']).lower():
        return 'wiki'
    elif 'youtube.com' in domain(link['url']).lower():
        return 'youtube'
    elif 'soundcloud.com' in domain(link['url']).lower():
        return 'soundcloud'
    elif 'youku.com' in domain(link['url']).lower():
        return 'youku'
    elif 'vimeo.com' in domain(link['url']).lower():
        return 'vimeo'
    return None

def merge_links(a, b):
    """deterministially merge two links, favoring longer field values over shorter,
    and "cleaner" values over worse ones.
    """
    longer = lambda key: (a[key] if len(a[key]) > len(b[key]) else b[key]) if (a[key] and b[key]) else (a[key] or b[key])
    earlier = lambda key: a[key] if a[key] < b[key] else b[key]
    
    url = longer('url')
    longest_title = longer('title')
    cleanest_title = a['title'] if '://' not in (a['title'] or '') else b['title']
    link = {
        'timestamp': earlier('timestamp'),
        'url': url,
        'domain': domain(url),
        'base_url': base_url(url),
        'tags': longer('tags'),
        'title': longest_title if '://' not in (longest_title or '') else cleanest_title,
        'sources': list(set(a.get('sources', []) + b.get('sources', []))),
    }
    link['type'] = get_link_type(link)
    return link

def find_link(folder, links):
    """for a given archive folder, find the corresponding link object in links"""
    url = parse_url(folder)
    if url:
        for link in links:
            if (base_url(link['url']) in url) or (url in link['url']):
                return link

    timestamp = folder.split('.')[0]
    for link in links:
        if link['timestamp'].startswith(timestamp):
            if domain(link['url']) in os.listdir(os.path.join(ARCHIVE_DIR, folder)):
                return link      # careful now, this isn't safe for most ppl
            if domain(link['url']) in parse_url(folder):
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
                    return base_url(link['url'])
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
        print('\nJust run ArchiveBox again to pick up where you left off.')
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
    if not (url_in_folder in base_url(link['url'])
            or base_url(link['url']) in url_in_folder):
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
        print('[!] Warning! {} folders need to be merged, fix by running ArchiveBox.'.format(len(bad_folders)))

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
        return urlencode(base_url(link['url']))

    # Since the wget algorithm to for -E (appending .html) is incredibly complex
    # instead of trying to emulate it here, we just look in the output folder
    # to see what html file wget actually created as the output
    wget_folder = base_url(link['url']).rsplit('/', 1)[0].split('/')
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
    #     return urlencode(base_url(link['url']))
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
    #         return urlencode(base_url(link['url']) + '/index.html')


def derived_link_info(link):
    """extend link info with the archive urls and other derived data"""

    url = link['url']

    to_date_str = lambda ts: datetime.fromtimestamp(Decimal(ts)).strftime('%Y-%m-%d %H:%M')

    extended_info = {
        **link,
        'title': link['title'] or base_url(url),
        'date': to_date_str(link['timestamp']),
        'updated_date': to_date_str(link['updated']) if 'updated' in link else None,
        'base_url': base_url(url),
        'domain': domain(url),
        'basename': basename(url),
        'path': path(url),
        'type': link['type'] or 'website',
        'tags': link['tags'] or 'untagged',
    }

    # Archive Method Output URLs
    extended_info = {
        **extended_info,
        'favicon_url': 'archive/{timestamp}/favicon.ico'.format(**extended_info),
        'google_favicon_url': 'https://www.google.com/s2/favicons?domain={domain}'.format(**extended_info),
        'files_url': 'archive/{timestamp}/index.html'.format(**extended_info),
        'archive_url': 'archive/{}/{}'.format(link['timestamp'], wget_output_path(link) or 'index.html'),
        'warc_url': 'archive/{timestamp}/warc'.format(**extended_info),
        'pdf_url': 'archive/{timestamp}/output.pdf'.format(**extended_info),
        'screenshot_url': 'archive/{timestamp}/screenshot.png'.format(**extended_info),
        'dom_url': 'archive/{timestamp}/output.html'.format(**extended_info),
        'archive_org_url': 'https://web.archive.org/web/{base_url}'.format(**extended_info),
        'git_url': 'archive/{timestamp}/git'.format(**extended_info),
        'media_url': 'archive/{timestamp}/media'.format(**extended_info),
        
    }

    # PDF and images are handled slightly differently
    # wget, screenshot, & pdf urls all point to the same file
    if link['type'] in ('PDF', 'image'):
        extended_info.update({
            'title': basename(link['url']),
            'archive_url': 'archive/{timestamp}/{base_url}'.format(**extended_info),
            'pdf_url': 'archive/{timestamp}/{base_url}'.format(**extended_info),
            'screenshot_url': 'archive/{timestamp}/{base_url}'.format(**extended_info),
            'dom_url': 'archive/{timestamp}/{base_url}'.format(**extended_info),
        })

    return extended_info


def run(*popenargs, input=None, capture_output=False, timeout=None, check=False, **kwargs):
    """Patched of subprocess.run to fix blocking io making timeout=innefective"""

    if input is not None:
        if 'stdin' in kwargs:
            raise ValueError('stdin and input arguments may not both be used.')
        kwargs['stdin'] = PIPE

    if capture_output:
        if ('stdout' in kwargs) or ('stderr' in kwargs):
            raise ValueError('stdout and stderr arguments may not be used '
                             'with capture_output.')
        kwargs['stdout'] = PIPE
        kwargs['stderr'] = PIPE

    with Popen(*popenargs, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except TimeoutExpired:
            process.kill()
            try:
                stdout, stderr = process.communicate(input, timeout=2)
            except:
                pass
            raise TimeoutExpired(popenargs[0][0], timeout)
        except BaseException as err:
            process.kill()
            # We don't call process.wait() as .__exit__ does that for us.
            raise 
        retcode = process.poll()
        if check and retcode:
            raise CalledProcessError(retcode, process.args,
                                     output=stdout, stderr=stderr)
    return CompletedProcess(process.args, retcode, stdout, stderr)


def check_link_structure(link):
    assert isinstance(link, dict)
    assert isinstance(link.get('url'), str)
    assert len(link['url']) > 2
    assert len(re.findall(URL_REGEX, link['url'])) == 1


def check_links_structure(links):
    assert isinstance(links, list)
    if links:
        check_link_structure(links[0])
