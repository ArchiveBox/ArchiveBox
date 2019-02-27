# coding: utf-8

"""
Everything related to parsing links from bookmark services.

For a list of supported services, see the README.md.
For examples of supported files see examples/.

Parsed link schema: {
    'url': 'https://example.com/example/?abc=123&xyc=345#lmnop',
    'timestamp': '15442123124234',
    'title': 'Example.com Page Title',
    'tags': 'abc,def',
    'sources': ['ril_export.html', 'downloads/getpocket.com.txt'],
}
"""

import re
import json

from datetime import datetime
from collections import OrderedDict
import xml.etree.ElementTree as etree

from config import ANSI
from util import (
    str_between,
    get_link_type,
    URL_REGEX,
    check_url_parsing,
)


def parse_links(path):
    """parse a list of links dictionaries from a bookmark export file"""
    
    check_url_parsing()

    links = []
    with open(path, 'r', encoding='utf-8') as file:
        print('{green}[*] [{}] Parsing new links from output/sources/{}...{reset}'.format(
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            path.rsplit('/', 1)[-1],
            **ANSI,
        ))

        for parser_name, parser_func in PARSERS.items():
            try:
                links += list(parser_func(file))
                if links:
                    break
            except Exception as err:
                # we try each parser one by one, wong parsers will throw exeptions
                # if unsupported and we accept the first one that passes
                # uncomment the following line to see why the parser was unsupported for each attempted format
                # print('[!] Parser {} failed: {} {}'.format(parser_name, err.__class__.__name__, err))
                pass

    return links, parser_name


def parse_pocket_html_export(html_file):
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
                'timestamp': str(time.timestamp()),
                'tags': match.group(3),
                'title': match.group(4).replace(' — Readability', '').replace('http://www.readability.com/read?url=', '') or None,
                'sources': [html_file.name],
            }
            info['type'] = get_link_type(info)
            yield info

def parse_pinboard_json_export(json_file):
    """Parse JSON-format bookmarks export files (produced by pinboard.in/export/, or wallabag)"""
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
            elif erg.get('created_at'):
                timestamp = str(datetime.strptime(erg['created_at'], '%Y-%m-%dT%H:%M:%S%z').timestamp())
            else:
                timestamp = str(datetime.now().timestamp())
            if erg.get('href'):
                url = erg['href']
            else:
                url = erg['url']
            if erg.get('description'):
                title = (erg.get('description') or '').replace(' — Readability', '')
            else:
                title = erg['title'].strip()
            info = {
                'url': url,
                'timestamp': timestamp,
                'tags': erg.get('tags') or '',
                'title': title or None,
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
            return [r for r in rows if r.strip().startswith('<{}>'.format(key))][0]

        title = str_between(get_row('title'), '<![CDATA[', ']]').strip()
        url = str_between(get_row('link'), '<link>', '</link>')
        ts_str = str_between(get_row('pubDate'), '<pubDate>', '</pubDate>')
        time = datetime.strptime(ts_str, "%a, %d %b %Y %H:%M:%S %z")

        info = {
            'url': url,
            'timestamp': str(time.timestamp()),
            'tags': '',
            'title': title or None,
            'sources': [rss_file.name],
        }
        info['type'] = get_link_type(info)

        yield info


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

        info = {
            'url': url,
            'timestamp': str(time.timestamp()),
            'tags': '',
            'title': title or None,
            'sources': [rss_file.name],
        }
        info['type'] = get_link_type(info)

        yield info

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

            info = {
                'url': url,
                'timestamp': str(time.timestamp()),
                'tags': "",
                'title': match.group(3).strip() or None,
                'sources': [html_file.name],
            }
            info['type'] = get_link_type(info)

            yield info

def parse_pinboard_rss_export(rss_file):
    """Parse Pinboard RSS feed files into links"""

    rss_file.seek(0)
    root = etree.parse(rss_file).getroot()
    items = root.findall("{http://purl.org/rss/1.0/}item")
    for item in items:
        url = item.find("{http://purl.org/rss/1.0/}link").text
        tags = item.find("{http://purl.org/dc/elements/1.1/}subject").text
        title = item.find("{http://purl.org/rss/1.0/}title").text.strip()
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
            'timestamp': str(time.timestamp()),
            'tags': tags,
            'title': title or None,
            'sources': [rss_file.name],
        }
        info['type'] = get_link_type(info)
        yield info

def parse_medium_rss_export(rss_file):
    """Parse Medium RSS feed files into links"""

    rss_file.seek(0)
    root = etree.parse(rss_file).getroot()
    items = root.find("channel").findall("item")
    for item in items:
        # for child in item:
        #     print(child.tag, child.text)
        url = item.find("link").text
        title = item.find("title").text.strip()
        ts_str = item.find("pubDate").text
        time = datetime.strptime(ts_str, "%a, %d %b %Y %H:%M:%S %Z")
        info = {
            'url': url,
            'timestamp': str(time.timestamp()),
            'tags': '',
            'title': title or None,
            'sources': [rss_file.name],
        }
        info['type'] = get_link_type(info)
        yield info


def parse_plain_text_export(text_file):
    """Parse raw links from each line in a text file"""

    text_file.seek(0)
    text_content = text_file.readlines()
    for line in text_content:
        if line:
            urls = re.findall(URL_REGEX, line)
            
            for url in urls:
                url = url.strip()
                info = {
                    'url': url,
                    'timestamp': str(datetime.now().timestamp()),
                    'tags': '',
                    'title': None,
                    'sources': [text_file.name],
                }
                info['type'] = get_link_type(info)
                yield info


PARSERS = OrderedDict([
    ('Pocket HTML', parse_pocket_html_export),
    ('Pinboard JSON', parse_pinboard_json_export),
    ('Netscape HTML', parse_netscape_html_export),
    ('RSS', parse_rss_export),
    ('Pinboard RSS', parse_pinboard_rss_export),
    ('Shaarli RSS', parse_shaarli_rss_export),
    ('Medium RSS', parse_medium_rss_export),
    ('Plain Text', parse_plain_text_export),
])
