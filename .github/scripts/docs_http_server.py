from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class DocsRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = f"<!doctype html><title>ArchiveBox docs fixture</title><p>{self.path}</p>\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready-fifo", type=Path, required=True)
    args = parser.parse_args()

    with ThreadingHTTPServer(("127.0.0.1", 0), DocsRequestHandler) as server:
        host, port = server.server_address
        with args.ready_fifo.open("w") as ready_fifo:
            ready_fifo.write(f"http://{host}:{port}\n")
        server.serve_forever()


if __name__ == "__main__":
    main()
