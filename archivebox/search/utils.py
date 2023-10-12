from html.parser import HTMLParser
import io

from django.db.models import QuerySet

from archivebox.util import enforce_types
from archivebox.config import ANSI, SEARCH_PROCESS_HTML

BLOCK_SIZE = 32768

def log_index_started(url):
    print('{green}[*] Indexing url: {} in the search index {reset}'.format(url, **ANSI))
    print( )


class HTMLTextExtractor(HTMLParser):

    TEXT_ATTRS = ["alt", "cite", "href", "label", "list", "placeholder", "title", "value"]
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
                self.output.write(value.strip())
                self.output.write(" ")

    def handle_endtag(self, tag):
        orig_stack = self._tag_stack.copy()
        try:
            # Keep popping tags until we find the nearest
            # ancestor matching this end tag
            while tag != self._tag_stack.pop():
                pass
        except IndexError:
            # Got to the top of the stack, but somehow missed
            # this end tag -- maybe malformed markup -- restore the
            # stack
            self._tag_stack = orig_stack

    def handle_data(self, data):
        # Don't output text data if any ancestor is in NOTEXT_TAGS
        if self._in_notext_tag():
            return
        if stripped := data.strip():
            self.output.write(stripped)
            self.output.write(" ")

    def __str__(self):
        return self.output.getvalue()


def _read_all(file: io.TextIOBase) -> str:
    return file.read()


def _extract_html_text(file: io.TextIOBase) -> str:
    extractor = HTMLTextExtractor()
    while (block := file.read(BLOCK_SIZE)):
        extractor.feed(block)
    else:
        extractor.close()

    return str(extractor)


def get_file_result_content(res, extra_path, use_pwd=False, *, filter=_read_all):
    if use_pwd: 
        fpath = f'{res.pwd}/{res.output}'
    else:
        fpath = f'{res.output}'

    if extra_path:
        fpath = f'{fpath}/{extra_path}'

    with open(fpath, 'r', encoding='utf-8', errors='replace') as file:
        data = filter(file)
    if data:
        return [data]
    return []


# This should be abstracted by a plugin interface for extractors
@enforce_types
def get_indexable_content(results: QuerySet):
    if not results:
        return []
    # Only use the first method available
    res, method = results.first(), results.first().extractor
    if method not in ('readability', 'singlefile', 'dom', 'wget'):
        return []
    # This should come from a plugin interface

    # TODO: banish this duplication and get these from the extractor file
    if method == 'readability':
        return get_file_result_content(res, 'content.txt', use_pwd=True)
    elif method == 'singlefile':
        filter = _extract_html_text if SEARCH_PROCESS_HTML else _read_all
        return get_file_result_content(res, '', use_pwd=True, filter=filter)
    elif method == 'dom':
        return get_file_result_content(res, '', use_pwd=True)
    elif method == 'wget':
        return get_file_result_content(res, '', use_pwd=True)
