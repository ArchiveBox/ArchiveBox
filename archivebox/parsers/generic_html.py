__package__ = 'archivebox.parsers'


import re

from typing import IO, Iterable, Optional
from datetime import datetime, timezone

from ..index.schema import Link
from archivebox.misc.util import (
    htmldecode,
    enforce_types,
    find_all_urls,
)
from html.parser import HTMLParser
from urllib.parse import urljoin


class HrefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for attr, value in attrs:
                if attr == "href":
                    self.urls.append(value)


@enforce_types
def parse_generic_html_export(html_file: IO[str], root_url: Optional[str]=None, **_kwargs) -> Iterable[Link]:
    """Parse Generic HTML for href tags and use only the url (support for title coming later)"""

    html_file.seek(0)
    for line in html_file:
        parser = HrefParser()
        # example line
        # <li><a href="http://example.com/ time_added="1478739709" tags="tag1,tag2">example title</a></li>
        parser.feed(line)
        for url in parser.urls:
            if root_url:
                url_is_absolute = (url.lower().startswith('http://') or url.lower().startswith('https://'))
                # url = https://abc.com                       => True
                # url = /page.php?next=https://example.com    => False

                if not url_is_absolute:                       # resolve it by joining it with root_url
                    relative_path = url

                    url = urljoin(root_url, relative_path)    # https://example.com/somepage.html + /home.html
                                                              # => https://example.com/home.html

                    # special case to handle bug around // handling, crucial for urls that contain sub-urls
                    # e.g. https://web.archive.org/web/https://example.com
                    if did_urljoin_misbehave(root_url, relative_path, url):
                        url = fix_urljoin_bug(url)

            for archivable_url in find_all_urls(url):
                yield Link(
                    url=htmldecode(archivable_url),
                    timestamp=str(datetime.now(timezone.utc).timestamp()),
                    title=None,
                    tags=None,
                    sources=[html_file.name],
                )


KEY = 'html'
NAME = 'Generic HTML'
PARSER = parse_generic_html_export


#### WORKAROUND CODE FOR https://github.com/python/cpython/issues/96015 ####

def did_urljoin_misbehave(root_url: str, relative_path: str, final_url: str) -> bool:
    """
    Handle urljoin edge case bug where multiple slashes get turned into a single slash:
    - https://github.com/python/cpython/issues/96015
    - https://github.com/ArchiveBox/ArchiveBox/issues/1411

    This workaround only fixes the most common case of a sub-URL inside an outer URL, e.g.:
       https://web.archive.org/web/https://example.com/some/inner/url

    But there are other valid URLs containing // that are not fixed by this workaround, e.g.:
       https://example.com/drives/C//some/file
    """

    # if relative path is actually an absolute url, cut off its own scheme so we check the path component only
    relative_path = relative_path.lower()
    if relative_path.startswith('http://') or relative_path.startswith('https://'):
        relative_path = relative_path.split('://', 1)[-1]

    # TODO: properly fix all double // getting stripped by urljoin, not just ://
    original_path_had_suburl = '://' in relative_path
    original_root_had_suburl = '://' in root_url[8:]     # ignore first 8 chars because root always starts with https://
    final_joined_has_suburl = '://' in final_url[8:]     # ignore first 8 chars because final always starts with https://

    urljoin_broke_suburls = (
        (original_root_had_suburl or original_path_had_suburl)
        and not final_joined_has_suburl
    )
    return urljoin_broke_suburls


def fix_urljoin_bug(url: str, nesting_limit=5):
    """
    recursively replace broken suburls .../http:/... with .../http://...

    basically equivalent to this for 99.9% of cases:
      url = url.replace('/http:/',  '/http://')
      url = url.replace('/https:/', '/https://')
    except this handles:
        other schemes besides http/https     (e.g. https://example.com/link/git+ssh://github.com/example)
        other preceding separators besides / (e.g. https://example.com/login/?next=https://example.com/home)
        fixing multiple suburls recursively
    """
    input_url = url
    for _ in range(nesting_limit):
        url = re.sub(
            r'(?P<root>.+?)'                             # https://web.archive.org/web
            + r'(?P<separator>[-=/_&+%$#@!*\(\\])'       # /
            + r'(?P<subscheme>[a-zA-Z0-9+_-]{1,32}?):/'  # http:/
            + r'(?P<suburl>[^/\\]+)',                    # example.com
            r"\1\2\3://\4",
            input_url,
            re.IGNORECASE | re.UNICODE,
        )
        if url == input_url:
            break                                        # nothing left to replace, all suburls are fixed
        input_url = url

    return url


# sanity check to make sure workaround code works as expected and doesnt introduce *more* bugs
assert did_urljoin_misbehave('https://web.archive.org/web/https://example.com', 'abc.html', 'https://web.archive.org/web/https:/example.com/abc.html') == True
assert did_urljoin_misbehave('http://example.com', 'https://web.archive.org/web/http://example.com/abc.html', 'https://web.archive.org/web/http:/example.com/abc.html') == True
assert fix_urljoin_bug('https:/example.com') == 'https:/example.com'   # should not modify original url's scheme, only sub-urls
assert fix_urljoin_bug('https://web.archive.org/web/https:/example.com/abc.html') == 'https://web.archive.org/web/https://example.com/abc.html'
assert fix_urljoin_bug('http://example.com/link/git+ssh:/github.com/example?next=ftp:/example.com') == 'http://example.com/link/git+ssh://github.com/example?next=ftp://example.com'

