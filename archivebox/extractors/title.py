__package__ = 'archivebox.extractors'

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

from archivebox.misc.util import (
    enforce_types,
    download_url,
    htmldecode,
    dedupe,
)
from archivebox.plugins_extractor.curl.apps import CURL_CONFIG, CURL_BINARY
from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..logging_util import TimedProgress



HTML_TITLE_REGEX = re.compile(
    r'<title.*?>'                      # start matching text after <title> tag
    r'([^<>]+)',                      # get everything up to these symbols
    re.IGNORECASE | re.MULTILINE | re.DOTALL | re.UNICODE,
)


class TitleParser(HTMLParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title_tag = ""
        self.title_og = ""
        self.inside_title_tag = False

    @property
    def title(self):
        return self.title_tag or self.title_og or None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title" and not self.title_tag:
            self.inside_title_tag = True
        elif tag.lower() == "meta" and not self.title_og:
            attrs = dict(attrs)
            if attrs.get("property") == "og:title" and attrs.get("content"):
                self.title_og = attrs.get("content")

    def handle_data(self, data):
        if self.inside_title_tag and data:
            self.title_tag += data.strip()
    
    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.inside_title_tag = False


@enforce_types
def get_html(link: Link, path: Path, timeout: int=CURL_CONFIG.CURL_TIMEOUT) -> str:
    """
    Try to find wget, singlefile and then dom files.
    If none is found, download the url again.
    """
    canonical = link.canonical_outputs()
    abs_path = path.absolute()

    # prefer chrome-generated DOM dump to singlefile as singlefile output often includes HUGE url(data:image/...base64) strings that crash parsers
    sources = [canonical["dom_path"], canonical["singlefile_path"], canonical["wget_path"]]
    document = None
    for source in sources:
        try:
            with open(abs_path / source, "r", encoding="utf-8") as f:
                document = f.read()
                break
        except (FileNotFoundError, TypeError, UnicodeDecodeError):
            continue
    if document is None:
        return download_url(link.url, timeout=timeout)
    else:
        return document


def get_output_path():
    # TODO: actually save title to this file
    # (currently only saved in ArchiveResult.output as charfield value, not saved to filesystem)
    return 'title.json'


@enforce_types
def should_save_title(link: Link, out_dir: Optional[str]=None, overwrite: Optional[bool]=False) -> bool:
    # if link already has valid title, skip it
    if not overwrite and link.title and not link.title.lower().startswith('http'):
        return False

    return CURL_CONFIG.SAVE_TITLE

def extract_title_with_regex(html):
    match = re.search(HTML_TITLE_REGEX, html)
    output = htmldecode(match.group(1).strip()) if match else None
    return output

@enforce_types
def save_title(link: Link, out_dir: Optional[Path]=None, timeout: int=CURL_CONFIG.CURL_TIMEOUT) -> ArchiveResult:
    """try to guess the page's title from its content"""

    from core.models import Snapshot

    curl_binary = CURL_BINARY.load()
    assert curl_binary.abspath and curl_binary.version

    output: ArchiveOutput = None
    # later options take precedence
    options = [
        *CURL_CONFIG.CURL_ARGS,
        *CURL_CONFIG.CURL_EXTRA_ARGS,
        '--max-time', str(timeout),
        *(['--user-agent', '{}'.format(CURL_CONFIG.CURL_USER_AGENT)] if CURL_CONFIG.CURL_USER_AGENT else []),
        *([] if CURL_CONFIG.CURL_CHECK_SSL_VALIDITY else ['--insecure']),
    ]
    cmd = [
        str(curl_binary.abspath),
        *dedupe(options),
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        html = get_html(link, out_dir, timeout=timeout)
        try:
            # try using relatively strict html parser first
            parser = TitleParser()
            parser.feed(html)
            output = parser.title
            if output is None:
                raise
        except Exception:
            # fallback to regex that can handle broken/malformed html
            output = extract_title_with_regex(html)
        
        # if title is better than the one in the db, update db with new title
        if isinstance(output, str) and output:
            if not link.title or len(output) >= len(link.title):
                Snapshot.objects.filter(url=link.url,
                                        timestamp=link.timestamp)\
                                .update(title=output)
        else:
            # if no content was returned, dont save a title (because it might be a temporary error)
            if not html:
                raise ArchiveError('Unable to detect page title')
            # output = html[:128]       # use first bit of content as the title
            output = link.base_url      # use the filename as the title (better UX)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=str(curl_binary.version),
        output=output,
        status=status,
        **timer.stats,
    )
