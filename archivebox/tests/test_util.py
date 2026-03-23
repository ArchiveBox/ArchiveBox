from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from archivebox.misc.util import download_url


class _ExampleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><body><h1>Example Domain</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def test_download_url_downloads_content():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ExampleHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        text = download_url(f"http://127.0.0.1:{server.server_address[1]}/")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert "Example Domain" in text
