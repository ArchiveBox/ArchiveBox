import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest


@pytest.fixture
def process(tmp_path):
    process = subprocess.run(
        ["archivebox", "init"],
        capture_output=True,
        cwd=tmp_path,
    )
    return process


@pytest.fixture
def disable_extractors_dict():
    env = os.environ.copy()
    env.update(
        {
            "SAVE_WGET": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_READABILITY": "false",
            "SAVE_MERCURY": "false",
            "SAVE_HTMLTOTEXT": "false",
            "SAVE_PDF": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_DOM": "false",
            "SAVE_HEADERS": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_TITLE": "false",
            "SAVE_FAVICON": "false",
        },
    )
    return env


@pytest.fixture
def recursive_test_site():
    pages = {
        "/": """
            <html>
              <head>
                <title>Root</title>
                <link rel="icon" href="/favicon.ico">
              </head>
              <body>
                <a href="/about">About</a>
                <a href="/blog">Blog</a>
                <a href="/contact">Contact</a>
              </body>
            </html>
        """.strip().encode("utf-8"),
        "/about": """
            <html>
              <body>
                <a href="/deep/about">Deep About</a>
              </body>
            </html>
        """.strip().encode("utf-8"),
        "/blog": """
            <html>
              <body>
                <a href="/deep/blog">Deep Blog</a>
              </body>
            </html>
        """.strip().encode("utf-8"),
        "/contact": """
            <html>
              <body>
                <a href="/deep/contact">Deep Contact</a>
              </body>
            </html>
        """.strip().encode("utf-8"),
        "/deep/about": b"<html><body><h1>Deep About</h1></body></html>",
        "/deep/blog": b"<html><body><h1>Deep Blog</h1></body></html>",
        "/deep/contact": b"<html><body><h1>Deep Contact</h1></body></html>",
        "/favicon.ico": b"test-icon",
    }

    class _RecursiveHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = pages.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            if self.path.endswith(".ico"):
                self.send_header("Content-Type", "image/x-icon")
            else:
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecursiveHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        yield {
            "base_url": base_url,
            "root_url": f"{base_url}/",
            "child_urls": [f"{base_url}/about", f"{base_url}/blog", f"{base_url}/contact"],
            "deep_urls": [f"{base_url}/deep/about", f"{base_url}/deep/blog", f"{base_url}/deep/contact"],
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
