"""
Everything related to parsing links from input sources.

For a list of supported services, see the README.md.
For examples of supported import formats see tests/.

Link: {
    'url': 'https://example.com/example/?abc=123&xyc=345#lmnop',
    'timestamp': '1544212312.4234',
    'title': 'Example.com Page Title',
    'tags': 'abc,def',
    'sources': [
        'output/sources/ril_export.html',
        'output/sources/getpocket.com-1523422111.txt',
        'output/sources/stdin-234234112312.txt'
    ]
}
"""

import re
import json

from datetime import datetime
import xml.etree.ElementTree as etree

from config import TIMEOUT
from util import (
    str_between,
    URL_REGEX,
    check_url_parsing_invariants,
    TimedProgress,
)


def parse_links(source_file):
    """parse a list of URLs with their metadata from an 
       RSS feed, bookmarks export, or text file
    """

    check_url_parsing_invariants()
    PARSERS = (
        # Specialized parsers
        ('Pocket HTML', parse_pocket_html_export),
        ('Pinboard RSS', parse_pinboard_rss_export),
        ('Shaarli RSS', parse_shaarli_rss_export),
        ('Medium RSS', parse_medium_rss_export),
        
        # General parsers
        ('Netscape HTML', parse_netscape_html_export),
        ('Generic RSS', parse_rss_export),
        ('Generic JSON', parse_json_export),

        # Fallback parser
        ('Plain Text', parse_plain_text_export),
    )
    timer = TimedProgress(TIMEOUT * 4)
    with open(source_file, 'r', encoding='utf-8') as file:
        for parser_name, parser_func in PARSERS:
            try:
                links = list(parser_func(file))
                if links:
                    timer.end()
                    return links, parser_name
            except Exception as err:
                # Parsers are tried one by one down the list, and the first one
                # that succeeds is used. To see why a certain parser was not used
                # due to error or format incompatibility, uncomment this line:
                # print('[!] Parser {} failed: {} {}'.format(parser_name, err.__class__.__name__, err))
                pass

    timer.end()
    return [], 'Failed to parse'


### Import Parser Functions

def parse_pocket_html_export(html_file):
    """Parse Pocket-format bookmarks export files (produced by getpocket.com/export/)"""

    html_file.seek(0)
    pattern = re.compile("^\\s*<li><a href=\"(.+)\" time_added=\"(\\d+)\" tags=\"(.*)\">(.+)</a></li>", re.UNICODE)
    for line in html_file:
        # example line
        # <li><a href="http://example.com/ time_added="1478739709" tags="tag1,tag2">example title</a></li>
        match = pattern.search(line)
        if match:
            url = match.group(1).replace('http://www.readability.com/read?url=', '')           # remove old readability prefixes to get original url
            time = datetime.fromtimestamp(float(match.group(2)))
            tags = match.group(3)
            title = match.group(4).replace(' — Readability', '').replace('http://www.readability.com/read?url=', '')
            
            yield {
                'url': url,
                'timestamp': str(time.timestamp()),
                'title': title or None,
                'tags': tags or '',
                'sources': [html_file.name],
            }


def parse_json_export(json_file):
    """Parse JSON-format bookmarks export files (produced by pinboard.in/export/, or wallabag)"""

    json_file.seek(0)
    links = json.load(json_file)
    json_date = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%S%z')

    for link in links:
        # example line
        # {"href":"http:\/\/www.reddit.com\/r\/example","description":"title here","extended":"","meta":"18a973f09c9cc0608c116967b64e0419","hash":"910293f019c2f4bb1a749fb937ba58e3","time":"2014-06-14T15:51:42Z","shared":"no","toread":"no","tags":"reddit android"}]
        if link:
            # Parse URL
            url = link.get('href') or link.get('url') or link.get('URL')
            if not url:
                raise Exception('JSON must contain URL in each entry [{"url": "http://...", ...}, ...]')

            # Parse the timestamp
            ts_str = str(datetime.now().timestamp())
            if link.get('timestamp'):
                # chrome/ff histories use a very precise timestamp
                ts_str = str(link['timestamp'] / 10000000)  
            elif link.get('time'):
                ts_str = str(json_date(link['time'].split(',', 1)[0]).timestamp())
            elif link.get('created_at'):
                ts_str = str(json_date(link['created_at']).timestamp())
            elif link.get('created'):
                ts_str = str(json_date(link['created']).timestamp())
            elif link.get('date'):
                ts_str = str(json_date(link['date']).timestamp())
            elif link.get('bookmarked'):
                ts_str = str(json_date(link['bookmarked']).timestamp())
            elif link.get('saved'):
                ts_str = str(json_date(link['saved']).timestamp())
            
            # Parse the title
            title = None
            if link.get('title'):
                title = link['title'].strip() or None
            elif link.get('description'):
                title = link['description'].replace(' — Readability', '').strip() or None
            elif link.get('name'):
                title = link['name'].strip() or None

            yield {
                'url': url,
                'timestamp': ts_str,
                'title': title,
                'tags': link.get('tags') or '',
                'sources': [json_file.name],
            }


def parse_rss_export(rss_file):
    """Parse RSS XML-format files into links"""

    rss_file.seek(0)
    items = rss_file.read().split('<item>')
    items = items[1:] if items else []
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
        leading_removed = trailing_removed.split('<item>', 1)[-1].strip()
        rows = leading_removed.split('\n')

        def get_row(key):
            return [r for r in rows if r.strip().startswith('<{}>'.format(key))][0]

        url = str_between(get_row('link'), '<link>', '</link>')
        ts_str = str_between(get_row('pubDate'), '<pubDate>', '</pubDate>')
        time = datetime.strptime(ts_str, "%a, %d %b %Y %H:%M:%S %z")
        title = str_between(get_row('title'), '<![CDATA[', ']]').strip() or None

        yield {
            'url': url,
            'timestamp': str(time.timestamp()),
            'title': title,
            'tags': '',
            'sources': [rss_file.name],
        }


def parse_shaarli_rss_export(rss_file):
    """Parse Shaarli-specific RSS XML-format files into links"""

    rss_file.seek(0)
    entries = rss_file.read().split('<entry>')[1:]
    for entry in entries:
        # example entry:
        # <entry>
        #   <title>Aktuelle Trojaner-Welle: Emotet lauert in gefÃ¤lschten Rechnungsmails | heise online</title>
        #   <link href="https://www.heise.de/security/meldung/Aktuelle-Trojaner-Welle-Emotet-lauert-in-gefaelschten-Rechnungsmails-4291268.html" />
        #   <id>https://demo.shaarli.org/?cEV4vw</id>
        #   <published>2019-01-30T06:06:01+00:00</published>
        #   <updated>2019-01-30T06:06:01+00:00</updated>
        #   <content type="html" xml:lang="en"><![CDATA[<div class="markdown"><p>&#8212; <a href="https://demo.shaarli.org/?cEV4vw">Permalink</a></p></div>]]></content>
        # </entry>

        trailing_removed = entry.split('</entry>', 1)[0]
        leading_removed = trailing_removed.strip()
        rows = leading_removed.split('\n')

        def get_row(key):
            return [r.strip() for r in rows if r.strip().startswith('<{}'.format(key))][0]

        title = str_between(get_row('title'), '<title>', '</title>').strip()
        url = str_between(get_row('link'), '<link href="', '" />')
        ts_str = str_between(get_row('published'), '<published>', '</published>')
        time = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")

        yield {
            'url': url,
            'timestamp': str(time.timestamp()),
            'title': title or None,
            'tags': '',
            'sources': [rss_file.name],
        }


def parse_netscape_html_export(html_file):
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

            yield {
                'url': url,
                'timestamp': str(time.timestamp()),
                'title': match.group(3).strip() or None,
                'tags': '',
                'sources': [html_file.name],
            }


def parse_pinboard_rss_export(rss_file):
    """Parse Pinboard RSS feed files into links"""

    rss_file.seek(0)
    root = etree.parse(rss_file).getroot()
    items = root.findall("{http://purl.org/rss/1.0/}item")
    for item in items:
        url = item.find("{http://purl.org/rss/1.0/}link").text
        tags = item.find("{http://purl.org/dc/elements/1.1/}subject").text if item.find("{http://purl.org/dc/elements/1.1/}subject") else None
        title = item.find("{http://purl.org/rss/1.0/}title").text.strip() if item.find("{http://purl.org/rss/1.0/}title").text.strip() else None
        ts_str = item.find("{http://purl.org/dc/elements/1.1/}date").text if item.find("{http://purl.org/dc/elements/1.1/}date").text else None
        
        # Pinboard includes a colon in its date stamp timezone offsets, which
        # Python can't parse. Remove it:
        if ts_str and ts_str[-3:-2] == ":":
            ts_str = ts_str[:-3]+ts_str[-2:]

        if ts_str:
            time = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")
        else:
            time = datetime.now()

        yield {
            'url': url,
            'timestamp': str(time.timestamp()),
            'title': title or None,
            'tags': tags or '',
            'sources': [rss_file.name],
        }


def parse_medium_rss_export(rss_file):
    """Parse Medium RSS feed files into links"""

    rss_file.seek(0)
    root = etree.parse(rss_file).getroot()
    items = root.find("channel").findall("item")
    for item in items:
        url = item.find("link").text
        title = item.find("title").text.strip()
        ts_str = item.find("pubDate").text
        time = datetime.strptime(ts_str, "%a, %d %b %Y %H:%M:%S %Z")
        
        yield {
            'url': url,
            'timestamp': str(time.timestamp()),
            'title': title or None,
            'tags': '',
            'sources': [rss_file.name],
        }


def parse_plain_text_export(text_file):
    """Parse raw links from each line in a text file"""

    text_file.seek(0)
    for line in text_file.readlines():
        urls = re.findall(URL_REGEX, line) if line.strip() else ()
        for url in urls:
            yield {
                'url': url,
                'timestamp': str(datetime.now().timestamp()),
                'title': None,
                'tags': '',
                'sources': [text_file.name],
            }
