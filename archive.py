#!/usr/bin/env python3

# wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
# sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
# apt update; apt install google-chrome-beta

import re
import os
import sys

from datetime import datetime
from subprocess import run, DEVNULL


RESOLUTION = '1440,900'


def parse_pocket_export(html):
    pattern = re.compile("^\\s*<li><a href=\"(.+)\" time_added=\"(\\d+)\" tags=\"(.*)\">(.+)</a></li>", re.UNICODE)
    for line in html:
        match = pattern.search(line)
        if match:
            yield {
                'url': match.group(1).replace('http://www.readability.com/read?url=', ''),
                'domain': match.group(1).replace('http://', '').replace('https://', '').split('/')[0],
                'base_url': match.group(1).replace('https://', '').replace('http://', '').split('?')[0],
                'time': datetime.fromtimestamp(int(match.group(2))),
                'timestamp': match.group(2),
                'tags': match.group(3),
                'title': match.group(4).replace(' — Readability', '').replace('http://www.readability.com/read?url=', ''),
            }

def dump_index(links):
    with open('index_template.html', 'r') as f:
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

    with open('pocket/index.html', 'w') as f:
        article_rows = '\n'.join(
            link_html.format(**link) for link in links
        )
        f.write(index_html.format(datetime.now().strftime('%Y-%m-%d %H:%M'), article_rows))


def dump_website(link, overwrite=False):
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    print('[+] [{time}] Archiving "{title}": {url}'.format(**link))

    out_dir = 'pocket/archive/{timestamp}'.format(**link)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    if link['base_url'].endswith('.pdf'):
        print('    i PDF File')
    elif 'youtube.com' in link['domain']:
        print('    i Youtube Video')
    elif 'wikipedia.org' in link['domain']:
        print('    i Wikipedia Article')

    # download full site
    if not os.path.exists('{}/{}'.format(out_dir, link['domain'])) or overwrite:
        print('    - Downloading Full Site')
        CMD = [
            *'wget --no-clobber --page-requisites --adjust-extension --convert-links --no-parent'.split(' '),
            link['url'],
        ]
        try:
            proc = run(CMD, stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=20)  # dom.html
        except Exception as e:
            print('      Exception: {}'.format(e.__class__.__name__))
    else:
        print('    √ Skipping site download')

    # download PDF
    if (not os.path.exists('{}/output.pdf'.format(out_dir)) or overwrite) and not link['base_url'].endswith('.pdf'):
        print('    - Printing PDF')
        CMD = 'google-chrome --headless --disable-gpu --print-to-pdf'.split(' ')
        try:
            proc = run([*CMD, link['url']], stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=20)  # output.pdf
        except Exception as e:
            print('      Exception: {}'.format(e.__class__.__name__))
    else:
        print('    √ Skipping PDF print')

    # take screenshot
    if (not os.path.exists('{}/screenshot.png'.format(out_dir)) or overwrite) and not link['base_url'].endswith('.pdf'):
        print('    - Snapping Screenshot')
        CMD = 'google-chrome --headless --disable-gpu --screenshot'.split(' ')
        try:
            proc = run([*CMD, '--window-size={}'.format(RESOLUTION), link['url']], stdout=DEVNULL, stderr=DEVNULL, cwd=out_dir, timeout=20)  # sreenshot.png
        except Exception as e:
            print('      Exception: {}'.format(e.__class__.__name__))
    else:
        print('    √ Skipping screenshot')

    # download favicon
    if not os.path.exists('{}/favicon.ico'.format(out_dir)) or overwrite:
        print('    - Fetching Favicon')
        CMD = 'curl https://www.google.com/s2/favicons?domain={domain}'.format(**link).split(' ')
        fout = open('{}/favicon.ico'.format(out_dir), 'w')
        try:
            proc = run([*CMD], stdout=fout, stderr=DEVNULL, cwd=out_dir, timeout=20)  # dom.html
        except Exception as e:
            print('      Exception: {}'.format(e.__class__.__name__))
        fout.close()
    else:
        print('    √ Skipping favicon')

    run(['chmod', '-R', '755', out_dir], timeout=1)

def create_archive(pocket_file, resume=None):
    print('[+] [{}] Starting pocket archive from {}'.format(datetime.now(), pocket_file))

    if not os.path.exists('pocket'):
        os.makedirs('pocket')

    if not os.path.exists('pocket/archive'):
        os.makedirs('pocket/archive')

    with open(pocket_file, 'r', encoding='utf-8') as f:
        links = parse_pocket_export(f)
        links = list(reversed(sorted(links, key=lambda l: l['timestamp'])))  # most recent first
        if resume:
            links = [link for link in links if link['timestamp'] >= resume]

    if not links:
        print('[X] No links found in {}'.format(pocket_file))
        raise SystemExit(1)

    dump_index(links)

    run(['chmod', '-R', '755', 'pocket'], timeout=1)

    print('[*] [{}] Created archive index.'.format(datetime.now()))

    for link in links:
        dump_website(link)

    print('[√] [{}] Archive complete.'.format(datetime.now()))



if __name__ == '__main__':
    pocket_file = 'ril_export.html'
    resume = None
    try:
        pocket_file = sys.argv[1]
        resume = sys.argv[2]
    except IndexError:
        pass

    create_archive(pocket_file, resume=resume)
