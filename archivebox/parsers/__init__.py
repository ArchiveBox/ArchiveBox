"""
Everything related to parsing links from input sources.

For a list of supported services, see the README.md.
For examples of supported import formats see tests/.
"""

__package__ = 'archivebox.parsers'

from io import StringIO

from typing import IO, Tuple, List, Optional
from datetime import datetime, timezone
from pathlib import Path 

from archivebox.config import DATA_DIR, CONSTANTS
from archivebox.config.common import SHELL_CONFIG, ARCHIVING_CONFIG
from archivebox.misc.system import atomic_write
from archivebox.misc.logging import stderr, hint
from archivebox.misc.util import (
    basename,
    htmldecode,
    download_url,
    enforce_types,
)

from ..index.schema import Link
from ..logging_util import TimedProgress, log_source_saved

from . import pocket_api
from . import readwise_reader_api
from . import wallabag_atom
from . import pocket_html
from . import pinboard_rss
from . import shaarli_rss
from . import medium_rss
from . import netscape_html
from . import generic_rss
from . import generic_json
from . import generic_jsonl
from . import generic_html
from . import generic_txt
from . import url_list


PARSERS = {
    # Specialized parsers
    pocket_api.KEY:     (pocket_api.NAME,       pocket_api.PARSER),
    readwise_reader_api.KEY: (readwise_reader_api.NAME, readwise_reader_api.PARSER),
    wallabag_atom.KEY:  (wallabag_atom.NAME,    wallabag_atom.PARSER),
    pocket_html.KEY:    (pocket_html.NAME,      pocket_html.PARSER),
    pinboard_rss.KEY:   (pinboard_rss.NAME,     pinboard_rss.PARSER),
    shaarli_rss.KEY:    (shaarli_rss.NAME,      shaarli_rss.PARSER),
    medium_rss.KEY:     (medium_rss.NAME,       medium_rss.PARSER),

    # General parsers
    netscape_html.KEY:  (netscape_html.NAME,    netscape_html.PARSER),
    generic_rss.KEY:    (generic_rss.NAME,      generic_rss.PARSER),
    generic_json.KEY:   (generic_json.NAME,     generic_json.PARSER),
    generic_jsonl.KEY:  (generic_jsonl.NAME,    generic_jsonl.PARSER),
    generic_html.KEY:   (generic_html.NAME,     generic_html.PARSER),

    # Catchall fallback parser
    generic_txt.KEY:    (generic_txt.NAME,      generic_txt.PARSER),

    # Explicitly specified parsers
    url_list.KEY:       (url_list.NAME,         url_list.PARSER),
}


@enforce_types
def parse_links_memory(urls: List[str], root_url: Optional[str]=None):
    """
    parse a list of URLS without touching the filesystem
    """

    timer = TimedProgress(ARCHIVING_CONFIG.TIMEOUT * 4)
    #urls = list(map(lambda x: x + "\n", urls))
    file = StringIO()
    file.writelines(urls)
    file.name = "io_string"
    links, parser = run_parser_functions(file, timer, root_url=root_url)
    timer.end()

    if parser is None:
        return [], 'Failed to parse'
    return links, parser
    

@enforce_types
def parse_links(source_file: str, root_url: Optional[str]=None, parser: str="auto") -> Tuple[List[Link], str]:
    """parse a list of URLs with their metadata from an 
       RSS feed, bookmarks export, or text file
    """

    timer = TimedProgress(ARCHIVING_CONFIG.TIMEOUT * 4)
    with open(source_file, 'r', encoding='utf-8') as file:
        links, parser = run_parser_functions(file, timer, root_url=root_url, parser=parser)

    timer.end()
    if parser is None:
        return [], 'Failed to parse'
    return links, parser


def run_parser_functions(to_parse: IO[str], timer, root_url: Optional[str]=None, parser: str="auto") -> Tuple[List[Link], Optional[str]]:
    most_links: List[Link] = []
    best_parser_name = None

    if parser != "auto":
        parser_name, parser_func = PARSERS[parser]
        parsed_links = list(parser_func(to_parse, root_url=root_url))
        if not parsed_links:
            stderr()
            stderr(f'[X] No links found using {parser_name} parser', color='red')
            hint('Try a different parser or double check the input?')
            stderr()
        timer.end()
        return parsed_links, parser_name

    for parser_id in PARSERS:
        parser_name, parser_func = PARSERS[parser_id]
        try:
            parsed_links = list(parser_func(to_parse, root_url=root_url))
            if not parsed_links:
                raise Exception(f'No links found using {parser_name} parser')

            # print(f'[√] Parser {parser_name} succeeded: {len(parsed_links)} links parsed')
            if len(parsed_links) > len(most_links):
                most_links = parsed_links
                best_parser_name = parser_name
                
        except Exception as err:                                                # noqa
            # Parsers are tried one by one down the list, and the first one
            # that succeeds is used. To debug why a certain parser was not used
            # due to python error or format incompatibility, uncomment this line:
            
            # print('[!] Parser {} failed: {} {}'.format(parser_name, err.__class__.__name__, err))
            # raise
            pass
    timer.end()
    return most_links, best_parser_name


@enforce_types
def save_text_as_source(raw_text: str, filename: str='{ts}-stdin.txt', out_dir: Path=DATA_DIR) -> str:
    ts = str(datetime.now(timezone.utc).timestamp()).split('.', 1)[0]
    source_path = str(CONSTANTS.SOURCES_DIR / filename.format(ts=ts))

    referenced_texts = ''

    # dont attempt to read local files from the text, security risk:
    # for entry in raw_text.split():
    #     try:
    #         if Path(entry).exists():
    #             referenced_texts += Path(entry).read_text()
    #     except Exception as err:
    #         print(err)

    atomic_write(source_path, raw_text + '\n' + referenced_texts)
    log_source_saved(source_file=source_path)
    return source_path


@enforce_types
def save_file_as_source(path: str, timeout: int=ARCHIVING_CONFIG.TIMEOUT, filename: str='{ts}-{basename}.txt', out_dir: Path=DATA_DIR) -> str:
    """download a given url's content into output/sources/domain-<timestamp>.txt"""
    ts = str(datetime.now(timezone.utc).timestamp()).split('.', 1)[0]
    source_path = str(CONSTANTS.SOURCES_DIR / filename.format(basename=basename(path), ts=ts))

    if any(path.startswith(s) for s in ('http://', 'https://', 'ftp://')):
        # Source is a URL that needs to be downloaded
        print(f'    > Downloading {path} contents')
        timer = TimedProgress(timeout, prefix='      ')
        try:
            raw_source_text = download_url(path, timeout=timeout)
            raw_source_text = htmldecode(raw_source_text)
            timer.end()
        except Exception as e:
            timer.end()
            print('{}[!] Failed to download {}{}\n'.format(
                SHELL_CONFIG.ANSI['red'],
                path,
                SHELL_CONFIG.ANSI['reset'],
            ))
            print('    ', e)
            raise e

    else:
        # Source is a path to a local file on the filesystem
        with open(path, 'r') as f:
            raw_source_text = f.read()

    atomic_write(source_path, raw_source_text)

    log_source_saved(source_file=source_path)

    return source_path
