__package__ = 'archivebox.extractors'

from html.parser import HTMLParser
import io
from pathlib import Path
from typing import Optional

from archivebox.config import VERSION
from archivebox.config.common import ARCHIVING_CONFIG
from archivebox.config.legacy import SAVE_HTMLTOTEXT
from archivebox.misc.system import atomic_write
from archivebox.misc.util import enforce_types, is_static_file

from ..logging_util import TimedProgress
from ..index.schema import Link, ArchiveResult, ArchiveError
from .title import get_html


def get_output_path():
    return "htmltotext.txt"



class HTMLTextExtractor(HTMLParser):
    TEXT_ATTRS = [
        "alt", "cite", "href", "label",
        "list", "placeholder", "title", "value"
    ]
    NOTEXT_TAGS = ["script", "style", "template"]
    NOTEXT_HREF = ["data:", "javascript:", "#"]

    def __init__(self):
        super().__init__()

        self.output = io.StringIO()
        self._tag_stack = []

    def _is_text_attr(self, name, value):
        if not isinstance(value, str):
            return False
        if name == "href" and any(map(lambda p: value.startswith(p), self.NOTEXT_HREF)):
            return False

        if name in self.TEXT_ATTRS:
            return True

        return False

    def _parent_tag(self):
        try:
            return self._tag_stack[-1]
        except IndexError:
            return None

    def _in_notext_tag(self):
        return any([t in self._tag_stack for t in self.NOTEXT_TAGS])

    def handle_starttag(self, tag, attrs):
        self._tag_stack.append(tag)

        # Don't write out attribute values if any ancestor
        # is in NOTEXT_TAGS
        if self._in_notext_tag():
            return

        for name, value in attrs:
            if self._is_text_attr(name, value):
                self.output.write(f"({value.strip()}) ")

    def handle_endtag(self, tag):
        orig_stack = self._tag_stack.copy()
        try:
            # Keep popping tags until we find the nearest
            # ancestor matching this end tag
            while tag != self._tag_stack.pop():
                pass
            # Write a space after every tag, to ensure that tokens
            # in tag text aren't concatenated. This may result in
            # excess spaces, which should be ignored by search tokenizers.
            if not self._in_notext_tag() and tag not in self.NOTEXT_TAGS:
                self.output.write(" ")
        except IndexError:
            # Got to the top of the stack, but somehow missed
            # this end tag -- maybe malformed markup -- restore the
            # stack
            self._tag_stack = orig_stack

    def handle_data(self, data):
        # Don't output text data if any ancestor is in NOTEXT_TAGS
        if self._in_notext_tag():
            return

        data = data.lstrip()
        len_before_rstrip = len(data)
        data = data.rstrip()
        spaces_rstripped = len_before_rstrip - len(data)
        if data:
            self.output.write(data)
            if spaces_rstripped:
                # Add back a single space if 1 or more
                # whitespace characters were stripped
                self.output.write(' ')

    def __str__(self):
        return self.output.getvalue()


@enforce_types
def should_save_htmltotext(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        return False

    return SAVE_HTMLTOTEXT


@enforce_types
def save_htmltotext(link: Link, out_dir: Optional[Path]=None, timeout: int=ARCHIVING_CONFIG.TIMEOUT) -> ArchiveResult:
    """extract search-indexing-friendly text from an HTML document"""

    out_dir = Path(out_dir or link.link_dir)
    output = get_output_path()
    cmd = ['(internal) archivebox.extractors.htmltotext', './{singlefile,dom}.html']

    timer = TimedProgress(timeout, prefix='      ')
    extracted_text = None
    status = 'failed'
    try:
        extractor = HTMLTextExtractor()
        document = get_html(link, out_dir)

        if not document:
            raise ArchiveError('htmltotext could not find HTML to parse for article text')

        extractor.feed(document)
        extractor.close()
        extracted_text = str(extractor)

        atomic_write(str(out_dir / output), extracted_text)
        status = 'succeeded'
    except (Exception, OSError) as err:
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=VERSION,
        output=output,
        status=status,
        index_texts=[extracted_text] if extracted_text else [],
        **timer.stats,  
    )
