#!/usr/bin/env python3
"""Serve gallery exports on localhost using ArchiveBox's byte-range support."""

import argparse
import os
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

import django
from django.conf import settings
from django.core.handlers.wsgi import WSGIHandler
from django.http import HttpResponseNotAllowed
from django.urls import re_path


def serve_export(request, path=""):
    from archivebox.misc.serve_static import serve_static_with_byterange_support

    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD"])
    request.GET = request.GET.copy()
    request.GET["raw"] = "1"
    if not path or path.endswith("/"):
        path += "index.html"
    return serve_static_with_byterange_support(request, path, document_root=export_directory)


urlpatterns = [re_path(r"^(?P<path>.*)$", serve_export)]


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", type=int)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    export_directory = args.directory.resolve(strict=True)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.core.settings")
    django.setup()
    settings.ROOT_URLCONF = __name__
    settings.MIDDLEWARE = []
    settings.ALLOWED_HOSTS = ["127.0.0.1"]
    with make_server("127.0.0.1", args.port, WSGIHandler(), server_class=ThreadingWSGIServer) as server:
        print(f"Serving gallery exports on http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()
