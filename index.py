import os
from datetime import datetime
from string import Template

from parse import derived_link_info
from config import (
    INDEX_TEMPLATE,
    INDEX_ROW_TEMPLATE,
    ARCHIVE_PERMISSIONS,
    ANSI,
    chmod_file,
)


def dump_index(links, service):
    """create index.html file for a given list of links and service"""

    with open(INDEX_TEMPLATE, 'r', encoding='utf-8') as f:
        index_html = f.read()

    # TODO: refactor this out into index_template.html
    with open(INDEX_ROW_TEMPLATE, 'r', encoding='utf-8') as f:
        link_html = f.read()

    article_rows = '\n'.join(
        Template(link_html).substitute(**derived_link_info(link)) for link in links
    )

    template_vars = {
        'num_links': len(links),
        'date_updated': datetime.now().strftime('%Y-%m-%d'),
        'time_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'rows': article_rows,
    }

    with open(os.path.join(service, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(Template(index_html).substitute(**template_vars))

    chmod_file(service, permissions=ARCHIVE_PERMISSIONS)

    print('[+] [{}] Created archive index with {}{}{} links.'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        ANSI['green'],
        len(links),
        ANSI['reset'],
    ))
