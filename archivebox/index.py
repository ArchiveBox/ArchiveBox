import os
import json

from datetime import datetime
from string import Template
try:
    from distutils.dir_util import copy_tree
except ImportError:
    print('[X] Missing "distutils" python package. To install it, run:')
    print('    pip install distutils')

from config import (
    OUTPUT_DIR,
    TEMPLATES_DIR,
    ANSI,
    GIT_SHA,
    FOOTER_INFO,
)
from util import (
    chmod_file,
    derived_link_info,
    pretty_path,
    check_link_structure,
    check_links_structure,
    wget_output_path,
)

TITLE_LOADING_MSG = 'Not yet archived...'


### Homepage index for all the links

def write_links_index(out_dir, links, finished=False):
    """create index.html file for a given list of links"""

    check_links_structure(links)

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    print('{green}[*] [{}] Saving main index files...{reset}'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        **ANSI,
    ))
    write_json_links_index(out_dir, links)
    print('    > {}/index.json'.format(pretty_path(out_dir)))
    
    write_html_links_index(out_dir, links, finished=finished)
    print('    > {}/index.html'.format(pretty_path(out_dir)))
    

def write_json_links_index(out_dir, links):
    """write the json link index to a given path"""

    check_links_structure(links)

    path = os.path.join(out_dir, 'index.json')

    index_json = {
        'info': 'ArchiveBox Index',
        'help': 'https://github.com/pirate/ArchiveBox',
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
            links = json.load(f)['links']
            check_links_structure(links)
            return links

    return []

def write_html_links_index(out_dir, links, finished=False):
    """write the html link index to a given path"""

    check_links_structure(links)

    path = os.path.join(out_dir, 'index.html')

    copy_tree(os.path.join(TEMPLATES_DIR, 'static'), os.path.join(out_dir, 'static'))

    with open(os.path.join(out_dir, 'robots.txt'), 'w+') as f:
        f.write('User-agent: *\nDisallow: /')

    with open(os.path.join(TEMPLATES_DIR, 'index.html'), 'r', encoding='utf-8') as f:
        index_html = f.read()

    with open(os.path.join(TEMPLATES_DIR, 'index_row.html'), 'r', encoding='utf-8') as f:
        link_row_html = f.read()

    full_links_info = (derived_link_info(link) for link in links)

    link_rows = '\n'.join(
        Template(link_row_html).substitute(**{
            **link,
            'title': (
                link['title']
                or (link['base_url'] if link['is_archived'] else TITLE_LOADING_MSG)
            ),
            'favicon_url': (
                os.path.join('archive', link['timestamp'], 'favicon.ico')
                # if link['is_archived'] else 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs='
            ),
            'archive_url': (
                wget_output_path(link) or 'index.html'
            ),
        })
        for link in full_links_info
    )

    template_vars = {
        'num_links': len(links),
        'date_updated': datetime.now().strftime('%Y-%m-%d'),
        'time_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'footer_info': FOOTER_INFO,
        'git_sha': GIT_SHA,
        'short_git_sha': GIT_SHA[:8],
        'rows': link_rows,
        'status': 'finished' if finished else 'running',
    }

    with open(path, 'w', encoding='utf-8') as f:
        f.write(Template(index_html).substitute(**template_vars))

    chmod_file(path)


def update_main_index(link):
    """hack to in-place update one row's info in the generated index html"""

    title = link['latest']['title']
    successful = len([entry for entry in link['latest'].values() if entry])

    # Patch JSON index
    json_path = os.path.join(OUTPUT_DIR, 'index.json')

    links = parse_json_links_index(OUTPUT_DIR)

    changed = False
    for json_link in links:
        if json_link['url'] == link['url']:
            json_link['title'] = title
            json_link['latest'] = link['latest']
            changed = True
            break

    if changed:
        write_json_links_index(OUTPUT_DIR, links)

    # Patch HTML index
    html_path = os.path.join(OUTPUT_DIR, 'index.html')

    html = open(html_path, 'r').read().split('\n')
    for idx, line in enumerate(html):
        if title and ('<span data-title-for="{}"'.format(link['url']) in line):
            html[idx] = '<span>{}</span>'.format(title)
        elif successful and ('<span data-number-for="{}"'.format(link['url']) in line):
            html[idx] = '<span>{}</span>'.format(successful)
            break

    with open(html_path, 'w') as f:
        f.write('\n'.join(html))

### Individual link index

def write_link_index(out_dir, link):
    link['updated'] = str(datetime.now().timestamp())
    write_json_link_index(out_dir, link)
    write_html_link_index(out_dir, link)

def write_json_link_index(out_dir, link):
    """write a json file with some info about the link"""
    
    check_link_structure(link)
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
            link_json = json.load(f)
            check_link_structure(link_json)
            return link_json
    return {}

def write_html_link_index(out_dir, link):
    check_link_structure(link)
    with open(os.path.join(TEMPLATES_DIR, 'link_index.html'), 'r', encoding='utf-8') as f:
        link_html = f.read()

    path = os.path.join(out_dir, 'index.html')

    print('      √ index.html')

    link = derived_link_info(link)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(Template(link_html).substitute({
            **link,
            'title': (
                link['title']
                or (link['base_url'] if link['is_archived'] else TITLE_LOADING_MSG)
            ),
            'archive_url': (
                wget_output_path(link)
                or (link['domain'] if link['is_archived'] else 'about:blank')
            ),
            'extension': link['extension'] or 'HTML',
        }))

    chmod_file(path)
