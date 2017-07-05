import re
import time
import json

from datetime import datetime


def parse_export(file, service=None):
    """parse a list of links dictionaries from a bookmark export file"""

    # if specific service was passed via command line
    if service == "pocket":
        links = parse_pocket_export(file)
    elif service == "pinboard":
        links = parse_json_export(file)
    elif service == "bookmarks":
        links = parse_bookmarks_export(file)
    else:
        # otherwise try all parsers until one works
        try:
            links = list(parse_json_export(file))
            service = 'pinboard'
        except Exception:
            links = list(parse_pocket_export(file))
            if links:
                service = 'pocket'
            else:
                links = list(parse_bookmarks_export(file))
                service = 'bookmarks'

    links = valid_links(links)              # remove chrome://, about:, mailto: etc.
    links = uniquefied_links(links)         # fix duplicate timestamps, returns sorted list
    return links, service


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
                'domain': without_scheme.split('/', 1)[0],    # without pathname
                'base_url': without_scheme.split('?', 1)[0],  # without query args
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
                'domain': erg['href'].replace('http://', '').replace('https://', '').split('/', 1)[0],
                'base_url': erg['href'].replace('https://', '').replace('http://', '').split('?', 1)[0],
                'time': datetime.fromtimestamp(int(time.mktime(time.strptime(erg['time'].split(',', 1)[0], '%Y-%m-%dT%H:%M:%SZ')))),
                'timestamp': str(int(time.mktime(time.strptime(erg['time'].split(',', 1)[0], '%Y-%m-%dT%H:%M:%SZ')))),
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
                'domain': url.replace('http://', '').replace('https://', '').split('/', 1)[0],
                'base_url': url.replace('https://', '').replace('http://', '').split('?', 1)[0],
                'time': dt,
                'timestamp': secs,
                'tags': "",
                'title': match.group(3),
            }

            info['type'] = get_link_type(info)
            yield info


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


def html_appended_url(link):
    """calculate the path to the wgetted .html file, since wget may
    adjust some paths to be different than the base_url path.

    See docs on wget --adjust-extension."""

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
                return '#'.join([without_scheme + 'index.html' + query + '.html', *split_url[1:]])
            return '#'.join([without_scheme + '.html', *split_url[1:]])


def derived_link_info(link):
    """extend link info with the archive urls and other derived data"""

    link_info = {
        **link,
        'files_url': 'archive/{timestamp}/'.format(**link),
        'archive_org_url': 'https://web.archive.org/web/{base_url}'.format(**link),
        'favicon_url': 'archive/{timestamp}/favicon.ico'.format(**link),
        'google_favicon_url': 'https://www.google.com/s2/favicons?domain={domain}'.format(**link),
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
    else:
        link_info.update({
            'archive_url': 'archive/{}/{}'.format(link['timestamp'], html_appended_url(link)),
            'pdf_link': 'archive/{timestamp}/output.pdf'.format(**link),
            'screenshot_link': 'archive/{timestamp}/screenshot.png'.format(**link)
        })
    return link_info
