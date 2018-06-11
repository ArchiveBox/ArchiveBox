"""
Everything related to parsing links from bookmark services.

For a list of supported services, see the README.md.
For examples of supported files see examples/.

Parsed link schema: {
    'url': 'https://example.com/example/?abc=123&xyc=345#lmnop',
    'domain': 'example.com',
    'base_url': 'example.com/example/',
    'timestamp': '15442123124234',
    'tags': 'abc,def',
    'title': 'Example.com Page Title',
    'sources': ['ril_export.html', 'downloads/getpocket.com.txt'],
}
"""

import re
import json
import xml.etree.ElementTree as etree

from datetime import datetime

from util import (
    domain,
    base_url,
    str_between,
    get_link_type,
)


def get_parsers(file):
    """return all parsers that work on a given file, defaults to all of them"""

    return {
        'pocket': parse_pocket_export,
        'pinboard': parse_json_export,
        'bookmarks': parse_bookmarks_export,
        'rss': parse_rss_export,
        'pinboard_rss': parse_pinboard_rss_feed,
        'medium_rss': parse_medium_rss_feed,
    }

def parse_links(path):
    """parse a list of links dictionaries from a bookmark export file"""
    
    links = []
    with open(path, 'r', encoding='utf-8') as file:
        for parser_func in get_parsers(file).values():
            # otherwise try all parsers until one works
            try:
                links += list(parser_func(file))
                if links:
                    break
            except (ValueError, TypeError, IndexError, AttributeError, etree.ParseError):
                # parser not supported on this file
                pass

    return links


def parse_pocket_export(html_file):
    """Parse Pocket-format bookmarks export files (produced by getpocket.com/export/)"""

    html_file.seek(0)
    pattern = re.compile("^\\s*<li><a href=\"(.+)\" time_added=\"(\\d+)\" tags=\"(.*)\">(.+)</a></li>", re.UNICODE)
    for line in html_file:
        # example line
        # <li><a href="http://example.com/ time_added="1478739709" tags="tag1,tag2">example title</a></li>
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
        # example line
        # {"href":"http:\/\/www.reddit.com\/r\/example","description":"title here","extended":"","meta":"18a973f09c9cc0608c116967b64e0419","hash":"910293f019c2f4bb1a749fb937ba58e3","time":"2014-06-14T15:51:42Z","shared":"no","toread":"no","tags":"reddit android"}]
        if line:
            erg = line
            if erg.get('timestamp'):
                timestamp = str(erg['timestamp']/10000000)  # chrome/ff histories use a very precise timestamp
            elif erg.get('time'):
                timestamp = str(datetime.strptime(erg['time'].split(',', 1)[0], '%Y-%m-%dT%H:%M:%SZ').timestamp())
            else:
                timestamp = str(datetime.now().timestamp())
            info = {
                'url': erg['href'],
                'domain': domain(erg['href']),
                'base_url': base_url(erg['href']),
                'timestamp': timestamp,
                'tags': erg.get('tags') or '',
                'title': (erg.get('description') or '').replace(' — Readability', ''),
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

        def get_row(key):
            return [r for r in rows if r.startswith('<{}>'.format(key))][0]

        title = str_between(get_row('title'), '<![CDATA[', ']]')
        url = str_between(get_row('link'), '<link>', '</link>')
        ts_str = str_between(get_row('pubDate'), '<pubDate>', '</pubDate>')
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

        yield info

def parse_bookmarks_export(html_file):
    """Parse netscape-format bookmarks export files (produced by all browsers)"""

    html_file.seek(0)
    pattern = re.compile("<a href=\"(.+?)\" add_date=\"(\\d+)\"[^>]*>(.+)</a>", re.UNICODE | re.IGNORECASE)
    for line in html_file:
        # example line
        # <DT><A HREF="https://example.com/?q=1+2" ADD_DATE="1497562974" LAST_MODIFIED="1497562974" ICON_URI="https://example.com/favicon.ico" ICON="data:image/png;base64,...">example bookmark title</A>
        
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

def parse_pinboard_rss_feed(rss_file):
    """Parse Pinboard RSS feed files into links"""

    rss_file.seek(0)
    root = etree.parse(rss_file).getroot()
    items = root.findall("{http://purl.org/rss/1.0/}item")
    for item in items:
        url = item.find("{http://purl.org/rss/1.0/}link").text
        tags = item.find("{http://purl.org/dc/elements/1.1/}subject").text
        title = item.find("{http://purl.org/rss/1.0/}title").text
        ts_str = item.find("{http://purl.org/dc/elements/1.1/}date").text
        #       = 🌈🌈🌈🌈
        #        = 🌈🌈🌈🌈
        #         = 🏆🏆🏆🏆
        
        # Pinboard includes a colon in its date stamp timezone offsets, which
        # Python can't parse. Remove it:
        if ":" == ts_str[-3:-2]:
            ts_str = ts_str[:-3]+ts_str[-2:]
        time = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")
        info = {
            'url': url,
            'domain': domain(url),
            'base_url': base_url(url),
            'timestamp': str(time.timestamp()),
            'tags': tags,
            'title': title,
            'sources': [rss_file.name],
        }
        info['type'] = get_link_type(info)
        yield info

def parse_medium_rss_feed(rss_file):
    """Parse Medium RSS feed files into links"""

    rss_file.seek(0)
    root = etree.parse(rss_file).getroot()
    items = root.find("channel").findall("item")
    for item in items:
        # for child in item:
        #     print(child.tag, child.text)
        url = item.find("link").text
        title = item.find("title").text
        ts_str = item.find("pubDate").text
        time = datetime.strptime(ts_str, "%a, %d %b %Y %H:%M:%S %Z")
        info = {
            'url': url,
            'domain': domain(url),
            'base_url': base_url(url),
            'timestamp': str(time.timestamp()),
            'tags': "",
            'title': title,
            'sources': [rss_file.name],
        }
        info['type'] = get_link_type(info)
        yield info
