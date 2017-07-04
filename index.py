import os
from datetime import datetime

from config import INDEX_TEMPLATE, INDEX_ROW_TEMPLATE
from parse import derived_link_info


def dump_index(links, service):
    """create index.html file for a given list of links and service"""

    with open(INDEX_TEMPLATE, 'r') as f:
        index_html = f.read()

    # TODO: refactor this out into index_template.html
    with open(INDEX_ROW_TEMPLATE, 'r') as f:
        link_html = f.read()

    article_rows = '\n'.join(
        link_html.format(**derived_link_info(link)) for link in links
    )

    template_vars = (datetime.now().strftime('%Y-%m-%d %H:%M'), article_rows)

    with open(os.path.join(service, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_html.format(*template_vars))
