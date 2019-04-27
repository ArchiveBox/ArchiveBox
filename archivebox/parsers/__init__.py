"""
Everything related to parsing links from input sources.

For a list of supported services, see the README.md.
For examples of supported import formats see tests/.
"""

__package__ = 'archivebox.parsers'


from typing import Tuple, List

from ..config import TIMEOUT
from ..util import (
    check_url_parsing_invariants,
    TimedProgress,
    Link,
    enforce_types,
)
from .pocket_html import parse_pocket_html_export
from .pinboard_rss import parse_pinboard_rss_export
from .shaarli_rss import parse_shaarli_rss_export
from .medium_rss import parse_medium_rss_export
from .netscape_html import parse_netscape_html_export
from .generic_rss import parse_generic_rss_export
from .generic_json import parse_generic_json_export
from .generic_txt import parse_generic_txt_export


@enforce_types
def parse_links(source_file: str) -> Tuple[List[Link], str]:
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
        ('Generic RSS', parse_generic_rss_export),
        ('Generic JSON', parse_generic_json_export),

        # Fallback parser
        ('Plain Text', parse_generic_txt_export),
    )
    timer = TimedProgress(TIMEOUT * 4)
    with open(source_file, 'r', encoding='utf-8') as file:
        for parser_name, parser_func in PARSERS:
            try:
                links = list(parser_func(file))
                if links:
                    timer.end()
                    return links, parser_name
            except Exception as err:   # noqa
                # Parsers are tried one by one down the list, and the first one
                # that succeeds is used. To see why a certain parser was not used
                # due to error or format incompatibility, uncomment this line:
                # print('[!] Parser {} failed: {} {}'.format(parser_name, err.__class__.__name__, err))
                pass

    timer.end()
    return [], 'Failed to parse'
