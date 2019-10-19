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
    GIT_SHA,
    FOOTER_INFO,
)
from util import (
    chmod_file,
    urlencode,
    derived_link_info,
    check_link_structure,
    check_links_structure,
    wget_output_path,
    latest_output,
)
from parse import parse_links
from links import validate_links
from logs import (
    log_indexing_process_started,
    log_indexing_started,
    log_indexing_finished,
    log_parsing_started,
    log_parsing_finished,
)

TITLE_LOADING_MSG = 'Not yet archived...'


### Homepage index for all the links

def write_links_index(out_dir, links, finished=False):
    """create index.html file for a given list of links"""

    log_indexing_process_started()
    check_links_structure(links)

    log_indexing_started(out_dir, 'index.json')
    write_json_links_index(out_dir, links)
    log_indexing_finished(out_dir, 'index.json')
    
    log_indexing_started(out_dir, 'index.html')
    write_html_links_index(out_dir, links, finished=finished)
    log_indexing_finished(out_dir, 'index.html')
    
def load_links_index(out_dir=OUTPUT_DIR, import_path=None):
    """parse and load existing index with any new links from import_path merged in"""

    existing_links = []
    if out_dir:
        existing_links = parse_json_links_index(out_dir)
        check_links_structure(existing_links)

    new_links = []
    if import_path:
        # parse and validate the import file
        log_parsing_started(import_path)
        raw_links, parser_name = parse_links(import_path)
        new_links = validate_links(raw_links)
        check_links_structure(new_links)

    # merge existing links in out_dir and new links
    all_links = validate_links(existing_links + new_links)
    check_links_structure(all_links)
    num_new_links = len(all_links) - len(existing_links)

    if import_path and parser_name:
        log_parsing_finished(num_new_links, parser_name)

    return all_links, new_links

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

def parse_json_links_index(out_dir=OUTPUT_DIR):
    """parse a archive index json file and return the list of links"""
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
            'archive_url': urlencode(
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


def patch_links_index(link, out_dir=OUTPUT_DIR):
    """hack to in-place update one row's info in the generated index html"""

    title = link['title'] or latest_output(link)['title']
    successful = len(tuple(filter(None, latest_output(link).values())))

    # Patch JSON index
    changed = False
    json_file_links = parse_json_links_index(out_dir)
    for saved_link in json_file_links:
        if saved_link['url'] == link['url']:
            saved_link['title'] = title
            saved_link['history'] = link['history']
            changed = True
            break
    if changed:
        write_json_links_index(out_dir, json_file_links)

    # Patch HTML index
    html_path = os.path.join(out_dir, 'index.html')
    with open(html_path, 'r') as html_file:
        html = html_file.read().splitlines()
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

def load_json_link_index(out_dir, link):
    """check for an existing link archive in the given directory, 
       and load+merge it into the given link dict
    """
    link = {
        **parse_json_link_index(out_dir),
        **link,
    }
    link.update({
        'history': link.get('history') or {},
    })

    check_link_structure(link)
    return link

def write_html_link_index(out_dir, link):
    check_link_structure(link)
    with open(os.path.join(TEMPLATES_DIR, 'link_index.html'), 'r', encoding='utf-8') as f:
        link_html = f.read()

    path = os.path.join(out_dir, 'index.html')

    link = derived_link_info(link)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(Template(link_html).substitute({
            **link,
            'title': (
                link['title']
                or (link['base_url'] if link['is_archived'] else TITLE_LOADING_MSG)
            ),
            'archive_url': urlencode(
                wget_output_path(link)
                or (link['domain'] if link['is_archived'] else 'about:blank')
            ),
            'extension': link['extension'] or 'html',
            'tags': link['tags'].strip() or 'untagged',
            'status': 'Archived' if link['is_archived'] else 'Not yet archived',
            'status_color': 'success' if link['is_archived'] else 'danger',
        }))

    chmod_file(path)
