import os
import stat
import posixpath
import mimetypes
from pathlib import Path

from django.contrib.staticfiles import finders
from django.views import static
from django.http import StreamingHttpResponse, Http404, HttpResponse, HttpResponseNotModified
from django.utils._os import safe_join
from django.utils.http import http_date
from django.utils.translation import gettext as _


def serve_static_with_byterange_support(request, path, document_root=None, show_indexes=False):
    """
    Overrides Django's built-in django.views.static.serve function to support byte range requests.
    This allows you to do things like seek into the middle of a huge mp4 or WACZ without downloading the whole file.
    https://github.com/satchamo/django/commit/2ce75c5c4bee2a858c0214d136bfcd351fcde11d
    """
    assert document_root
    path = posixpath.normpath(path).lstrip("/")
    fullpath = Path(safe_join(document_root, path))
    if os.access(fullpath, os.R_OK) and fullpath.is_dir():
        if show_indexes:
            return static.directory_index(path, fullpath)
        raise Http404(_("Directory indexes are not allowed here."))
    if not os.access(fullpath, os.R_OK):
        raise Http404(_("“%(path)s” does not exist") % {"path": fullpath})
    
    # Respect the If-Modified-Since header.
    statobj = fullpath.stat()
    if not static.was_modified_since(request.META.get("HTTP_IF_MODIFIED_SINCE"), statobj.st_mtime):
        return HttpResponseNotModified()
    
    content_type, encoding = mimetypes.guess_type(str(fullpath))
    content_type = content_type or "application/octet-stream"
    
    # setup resposne object
    ranged_file = RangedFileReader(open(fullpath, "rb"))
    response = StreamingHttpResponse(ranged_file, content_type=content_type)
    response.headers["Last-Modified"] = http_date(statobj.st_mtime)

    # handle byte-range requests by serving chunk of file    
    if stat.S_ISREG(statobj.st_mode):
        size = statobj.st_size
        response["Content-Length"] = size
        response["Accept-Ranges"] = "bytes"
        response["X-Django-Ranges-Supported"] = "1"
        # Respect the Range header.
        if "HTTP_RANGE" in request.META:
            try:
                ranges = parse_range_header(request.META['HTTP_RANGE'], size)
            except ValueError:
                ranges = None
            # only handle syntactically valid headers, that are simple (no
            # multipart byteranges)
            if ranges is not None and len(ranges) == 1:
                start, stop = ranges[0]
                if stop > size:
                    # requested range not satisfiable
                    return HttpResponse(status=416)
                ranged_file.start = start
                ranged_file.stop = stop
                response["Content-Range"] = "bytes %d-%d/%d" % (start, stop - 1, size)
                response["Content-Length"] = stop - start
                response.status_code = 206
    if encoding:
        response.headers["Content-Encoding"] = encoding
    return response


def serve_static(request, path, **kwargs):
    """
    Serve static files below a given point in the directory structure or
    from locations inferred from the staticfiles finders.

    To use, put a URL pattern such as::

        from django.contrib.staticfiles import views

        path('<path:path>', views.serve)

    in your URLconf.

    It uses the django.views.static.serve() view to serve the found files.
    """

    normalized_path = posixpath.normpath(path).lstrip("/")
    absolute_path = finders.find(normalized_path)
    if not absolute_path:
        if path.endswith("/") or path == "":
            raise Http404("Directory indexes are not allowed here.")
        raise Http404("'%s' could not be found" % path)
    document_root, path = os.path.split(absolute_path)
    return serve_static_with_byterange_support(request, path, document_root=document_root, **kwargs)


def parse_range_header(header, resource_size):
    """
    Parses a range header into a list of two-tuples (start, stop) where `start`
    is the starting byte of the range (inclusive) and `stop` is the ending byte
    position of the range (exclusive).
    Returns None if the value of the header is not syntatically valid.
    https://github.com/satchamo/django/commit/2ce75c5c4bee2a858c0214d136bfcd351fcde11d
    """
    if not header or "=" not in header:
        return None

    ranges = []
    units, range_ = header.split("=", 1)
    units = units.strip().lower()

    if units != "bytes":
        return None

    for val in range_.split(","):
        val = val.strip()
        if "-" not in val:
            return None

        if val.startswith("-"):
            # suffix-byte-range-spec: this form specifies the last N bytes of an
            # entity-body
            start = resource_size + int(val)
            if start < 0:
                start = 0
            stop = resource_size
        else:
            # byte-range-spec: first-byte-pos "-" [last-byte-pos]
            start, stop = val.split("-", 1)
            start = int(start)
            # the +1 is here since we want the stopping point to be exclusive, whereas in
            # the HTTP spec, the last-byte-pos is inclusive
            stop = int(stop) + 1 if stop else resource_size
            if start >= stop:
                return None

        ranges.append((start, stop))

    return ranges


class RangedFileReader:
    """
    Wraps a file like object with an iterator that runs over part (or all) of
    the file defined by start and stop. Blocks of block_size will be returned
    from the starting position, up to, but not including the stop point.
    https://github.com/satchamo/django/commit/2ce75c5c4bee2a858c0214d136bfcd351fcde11d
    """

    block_size = 8192

    def __init__(self, file_like, start=0, stop=float("inf"), block_size=None):
        self.f = file_like
        self.block_size = block_size or RangedFileReader.block_size
        self.start = start
        self.stop = stop

    def __iter__(self):
        self.f.seek(self.start)
        position = self.start
        while position < self.stop:
            data = self.f.read(min(self.block_size, self.stop - position))
            if not data:
                break

            yield data
            position += self.block_size
