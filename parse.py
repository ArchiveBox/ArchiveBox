import re
import json
from datetime import datetime

from util import (
    domain,
    base_url,
    get_str_between,
    get_link_type,
)


def parse_export(path):
    """parse a list of links dictionaries from a bookmark export file"""
    
    links = []
    with open(path, 'r', encoding='utf-8') as file:
        for service, parser_func in get_parsers().items():
            # otherwise try all parsers until one works
            try:
                links += list(parser_func(file))
                if links:
                    break
            except Exception as e:
                pass

    return links

def get_parsers():
    return {
        'pocket': parse_pocket_export,
        'pinboard': parse_json_export,
        'bookmarks': parse_bookmarks_export,
        'rss': parse_rss_export,
    }

def parse_pocket_export(html_file):
    """Parse Pocket-format bookmarks export files (produced by getpocket.com/export/)"""

    html_file.seek(0)
    pattern = re.compile("^\\s*<li><a href=\"(.+)\" time_added=\"(\\d+)\" tags=\"(.*)\">(.+)</a></li>", re.UNICODE)   # see sample input in ./example_ril_export.html
    for line in html_file:
        match = pattern.search(line)
        if match:
            fixed_url = match.group(1).replace('http://www.readability.com/read?url=', '')           # remove old readability prefixes to get original url
            time = datetime.fromtimestamp(float(match.group(2)))
            info = {
                'url': fixed_url,
                'domain': domain(fixed_url),
                'base_url': base_url(fixed_url),
                'timestamp': str(time.timestamp()),
                'tags': match.group(3),
                'title': match.group(4).replace(' — Readability', '').replace('http://www.readability.com/read?url=', '') or base_url(fixed_url),
                'sources': [html_file.name],
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
            time = datetime.strptime(erg['time'].split(',', 1)[0], '%Y-%m-%dT%H:%M:%SZ')
            info = {
                'url': erg['href'],
                'domain': domain(erg['href']),
                'base_url': base_url(erg['href']),
                'timestamp': str(time.timestamp()),
                'tags': erg['tags'],
                'title': erg['description'].replace(' — Readability', ''),
                'sources': [json_file.name],
            }
            info['type'] = get_link_type(info)
            yield info

def parse_rss_export(rss_file):
    """Parse RSS XML-format files into links"""

    rss_file.seek(0)
    items = rss_file.read().split('</item>\n<item>')
    for item in items:
        # example item:
        # <item>
        # <title><![CDATA[How JavaScript works: inside the V8 engine]]></title>
        # <category>Unread</category>
        # <link>https://blog.sessionstack.com/how-javascript-works-inside</link>
        # <guid>https://blog.sessionstack.com/how-javascript-works-inside</guid>
        # <pubDate>Mon, 21 Aug 2017 14:21:58 -0500</pubDate>
        # </item>

        trailing_removed = item.split('</item>', 1)[0]
        leading_removed = trailing_removed.split('<item>', 1)[-1]
        rows = leading_removed.split('\n')

        row = lambda key: [r for r in rows if r.startswith('<{}>'.format(key))][0]

        title = get_str_between(row('title'), '<![CDATA[', ']]')
        url = get_str_between(row('link'), '<link>', '</link>')
        ts_str = get_str_between(row('pubDate'), '<pubDate>', '</pubDate>')
        time = datetime.strptime(ts_str, "%a, %d %b %Y %H:%M:%S %z")

        info = {
            'url': url,
            'domain': domain(url),
            'base_url': base_url(url),
            'timestamp': str(time.timestamp()),
            'tags': '',
            'title': title,
            'sources': [rss_file.name],
        }

        info['type'] = get_link_type(info)
        # import ipdb; ipdb.set_trace()
        yield info

def parse_bookmarks_export(html_file):
    """Parse netscape-format bookmarks export files (produced by all browsers)"""

    html_file.seek(0)
    pattern = re.compile("<a href=\"(.+?)\" add_date=\"(\\d+)\"[^>]*>(.+)</a>", re.UNICODE | re.IGNORECASE)
    for line in html_file:
        match = pattern.search(line)
        if match:
            url = match.group(1)
            time = datetime.fromtimestamp(float(match.group(2)))

            info = {
                'url': url,
                'domain': domain(url),
                'base_url': base_url(url),
                'timestamp': str(time.timestamp()),
                'tags': "",
                'title': match.group(3),
                'sources': [html_file.name],
            }

            info['type'] = get_link_type(info)
            yield info
