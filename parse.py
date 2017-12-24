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
        'list': parse_list_export,
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
            except (ValueError, TypeError, IndexError):                
                # parser not supported on this file
                pass

    return links

def basic_link_info(url, f, title=None, time=datetime.now(), tags=""):
    info = {
        'url': url,
        'domain': domain(url),
        'base_url': base_url(url),
        'timestamp': str(time.timestamp()),
        'tags': tags,
        'title': title,
        'sources': [f.name],
    }
    info['type'] = get_link_type(info)
    return info

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
            info = basic_link_info(fixed_url,
                              html_file,
                              match.group(4).replace(' — Readability', '').replace('http://www.readability.com/read?url=', ''),
                              time,
                              match.group(3))
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
            time = datetime.strptime(erg['time'].split(',', 1)[0], '%Y-%m-%dT%H:%M:%SZ')
            info = basic_link_info(erg['href'],
                              json_file,
                              erg['description'].replace(' — Readability', ''),
                              time,
                              erg['tags'])
            yield info

def parse_list_export(list_file):
    """Parse newline-separated list of links into links"""
    list_file.seek(0)
    for l in list_file:
        href = l.rstrip("\n")
        info = basic_link_info(href, list_file)
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

        info = basic_link_info(url, rss_file, title, time)

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
            info = basic_link_info(url, html_file, match.group(3), time)

            yield info
