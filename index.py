import os
import re
import json

from datetime import datetime
from string import Template

from config import (
    INDEX_TEMPLATE,
    INDEX_ROW_TEMPLATE,
    LINK_INDEX_TEMPLATE,
    ARCHIVE_PERMISSIONS,
    ARCHIVE_DIR,
    ANSI,
    GIT_SHA,
)
from util import chmod_file


### Homepage index for all the links

def parse_json_links_index(out_dir):
    """load the index in a given directory and merge it with the given link"""
    index_path = os.path.join(out_dir, 'index.json')
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            return json.load(f)['links']

    return []

def write_links_index(out_dir, links):
    """create index.html file for a given list of links"""

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    print('[i] [{}] Updating {}{}{} links in archive index...'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        ANSI['green'],
        len(links),
        ANSI['reset'],
    ))
    
    write_json_links_index(out_dir, links)
    write_html_links_index(out_dir, links)

    chmod_file(out_dir, permissions=ARCHIVE_PERMISSIONS)

def write_json_links_index(out_dir, links):
    """write the json link index to a given path"""

    path = os.path.join(out_dir, 'index.json')

    index_json = {
        'info': 'Bookmark Archiver Index',
        'help': 'https://github.com/pirate/bookmark-archiver',
        'version': GIT_SHA,
        'num_links': len(links),
        'updated': str(datetime.now().timestamp()),
        'links': links,
    }

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(index_json, f, indent=4, default=str)

    chmod_file(path)

def write_html_links_index(out_dir, links):
    """write the html link index to a given path"""

    path = os.path.join(out_dir, 'index.html')

    with open(INDEX_TEMPLATE, 'r', encoding='utf-8') as f:
        index_html = f.read()

    with open(INDEX_ROW_TEMPLATE, 'r', encoding='utf-8') as f:
        link_row_html = f.read()

    link_rows = '\n'.join(
        Template(link_row_html).substitute(**derived_link_info(link))
        for link in links
    )

    template_vars = {
        'num_links': len(links),
        'date_updated': datetime.now().strftime('%Y-%m-%d'),
        'time_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'rows': link_rows,
    }

    with open(path, 'w', encoding='utf-8') as f:
        f.write(Template(index_html).substitute(**template_vars))


### Individual link index

def parse_json_link_index(out_dir):
    """load the index in a given directory and merge it with the given link"""
    existing_index = os.path.join(out_dir, 'index.json')
    if os.path.exists(existing_index):
        with open(existing_index, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def write_link_index(out_dir, link):
    link['updated'] = str(datetime.now().timestamp())
    write_json_link_index(out_dir, link)
    write_html_link_index(out_dir, link)

def write_json_link_index(out_dir, link):
    """write a json file with some info about the link"""
    
    path = os.path.join(out_dir, 'index.json')

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(link, f, indent=4, default=str)

    chmod_file(path)

def write_html_link_index(out_dir, link):
    with open(LINK_INDEX_TEMPLATE, 'r', encoding='utf-8') as f:
        link_html = f.read()

    path = os.path.join(out_dir, 'index.html')

    with open(path, 'w', encoding='utf-8') as f:
        f.write(Template(link_html).substitute({
            **link,
            **link['methods'],
            'type': link['type'] or 'website',
            'tags': link['tags'] or '',
            'bookmarked': datetime.fromtimestamp(float(link['timestamp'])).strftime('%Y-%m-%d %H:%M'),
            'updated': datetime.fromtimestamp(float(link['updated'])).strftime('%Y-%m-%d %H:%M'),
            'archive_org': link['methods']['archive_org'] or 'https://web.archive.org/save/{}'.format(link['url']),
            'wget': link['methods']['wget'] or link['domain'],
        }))

    chmod_file(path)



def html_appended_url(link):
    """calculate the path to the wgetted .html file, since wget may
    adjust some paths to be different than the base_url path.

    See docs on wget --adjust-extension."""

    if link['type'] in ('PDF', 'image'):
        return link['base_url']

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
                return '#'.join([without_scheme + '/index.html' + query + '.html', *split_url[1:]])
            elif '/' in without_scheme:
                return '#'.join([without_scheme + '.html', *split_url[1:]])
            return link['base_url'] + '/index.html'


def derived_link_info(link):
    """extend link info with the archive urls and other derived data"""

    link_info = {
        **link,
        'date': datetime.fromtimestamp(float(link['timestamp'])).strftime('%Y-%m-%d %H:%M'),
        'google_favicon_url': 'https://www.google.com/s2/favicons?domain={domain}'.format(**link),
        'favicon_url': 'archive/{timestamp}/favicon.ico'.format(**link),
        'files_url': 'archive/{timestamp}/'.format(**link),
        'archive_url': 'archive/{}/{}'.format(link['timestamp'], html_appended_url(link)),
        'pdf_link': 'archive/{timestamp}/output.pdf'.format(**link),
        'screenshot_link': 'archive/{timestamp}/screenshot.png'.format(**link),
        'archive_org_url': 'https://web.archive.org/web/{base_url}'.format(**link),
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
    return link_info
