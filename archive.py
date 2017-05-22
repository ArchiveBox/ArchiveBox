#!/usr/bin/env python3

# wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
# sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
# apt update; apt install google-chrome-beta

import re
import os
import sys
import json

from datetime import datetime
import time

from subprocess import run, DEVNULL

INDEX_TEMPLATE = 'index_template.html'

FETCH_WGET = True
FETCH_PDF = True
FETCH_SCREENSHOT = True
FETCH_FAVICON = True
RESOLUTION = '1440,900'

def check_dependencies():
    for dependency in ('google-chrome', 'wget'):
        if run(['which', dependency]).returncode:
            print('[X] Missing dependency: {}'.format(dependency))
            print('    See https://github.com/pirate/pocket-archive-stream for help.')
            raise SystemExit(1)


def parse_pocket_export(html):
    pattern = re.compile("^\\s*<li><a href=\"(.+)\" time_added=\"(\\d+)\" tags=\"(.*)\">(.+)</a></li>", re.UNICODE)   # see sample input in ./example_ril_export.html
    for line in html:
        match = pattern.search(line)
        if match:
            fixed_url = match.group(1).replace('http://www.readability.com/read?url=', '')           # remove old readability prefixes to get original url
            without_scheme = fixed_url.replace('http://', '').replace('https://', '')
            yield {
                'url': fixed_url,
                'domain': without_scheme.split('/')[0],    # without pathname
                'base_url': without_scheme.split('?')[0],  # without query args
                'time': datetime.fromtimestamp(int(match.group(2))),
                'timestamp': match.group(2),
                'tags': match.group(3),
                'title': match.group(4).replace(' — Readability', '').replace('http://www.readability.com/read?url=', '') or without_scheme,
            }

def parse_pinboard_export(html):
    json_content = json.load(html)
    for line in json_content:
        if line:
            erg = line
            yield {
                'url': erg['href'],
                'domain': erg['href'].replace('http://', '').replace('https://', '').split('/')[0],
                'base_url': erg['href'].replace('https://', '').replace('http://', '').split('?')[0],
                'time': datetime.fromtimestamp(time.mktime(time.strptime(erg['time'].split(',')[0],'%Y-%m-%dT%H:%M:%SZ'))),
                'timestamp': time.mktime(time.strptime(erg['time'].split(',')[0],'%Y-%m-%dT%H:%M:%SZ')),
                'tags': erg['tags'],
                'title': erg['description'].replace(' — Readability', ''),
            }

def dump_index(links, service):
    with open(INDEX_TEMPLATE, 'r') as f:
        index_html = f.read()

    link_html = """\
    <tr>
        <td>{time}</td>
        <td><a href="archive/{timestamp}/{base_url}" style="font-size:1.4em;text-decoration:none;color:black;" title="{title}">
            <img src="archive/{timestamp}/favicon.ico">
            {title}
        </td>
        <td style="text-align:center"><a href="archive/{timestamp}/" title="Files">📂</a></td>
        <td style="text-align:center"><a href="archive/{timestamp}/output.pdf" title="PDF">📄</a></td>
        <td style="text-align:center"><a href="archive/{timestamp}/screenshot.png" title="Screenshot">🖼</a></td>
        <td>🔗 <img src="https://www.google.com/s2/favicons?domain={domain}" height="16px"> <a href="{url}">{url}</a></td>
    </tr>"""

    with open(''.join((service,'/index.html')), 'w') as f:
        article_rows = '\n'.join(
            link_html.format(**link) for link in links
        )
        f.write(index_html.format(datetime.now().strftime('%Y-%m-%d %H:%M'), article_rows))

def fetch_wget(out_dir, link, overwrite=False):
    # download full site
    if not os.path.exists('{}/{}'.format(out_dir, link, overwrite=link['domain'])) or overwrite:
        print('    - Downloading Full Site')
        CMD = [
            *'wget --no-clobber --page-requisites --adjust-extension --convert-links --no-parent'.split(' '),
            link['url'],
        ]
        try:
            run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=20)  # dom.html
        except Exception as e:
            print('      Exception: {}'.format(e.__class__.__name__))
    else:
        print('    √ Skipping site download')

def fetch_pdf(out_dir, link, overwrite=False):
    # download PDF
    if (not os.path.exists('{}/output.pdf'.format(out_dir)) or overwrite) and not link['base_url'].endswith('.pdf'):
        print('    - Printing PDF')
        CMD = 'google-chrome --headless --disable-gpu --print-to-pdf'.split(' ')
        try:
            run([*CMD, link['url']], stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=20)  # output.pdf
        except Exception as e:
            print('      Exception: {}'.format(e.__class__.__name__))
    else:
        print('    √ Skipping PDF print')

def fetch_screenshot(out_dir, link, overwrite=False):
    # take screenshot
    if (not os.path.exists('{}/screenshot.png'.format(out_dir)) or overwrite) and not link['base_url'].endswith('.pdf'):
        print('    - Snapping Screenshot')
        CMD = 'google-chrome --headless --disable-gpu --screenshot'.split(' ')
        try:
            run([*CMD, '--window-size={}'.format(RESOLUTION), link['url']], stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=20)  # sreenshot.png
        except Exception as e:
            print('      Exception: {}'.format(e.__class__.__name__))
    else:
        print('    √ Skipping screenshot')

def fetch_favicon(out_dir, link, overwrite=False):
    # download favicon
    if not os.path.exists('{}/favicon.ico'.format(out_dir)) or overwrite:
        print('    - Fetching Favicon')
        CMD = 'curl https://www.google.com/s2/favicons?domain={domain}'.format(**link).split(' ')
        fout = open('{}/favicon.ico'.format(out_dir), 'w')
        try:
            run([*CMD], stdout=fout, stderr=DEVNULL, cwd=out_dir, timeout=20)  # dom.html
        except Exception as e:
            print('      Exception: {}'.format(e.__class__.__name__))
        fout.close()
    else:
        print('    √ Skipping favicon')


def dump_website(link, service, overwrite=False):
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    print('[+] [{time}] Archiving "{title}": {url}'.format(**link))

    out_dir = ''.join((service, '/archive/{timestamp}')).format(**link)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    if link['base_url'].endswith('.pdf'):
        print('    i PDF File')
    elif 'youtube.com' in link['domain']:
        print('    i Youtube Video')
    elif 'wikipedia.org' in link['domain']:
        print('    i Wikipedia Article')

    if FETCH_WGET:
        fetch_wget(out_dir, link, overwrite=overwrite)

    if FETCH_PDF:
        fetch_pdf(out_dir, link, overwrite=overwrite)

    if FETCH_SCREENSHOT:
        fetch_screenshot(out_dir, link, overwrite=overwrite)

    if FETCH_FAVICON:
        fetch_favicon(out_dir, link, overwrite=overwrite)

    run(['chmod', '-R', '755', out_dir], timeout=1)

def create_archive(service_file, service, resume=None):
    print('[+] [{}] Starting {} archive from {}'.format(datetime.now(), service, service_file))

    if not os.path.exists(service):
        os.makedirs(service)

    if not os.path.exists(''.join((service,'/archive'))):
        os.makedirs(''.join((service,'/archive')))

    with open(service_file, 'r', encoding='utf-8') as f:
        if service == "pocket":
            links = parse_pocket_export(f)
        elif service == "pinboard":
            links = parse_pinboard_export(f)
        links = list(reversed(sorted(links, key=lambda l: l['timestamp'])))  # most recent first
        if resume:
            links = [link for link in links if link['timestamp'] >= resume]

    if not links:
        if service == "pocket":
            print('[X] No links found in {}, is it a getpocket.com/export export?'.format(service_file))
        elif service == "pinboard":
            print ('[X] No links found in {}, is it a pinboard.in/export/format:json/ export?'.format(service_file))
        raise SystemExit(1)

    dump_index(links, service)

    run(['chmod', '-R', '755', service], timeout=1)

    print('[*] [{}] Created archive index.'.format(datetime.now()))

    check_dependencies()

    for link in links:
        dump_website(link, service)

    print('[√] [{}] Archive complete.'.format(datetime.now()))


if __name__ == '__main__':
    service_file = 'ril_export.html'
    argc = len(sys.argv)
    service_file = sys.argv[1] if argc > 1 else "ril_export.html" # path to export file
    service = sys.argv[2] if argc > 2 else "pocket" # select service for file format select
    resume = sys.argv[3] if argc > 3 else None # timestamp to resume dowloading from

    create_archive(service_file, service, resume=resume)
