import os
import json

from datetime import datetime
from string import Template
from distutils.dir_util import copy_tree

from config import (
    TEMPLATES_DIR,
    OUTPUT_PERMISSIONS,
    ANSI,
    GIT_SHA,
    FOOTER_INFO,
)
from util import (
    chmod_file,
    wget_output_path,
    derived_link_info,
    pretty_path,
)


### Homepage index for all the links

def write_links_index(out_dir, links):
    """create index.html file for a given list of links"""

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    write_json_links_index(out_dir, links)
    write_html_links_index(out_dir, links)
    
    print('{green}[√] [{}] Updated main index files:{reset}'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        **ANSI))
    print('    > {}/index.json'.format(pretty_path(out_dir)))
    print('    > {}/index.html'.format(pretty_path(out_dir)))

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

def parse_json_links_index(out_dir):
    """load the index in a given directory and merge it with the given link"""
    index_path = os.path.join(out_dir, 'index.json')
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            return json.load(f)['links']

    return []

def write_html_links_index(out_dir, links):
    """write the html link index to a given path"""

    path = os.path.join(out_dir, 'index.html')

    copy_tree(os.path.join(TEMPLATES_DIR, 'static'), os.path.join(out_dir, 'static'))

    with open(os.path.join(out_dir, 'robots.txt'), 'w+') as f:
        f.write('User-agent: *\nDisallow: /')

    with open(os.path.join(TEMPLATES_DIR, 'index.html'), 'r', encoding='utf-8') as f:
        index_html = f.read()

    with open(os.path.join(TEMPLATES_DIR, 'index_row.html'), 'r', encoding='utf-8') as f:
        link_row_html = f.read()

    link_rows = '\n'.join(
        Template(link_row_html).substitute(**derived_link_info(link))
        for link in links
    )

    template_vars = {
        'num_links': len(links),
        'date_updated': datetime.now().strftime('%Y-%m-%d'),
        'time_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'footer_info': FOOTER_INFO,
        'git_sha': GIT_SHA,
        'short_git_sha': GIT_SHA[:8],
        'rows': link_rows,
    }

    with open(path, 'w', encoding='utf-8') as f:
        f.write(Template(index_html).substitute(**template_vars))

    chmod_file(path)


### Individual link index

def write_link_index(out_dir, link):
    link['updated'] = str(datetime.now().timestamp())
    write_json_link_index(out_dir, link)
    write_html_link_index(out_dir, link)

def write_json_link_index(out_dir, link):
    """write a json file with some info about the link"""
    
    path = os.path.join(out_dir, 'index.json')

    print('      √ index.json')

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(link, f, indent=4, default=str)

    chmod_file(path)

def parse_json_link_index(out_dir):
    """load the json link index from a given directory"""
    existing_index = os.path.join(out_dir, 'index.json')
    if os.path.exists(existing_index):
        with open(existing_index, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def write_html_link_index(out_dir, link):
    with open(os.path.join(TEMPLATES_DIR, 'link_index_fancy.html'), 'r', encoding='utf-8') as f:
        link_html = f.read()

    path = os.path.join(out_dir, 'index.html')

    print('      √ index.html')

    with open(path, 'w', encoding='utf-8') as f:
        f.write(Template(link_html).substitute({
            **link,
            **link['latest'],
            'type': link['type'] or 'website',
            'tags': link['tags'] or 'untagged',
            'bookmarked': datetime.fromtimestamp(float(link['timestamp'])).strftime('%Y-%m-%d %H:%M'),
            'updated': datetime.fromtimestamp(float(link['updated'])).strftime('%Y-%m-%d %H:%M'),
            'bookmarked_ts': link['timestamp'],
            'updated_ts': link['updated'],
            'archive_org': link['latest'].get('archive_org') or 'https://web.archive.org/save/{}'.format(link['url']),
            'wget': link['latest'].get('wget') or wget_output_path(link),
        }))

    chmod_file(path)
