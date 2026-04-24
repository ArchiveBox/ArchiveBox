from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from archivebox.misc.util import (
    download_url,
    validate_url_strict,
    validate_urls_list,
    contains_invisible_chars,
    MAX_URL_LENGTH,
)


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


class TestValidateUrlStrict:
    def test_valid_http_url_passes(self):
        is_valid, error = validate_url_strict("http://example.com")
        assert is_valid is True
        assert error is None

    def test_valid_https_url_passes(self):
        is_valid, error = validate_url_strict("https://example.com/path?query=1#fragment")
        assert is_valid is True
        assert error is None

    def test_valid_url_with_port_passes(self):
        is_valid, error = validate_url_strict("https://example.com:8080/path")
        assert is_valid is True
        assert error is None

    def test_valid_localhost_url_passes(self):
        is_valid, error = validate_url_strict("http://localhost:8000/")
        assert is_valid is True
        assert error is None

    def test_valid_ip_url_passes(self):
        is_valid, error = validate_url_strict("http://192.168.1.1:8080/path")
        assert is_valid is True
        assert error is None

    def test_empty_url_fails(self):
        is_valid, error = validate_url_strict("")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_none_url_fails(self):
        is_valid, error = validate_url_strict(None)
        assert is_valid is False
        assert "empty" in error.lower()

    def test_whitespace_only_url_fails(self):
        is_valid, error = validate_url_strict("   \n\t  ")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_url_without_scheme_fails(self):
        is_valid, error = validate_url_strict("example.com/path")
        assert is_valid is False
        assert "http" in error.lower()

    def test_url_with_invalid_scheme_fails(self):
        is_valid, error = validate_url_strict("ftp://example.com")
        assert is_valid is False
        assert "http" in error.lower()

    def test_url_without_netloc_fails(self):
        is_valid, error = validate_url_strict("http:///path")
        assert is_valid is False
        assert "domain" in error.lower() or "netloc" in error.lower()

    def test_url_too_long_fails(self):
        long_url = "https://example.com/" + "a" * (MAX_URL_LENGTH + 1)
        is_valid, error = validate_url_strict(long_url)
        assert is_valid is False
        assert "too long" in error.lower()

    def test_url_with_null_char_fails(self):
        url_with_null = "https://example.com/path\x00"
        is_valid, error = validate_url_strict(url_with_null)
        assert is_valid is False
        assert "control" in error.lower() or "invalid" in error.lower()

    def test_url_with_zero_width_space_fails(self):
        url_with_zws = "https://example.com/\u200Bpath"
        is_valid, error = validate_url_strict(url_with_zws)
        assert is_valid is False
        assert "control" in error.lower() or "invalid" in error.lower()

    def test_url_with_bidi_override_fails(self):
        url_with_bidi = "https://example.com/\u202Epath"
        is_valid, error = validate_url_strict(url_with_bidi)
        assert is_valid is False
        assert "control" in error.lower() or "invalid" in error.lower()


class TestContainsInvisibleChars:
    def test_normal_url_has_no_invisible_chars(self):
        assert contains_invisible_chars("https://example.com") is False

    def test_url_with_null_char_has_invisible_chars(self):
        assert contains_invisible_chars("https://example.com\x00") is True

    def test_url_with_zero_width_space_has_invisible_chars(self):
        assert contains_invisible_chars("https://example.com\u200B") is True

    def test_url_with_bom_has_invisible_chars(self):
        assert contains_invisible_chars("\uFEFFhttps://example.com") is True

    def test_url_with_control_char_has_invisible_chars(self):
        assert contains_invisible_chars("https://example.com\x1F") is True


class TestValidateUrlsList:
    def test_all_valid_urls_pass(self):
        urls = [
            "https://example.com",
            "http://test.org/path",
            "https://localhost:8000/api",
        ]
        is_valid, error, valid_urls = validate_urls_list(urls)
        assert is_valid is True
        assert error is None
        assert valid_urls == urls

    def test_invalid_url_in_list_fails(self):
        urls = [
            "https://example.com",
            "invalid-url",
            "https://test.org",
        ]
        is_valid, error, valid_urls = validate_urls_list(urls)
        assert is_valid is False
        assert error is not None
        assert valid_urls == ["https://example.com"]

    def test_empty_list_returns_valid(self):
        is_valid, error, valid_urls = validate_urls_list([])
        assert is_valid is True
        assert error is None
        assert valid_urls == []
