#!/usr/bin/env python3
# Bookmark Archiver
# Nick Sweeting 2017 | MIT License
# https://github.com/pirate/bookmark-archiver

import re
import os
import sys
import json
import time

from datetime import datetime
from subprocess import run, PIPE, DEVNULL

__DESCRIPTION__ = 'Bookmark Archiver: Create a browsable html archive of a list of links.'
__DOCUMENTATION__ = 'https://github.com/pirate/bookmark-archiver'

### SETTINGS

INDEX_TEMPLATE = 'index_template.html'

# os.getenv('VARIABLE', 'DEFAULT') gets the value of environment
# variable "VARIABLE" and if it is not set, sets it to 'DEFAULT'

# for boolean values, check to see if the string is 'true', and
# if so, the python variable will be True

FETCH_WGET =             os.getenv('FETCH_WGET',             'True'             ).lower() == 'true'
FETCH_PDF =              os.getenv('FETCH_PDF',              'True'             ).lower() == 'true'
FETCH_SCREENSHOT =       os.getenv('FETCH_SCREENSHOT',       'True'             ).lower() == 'true'
FETCH_FAVICON =          os.getenv('FETCH_FAVICON',          'True'             ).lower() == 'true'
SUBMIT_ARCHIVE_DOT_ORG = os.getenv('SUBMIT_ARCHIVE_DOT_ORG', 'True'             ).lower() == 'true'
RESOLUTION =             os.getenv('RESOLUTION',             '1440,900'         )
ARCHIVE_PERMISSIONS =    os.getenv('ARCHIVE_PERMISSIONS',    '755'              )
CHROME_BINARY =          os.getenv('CHROME_BINARY',          'chromium-browser' )  # change to google-chrome browser if using google-chrome
WGET_BINARY =            os.getenv('WGET_BINARY',            'wget'             )


def check_dependencies():
    print('[*] Checking Dependencies:')
    if FETCH_PDF or FETCH_SCREENSHOT:
        if run(['which', CHROME_BINARY]).returncode:
            print('[X] Missing dependency: {}'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

        # parse chrome --version e.g. Google Chrome 61.0.3114.0 canary / Chromium 59.0.3029.110 built on Ubuntu, running on Ubuntu 16.04
        result = run([CHROME_BINARY, '--version'], stdout=PIPE)
        version = result.stdout.decode('utf-8').replace('Google Chrome ', '').replace('Chromium ', '').split(' ', 1)[0].split('.', 1)[0]  # TODO: regex might be better
        if int(version) < 59:
            print('[X] Chrome version must be 59 or greater for headless PDF and screenshot saving')
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_WGET:
        if run(['which', 'wget']).returncode:
            print('[X] Missing dependency: wget')
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_FAVICON or SUBMIT_ARCHIVE_DOT_ORG:
        if run(['which', 'curl']).returncode:
            print('[X] Missing dependency: curl')
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)


### PARSING READER LIST EXPORTS

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
    return None

def parse_pocket_export(html_file):
    """Parse Pocket-format bookmarks export files (produced by getpocket.com/export/)"""

    html_file.seek(0)
    pattern = re.compile("^\\s*<li><a href=\"(.+)\" time_added=\"(\\d+)\" tags=\"(.*)\">(.+)</a></li>", re.UNICODE)   # see sample input in ./example_ril_export.html
    for line in html_file:
        match = pattern.search(line)
        if match:
            fixed_url = match.group(1).replace('http://www.readability.com/read?url=', '')           # remove old readability prefixes to get original url
            without_scheme = fixed_url.replace('http://', '').replace('https://', '')
            info = {
                'url': fixed_url,
                'domain': without_scheme.split('/')[0],    # without pathname
                'base_url': without_scheme.split('?')[0],  # without query args
                'time': datetime.fromtimestamp(int(match.group(2))).strftime('%Y-%m-%d %H:%M'),
                'timestamp': match.group(2),
                'tags': match.group(3),
                'title': match.group(4).replace(' — Readability', '').replace('http://www.readability.com/read?url=', '') or without_scheme,
            }
            info['type'] = get_link_type(info)
            yield info

def parse_json_export(json_file):
    """Parse JSON-format bookmarks export files (produced by pinboard.in/export/)"""

    json_file.seek(0)
    json_content = json.load(json_file)
    for line in json_content:
        if line:
            erg = line
            info = {
                'url': erg['href'],
                'domain': erg['href'].replace('http://', '').replace('https://', '').split('/')[0],
                'base_url': erg['href'].replace('https://', '').replace('http://', '').split('?')[0],
                'time': datetime.fromtimestamp(int(time.mktime(time.strptime(erg['time'].split(',')[0], '%Y-%m-%dT%H:%M:%SZ')))),
                'timestamp': str(int(time.mktime(time.strptime(erg['time'].split(',')[0], '%Y-%m-%dT%H:%M:%SZ')))),
                'tags': erg['tags'],
                'title': erg['description'].replace(' — Readability', ''),
            }
            info['type'] = get_link_type(info)
            yield info

def parse_bookmarks_export(html_file):
    """Parse netscape-format bookmarks export files (produced by all browsers)"""

    html_file.seek(0)
    pattern = re.compile("<a href=\"(.+?)\" add_date=\"(\\d+)\"[^>]*>(.+)</a>", re.UNICODE | re.IGNORECASE)
    for line in html_file:
        match = pattern.search(line)
        if match:
            url = match.group(1)
            secs = match.group(2)
            dt = datetime.fromtimestamp(int(secs))

            info = {
                'url': url,
                'domain': url.replace('http://', '').replace('https://', '').split('/')[0],
                'base_url': url.replace('https://', '').replace('http://', '').split('?')[0],
                'time': dt,
                'timestamp': secs,
                'tags': "",
                'title': match.group(3),
            }

            info['type'] = get_link_type(info)
            yield info


### ACHIVING FUNCTIONS

def fetch_wget(out_dir, link, overwrite=False):
    """download full site using wget"""

    domain = link['base_url'].split('/', 1)[0]
    if not os.path.exists('{}/{}'.format(out_dir, domain)) or overwrite:
        print('    - Downloading Full Site')
        CMD = [
            *'wget --no-clobber --page-requisites --adjust-extension --convert-links --no-parent'.split(' '),
        ]
        try:
            output = run(CMD, stdout=DEVNULL, stderr=PIPE, cwd=out_dir, timeout=20)  # dom.html
            if output.returncode:
                print(output.stderr.read())
                raise Exception('Failed to wget download')
        except Exception as e:
            print('      Exception: {} {}'.format(e.__class__.__name__, e))
    else:
        print('    √ Skipping site download')

def fetch_pdf(out_dir, link, overwrite=False):
    """print PDF of site to file using chrome --headless"""

    if (not os.path.exists('{}/output.pdf'.format(out_dir)) or overwrite) and link['type'] not in ('PDF', 'image'):
        print('    - Printing PDF')
        chrome_args = '--headless --disable-gpu --print-to-pdf'.split(' ')
        try:
            result = run([CHROME_BINARY, *chrome_args, link['url']], stdout=DEVNULL, stderr=PIPE, cwd=out_dir, timeout=20)  # output.pdf
            if run(['chmod', ARCHIVE_PERMISSIONS, 'output.pdf'], stdout=DEVNULL, stderr=DEVNULL, timeout=5).returncode:
                print(result.stderr.read())
                raise Exception('Failed to print PDF')
        except Exception as e:
            print('      Exception: {} {}'.format(e.__class__.__name__, e))
    else:
        print('    √ Skipping PDF print')

def fetch_screenshot(out_dir, link, overwrite=False):
    """take screenshot of site using chrome --headless"""

    if (not os.path.exists('{}/screenshot.png'.format(out_dir)) or overwrite) and link['type'] not in ('PDF', 'image'):
        print('    - Snapping Screenshot')
        chrome_args = '--headless --disable-gpu --screenshot'.split(' ')
        try:
            result = run([CHROME_BINARY, *chrome_args, '--window-size={}'.format(RESOLUTION), link['url']], stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=20)  # sreenshot.png
            if run(['chmod', ARCHIVE_PERMISSIONS, 'screenshot.png'], stdout=DEVNULL, stderr=DEVNULL, timeout=5).returncode:
                print(result.stderr.read())
                raise Exception('Failed to take screenshot')
        except Exception as e:
            print('      Exception: {} {}'.format(e.__class__.__name__, e))
    else:
        print('    √ Skipping screenshot')

def archive_dot_org(out_dir, link, overwrite=False):
    """submit site to archive.org for archiving via their service, save returned archive url"""
    if (not os.path.exists('{}/archive.org.txt'.format(out_dir)) or overwrite):
        print('    - Submitting to archive.org')
        submit_url = 'https://web.archive.org/save/{}'.format(link['url'].split('?', 1)[0])

        success = False
        try:
            result = run(['curl', '-I', submit_url], stdout=PIPE, stderr=DEVNULL, cwd=out_dir, timeout=20)  # archive.org
            headers = result.stdout.splitlines()
            content_location = [h for h in headers if b'Content-Location: ' in h]
            if content_location:
                archive_path = content_location[0].split(b'Content-Location: ', 1)[-1].decode('utf-8')
                saved_url = 'https://web.archive.org{}'.format(archive_path)
                success = True
            else:
                raise Exception('Failed to find Content-Location URL in Archive.org response headers.')
        except Exception as e:
            print('      Exception: {} {}'.format(e.__class__.__name__, e))

        if success:
            with open('{}/archive.org.txt'.format(out_dir), 'w') as f:
                f.write(saved_url)

    else:
        print('    √ Skipping archive.org')

def fetch_favicon(out_dir, link, overwrite=False):
    """download site favicon from google's favicon api"""

    if not os.path.exists('{}/favicon.ico'.format(out_dir)) or overwrite:
        print('    - Fetching Favicon')
        CMD = 'curl https://www.google.com/s2/favicons?domain={domain}'.format(**link).split(' ')
        fout = open('{}/favicon.ico'.format(out_dir), 'w')
        try:
            run([*CMD], stdout=fout, stderr=DEVNULL, cwd=out_dir, timeout=20)  # dom.html
        except Exception as e:
            print('      Exception: {} {}'.format(e.__class__.__name__, e))
        fout.close()
    else:
        print('    √ Skipping favicon')


### ORCHESTRATION

def next_uniq_timestamp(used_timestamps, timestamp):
    """resolve duplicate timestamps by appending a decimal 1234, 1234 -> 1234.1, 1234.2"""

    if timestamp not in used_timestamps:
        return timestamp

    if '.' in timestamp:
        timestamp, nonce = timestamp.split('.')
        nonce = int(nonce)
    else:
        nonce = 1

    new_timestamp = '{}.{}'.format(timestamp, nonce)

    while new_timestamp in used_timestamps:
        nonce += 1
        new_timestamp = '{}.{}'.format(timestamp, nonce)

    return new_timestamp

def uniquefied_links(links):
    """uniqueify link timestamps by de-duping using url, returns links sorted most recent -> oldest

    needed because firefox will produce exports where many links share the same timestamp, this func
    ensures that all non-duplicate links have monotonically increasing timestamps
    """

    links = list(reversed(sorted(links, key=lambda l: (l['timestamp'], l['url']))))
    seen_timestamps = {}

    for link in links:
        t = link['timestamp']
        if t in seen_timestamps:
            if link['url'] == seen_timestamps[t]['url']:
                # don't create new unique timestamp if link is the same
                continue
            else:
                # resolve duplicate timstamp by appending a decimal
                link['timestamp'] = next_uniq_timestamp(seen_timestamps, link['timestamp'])
        seen_timestamps[link['timestamp']] = link

    return links

def valid_links(links):
    """remove chrome://, about:// or other schemed links that cant be archived"""
    return (link for link in links if link['url'].startswith('http') or link['url'].startswith('ftp'))


def dump_index(links, service):
    """create index.html file for a given list of links and service"""

    with open(INDEX_TEMPLATE, 'r') as f:
        index_html = f.read()

    # TODO: refactor this out into index_template.html
    link_html = """\
    <tr>
        <td>{time}</td>
        <td><a href="archive/{timestamp}/{base_url}" style="font-size:1.4em;text-decoration:none;color:black;" title="{title}">
            <img src="archive/{timestamp}/favicon.ico">
            {title} <small style="background-color: #eee;border-radius:4px; float:right">{tags}</small>
        </td>
        <td style="text-align:center"><a href="archive/{timestamp}/" title="Files">📂</a></td>
        <td style="text-align:center"><a href="{pdf_link}" title="PDF">📄</a></td>
        <td style="text-align:center"><a href="{screenshot_link}" title="Screenshot">🖼</a></td>
        <td style="text-align:center"><a href="https://web.archive.org/web/{base_url}" title="Archive.org">🏛</a></td>
        <td>🔗 <img src="https://www.google.com/s2/favicons?domain={domain}" height="16px"> <a href="{url}">{url}</a></td>
    </tr>"""

    def get_template_vars(link):
        # since we dont screenshot or PDF links that are images or PDFs, change those links to point to the wget'ed file
        link_info = {**link}

        # add link type to title
        if link['type']:
            link_info.update({'title': '{title} ({type})'.format(**link)})

        # PDF and images link to wgetted version, since we dont re-screenshot/pdf them
        if link['type'] in ('PDF', 'image'):
            link_info.update({
                'pdf_link': 'archive/{timestamp}/{base_url}'.format(**link),
                'screenshot_link': 'archive/{timestamp}/{base_url}'.format(**link),
            })
        else:
            link_info.update({
                'pdf_link': 'archive/{timestamp}/output.pdf'.format(**link),
                'screenshot_link': 'archive/{timestamp}/screenshot.png'.format(**link)
            })
        return link_info

    article_rows = '\n'.join(
        link_html.format(**get_template_vars(link)) for link in links
    )

    template_vars = (datetime.now().strftime('%Y-%m-%d %H:%M'), article_rows)

    with open(''.join((service, '/index.html')), 'w') as f:
        f.write(index_html.format(*template_vars))


def dump_website(link, service, overwrite=False):
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    print('[+] [{timestamp} ({time})] "{title}": {base_url}'.format(**link))

    out_dir = ''.join((service, '/archive/{timestamp}')).format(**link)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    run(['chmod', ARCHIVE_PERMISSIONS, out_dir], timeout=5)

    if link['type']:
        print('    i Type: {}'.format(link['type']))

    if not (link['url'].startswith('http') or link['url'].startswith('ftp')):
        print('    X Skipping: invalid link.')
        return

    if FETCH_WGET:
        fetch_wget(out_dir, link, overwrite=overwrite)

    if FETCH_PDF:
        fetch_pdf(out_dir, link, overwrite=overwrite)

    if FETCH_SCREENSHOT:
        fetch_screenshot(out_dir, link, overwrite=overwrite)

    if SUBMIT_ARCHIVE_DOT_ORG:
        archive_dot_org(out_dir, link, overwrite=overwrite)

    if FETCH_FAVICON:
        fetch_favicon(out_dir, link, overwrite=overwrite)


def create_archive(export_file, service=None, resume=None):
    """update or create index.html and download archive of all links"""

    with open(export_file, 'r', encoding='utf-8') as f:
        print('[+] [{}] Starting archive from {} export file.'.format(
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            export_file
        ))

        # if specific service was passed via command line
        if service == "pocket":
            links = parse_pocket_export(f)
        elif service == "pinboard":
            links = parse_json_export(f)
        elif service == "bookmarks":
            links = parse_bookmarks_export(f)
        else:
            # otherwise try all parsers until one works
            try:
                links = list(parse_json_export(f))
                service = 'pinboard'
            except Exception:
                links = list(parse_pocket_export(f))
                if links:
                    service = 'pocket'
                else:
                    links = list(parse_bookmarks_export(f))
                    service = 'bookmarks'

        links = valid_links(links)              # remove chrome://, about:, mailto: etc.
        links = uniquefied_links(links)         # fix duplicate timestamps, returns sorted list

        if resume:
            try:
                links = [
                    link
                    for link in links
                    if float(link['timestamp']) >= float(resume)
                ]
            except TypeError:
                print('Resume value and all timestamp values must be valid numbers.')

    if not links:
        print('[X] No links found in {}, is it a {} export file?'.format(export_file, service))
        raise SystemExit(1)

    if not os.path.exists(service):
        os.makedirs(service)

    if not os.path.exists(''.join((service, '/archive'))):
        os.makedirs(''.join((service, '/archive')))

    dump_index(links, service)

    run(['chmod', '-R', ARCHIVE_PERMISSIONS, service], timeout=30)

    print('[*] [{}] Created archive index with {} links.'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        len(links),
    ))

    check_dependencies()

    for link in links:
        dump_website(link, service)

    print('[√] [{}] Archive update complete.'.format(datetime.now()))



if __name__ == '__main__':
    argc = len(sys.argv)

    if argc < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print(__DESCRIPTION__)
        print("Documentation:     {}".format(__DOCUMENTATION__))
        print("")
        print("Usage:")
        print("    ./archive.py ~/Downloads/bookmarks_export.html")
        print("")
        raise SystemExit(0)

    export_file = sys.argv[1]                                       # path to export file
    export_type = sys.argv[2] if argc > 2 else None                 # select export_type for file format select
    resume_from = sys.argv[3] if argc > 3 else None                 # timestamp to resume dowloading from

    create_archive(export_file, service=export_type, resume=resume_from)
