"""
Everything related to parsing links from input sources.

For a list of supported services, see the README.md.
For examples of supported import formats see tests/.
"""

__package__ = 'archivebox.parsers'

import re
import os
from io import StringIO

from typing import IO, Tuple, List
from datetime import datetime

from ..system import atomic_write
from ..config import (
    ANSI,
    OUTPUT_DIR,
    SOURCES_DIR_NAME,
    TIMEOUT,
)
from ..util import (
    basename,
    download_url,
    enforce_types,
    URL_REGEX,
)
from ..index.schema import Link
from ..logging_util import TimedProgress, log_source_saved
from .pocket_html import parse_pocket_html_export
from .pinboard_rss import parse_pinboard_rss_export
from .shaarli_rss import parse_shaarli_rss_export
from .medium_rss import parse_medium_rss_export
from .netscape_html import parse_netscape_html_export
from .generic_rss import parse_generic_rss_export
from .generic_json import parse_generic_json_export
from .generic_txt import parse_generic_txt_export

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

@enforce_types
def parse_links_memory(urls: List[str]):
    """
    parse a list of URLS without touching the filesystem
    """
    check_url_parsing_invariants()

    timer = TimedProgress(TIMEOUT * 4)
    #urls = list(map(lambda x: x + "\n", urls))
    file = StringIO()
    file.writelines(urls)
    file.name = "io_string"
    output = _parse(file, timer)

    if output is not None:
        return output

    timer.end()
    return [], 'Failed to parse'
    

@enforce_types
def parse_links(source_file: str) -> Tuple[List[Link], str]:
    """parse a list of URLs with their metadata from an 
       RSS feed, bookmarks export, or text file
    """

    check_url_parsing_invariants()

    timer = TimedProgress(TIMEOUT * 4)
    with open(source_file, 'r', encoding='utf-8') as file:
        output = _parse(file, timer)

    if output is not None:
        return output

    timer.end()
    return [], 'Failed to parse'

def _parse(to_parse: IO[str], timer) -> Tuple[List[Link], str]:
    for parser_name, parser_func in PARSERS:
        try:
            links = list(parser_func(to_parse))
            if links:
                timer.end()
                return links, parser_name
        except Exception as err:   # noqa
            pass
            # Parsers are tried one by one down the list, and the first one
            # that succeeds is used. To see why a certain parser was not used
            # due to error or format incompatibility, uncomment this line:
            # print('[!] Parser {} failed: {} {}'.format(parser_name, err.__class__.__name__, err))
            # raise


@enforce_types
def save_text_as_source(raw_text: str, filename: str='{ts}-stdin.txt', out_dir: str=OUTPUT_DIR) -> str:
    ts = str(datetime.now().timestamp()).split('.', 1)[0]
    source_path = os.path.join(out_dir, SOURCES_DIR_NAME, filename.format(ts=ts))
    atomic_write(source_path, raw_text)
    log_source_saved(source_file=source_path)
    return source_path


@enforce_types
def save_file_as_source(path: str, timeout: int=TIMEOUT, filename: str='{ts}-{basename}.txt', out_dir: str=OUTPUT_DIR) -> str:
    """download a given url's content into output/sources/domain-<timestamp>.txt"""
    ts = str(datetime.now().timestamp()).split('.', 1)[0]
    source_path = os.path.join(OUTPUT_DIR, SOURCES_DIR_NAME, filename.format(basename=basename(path), ts=ts))

    if any(path.startswith(s) for s in ('http://', 'https://', 'ftp://')):
        # Source is a URL that needs to be downloaded
        print('{}[*] [{}] Downloading {}{}'.format(
            ANSI['green'],
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            path,
            ANSI['reset'],
        ))
        timer = TimedProgress(timeout, prefix='      ')
        try:
            raw_source_text = download_url(path, timeout=timeout)
            timer.end()
        except Exception as e:
            timer.end()
            print('{}[!] Failed to download {}{}\n'.format(
                ANSI['red'],
                path,
                ANSI['reset'],
            ))
            print('    ', e)
            raise SystemExit(1)

    else:
        # Source is a path to a local file on the filesystem
        with open(path, 'r') as f:
            raw_source_text = f.read()

    atomic_write(source_path, raw_source_text)

    log_source_saved(source_file=source_path)

    return source_path


def check_url_parsing_invariants() -> None:
    """Check that plain text regex URL parsing works as expected"""

    # this is last-line-of-defense to make sure the URL_REGEX isn't
    # misbehaving, as the consequences could be disastrous and lead to many
    # incorrect/badly parsed links being added to the archive

    test_urls = '''
    https://example1.com/what/is/happening.html?what=1#how-about-this=1
    https://example2.com/what/is/happening/?what=1#how-about-this=1
    HTtpS://example3.com/what/is/happening/?what=1#how-about-this=1f
    https://example4.com/what/is/happening.html
    https://example5.com/
    https://example6.com

    <test>http://example7.com</test>
    [https://example8.com/what/is/this.php?what=1]
    [and http://example9.com?what=1&other=3#and-thing=2]
    <what>https://example10.com#and-thing=2 "</about>
    abc<this["https://example11.com/what/is#and-thing=2?whoami=23&where=1"]that>def
    sdflkf[what](https://example12.com/who/what.php?whoami=1#whatami=2)?am=hi
    example13.bada
    and example14.badb
    <or>htt://example15.badc</that>
    '''
    # print('\n'.join(re.findall(URL_REGEX, test_urls)))
    assert len(re.findall(URL_REGEX, test_urls)) == 12

