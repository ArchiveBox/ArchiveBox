from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from archivebox.misc.util import download_url, find_all_urls, fix_url_from_markdown


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


# URL parsing regression tests — last-line-of-defense to make sure URL_REGEX
# and fix_url_from_markdown don't regress due to regex engine / cpython / locale
# differences. Bad URL parsing leads to many incorrectly archived links, so
# these checks are worth running.


@pytest.mark.parametrize(
    "input_url,expected",
    [
        (
            "http://example.com/a(b)c).x(y)z",
            "http://example.com/a(b)c",
        ),
        (
            "https://wikipedia.org/en/some_article_(Disambiguation).html?abc=def).link(with)_trailingtext",
            "https://wikipedia.org/en/some_article_(Disambiguation).html?abc=def",
        ),
    ],
)
def test_fix_url_from_markdown_trims_trailing_junk(input_url, expected):
    assert fix_url_from_markdown(input_url) == expected


URL_REGEX_CASES = [
    ("https://example.com", ["https://example.com"]),
    ("https://sweeting.me,https://google.com", ["https://sweeting.me", "https://google.com"]),
    (
        "http://abc-file234example.com/abc?def=abc&23423=sdfsdf#abc=234&234=a234",
        ["http://abc-file234example.com/abc?def=abc&23423=sdfsdf#abc=234&234=a234"],
    ),
    (
        "https://twitter.com/share?url=https://akaao.success-corp.co.jp&text=ア@サ!ト&hashtags=ア%オ,元+ア.ア-オ_イ*シ$ロ abc",
        [
            "https://twitter.com/share?url=https://akaao.success-corp.co.jp&text=ア@サ!ト&hashtags=ア%オ,元+ア.ア-オ_イ*シ$ロ",
            "https://akaao.success-corp.co.jp&text=ア@サ!ト&hashtags=ア%オ,元+ア.ア-オ_イ*シ$ロ",
        ],
    ),
    (
        '<a href="https://twitter.com/share#url=https://akaao.success-corp.co.jp&text=ア@サ!ト?hashtags=ア%オ,元+ア&abc=.ア-オ_イ*シ$ロ"> abc',
        [
            "https://twitter.com/share#url=https://akaao.success-corp.co.jp&text=ア@サ!ト?hashtags=ア%オ,元+ア&abc=.ア-オ_イ*シ$ロ",
            "https://akaao.success-corp.co.jp&text=ア@サ!ト?hashtags=ア%オ,元+ア&abc=.ア-オ_イ*シ$ロ",
        ],
    ),
    ("///a", []),
    ("http://", []),
    ("http://../", ["http://../"]),
    ("http://-error-.invalid/", ["http://-error-.invalid/"]),
    ("https://a(b)c+1#2?3&4/", ["https://a(b)c+1#2?3&4/"]),
    ("http://उदाहरण.परीक्षा", ["http://उदाहरण.परीक्षा"]),
    ("http://例子.测试", ["http://例子.测试"]),
    ("http://➡.ws/䨹 htps://abc.1243?234", ["http://➡.ws/䨹"]),
    ('http://⌘.ws">https://exa+mple.com//:abc ', ["http://⌘.ws", "https://exa+mple.com//:abc"]),
    ("http://مثال.إختبار/abc?def=ت&ب=abc#abc=234", ["http://مثال.إختبار/abc?def=ت&ب=abc#abc=234"]),
    ("http://-.~_!$&()*+,;=:%40:80%2f::::::@example.c'om", ["http://-.~_!$&()*+,;=:%40:80%2f::::::@example.c"]),
    (
        "http://us:pa@ex.co:42/http://ex.co:19/a?_d=4#-a=2.3",
        ["http://us:pa@ex.co:42/http://ex.co:19/a?_d=4#-a=2.3", "http://ex.co:19/a?_d=4#-a=2.3"],
    ),
    ("http://code.google.com/events/#&product=browser", ["http://code.google.com/events/#&product=browser"]),
    ("http://foo.bar?q=Spaces should be encoded", ["http://foo.bar?q=Spaces"]),
    ("http://foo.com/blah_(wikipedia)#c(i)t[e]-1", ["http://foo.com/blah_(wikipedia)#c(i)t"]),
    ("http://foo.com/(something)?after=parens", ["http://foo.com/(something)?after=parens"]),
    ("http://foo.com/unicode_(✪)_in_parens) abc", ["http://foo.com/unicode_(✪)_in_parens"]),
    ("http://foo.bar/?q=Test%20URL-encoded%20stuff", ["http://foo.bar/?q=Test%20URL-encoded%20stuff"]),
    ("[xyz](http://a.b/?q=(Test)%20U)RL-encoded%20stuff", ["http://a.b/?q=(Test)%20U"]),
    ("[xyz](http://a.b/?q=(Test)%20U)-ab https://abc+123", ["http://a.b/?q=(Test)%20U", "https://abc+123"]),
    ("[xyz](http://a.b/?q=(Test)%20U) https://a(b)c+12)3", ["http://a.b/?q=(Test)%20U", "https://a(b)c+12"]),
    ("[xyz](http://a.b/?q=(Test)a\nabchttps://a(b)c+12)3", ["http://a.b/?q=(Test)a", "https://a(b)c+12"]),
]


@pytest.mark.parametrize("urls_str,expected_url_matches", URL_REGEX_CASES)
def test_find_all_urls_matches_expected(urls_str, expected_url_matches):
    assert list(find_all_urls(urls_str)) == expected_url_matches


URL_REGEX_COUNT_CASES = {
    "example.com": 0,
    "/example.com": 0,
    "//example.com": 0,
    ":/example.com": 0,
    "://example.com": 0,
    "htt://example8.com": 0,
    "/htt://example.com": 0,
    "https://example": 1,
    "https://localhost/2345": 1,
    "https://localhost:1234/123": 1,
    "://": 0,
    "https://": 0,
    "http://": 0,
    "ftp://": 0,
    "ftp://example.com": 0,
    "https://example.com": 1,
    "https://example.com/": 1,
    "https://a.example.com": 1,
    "https://a.example.com/": 1,
    "https://a.example.com/what/is/happening.html": 1,
    "https://a.example.com/what/ís/happening.html": 1,
    "https://a.example.com/what/is/happening.html?what=1&2%20b#höw-about-this=1a": 1,
    "https://a.example.com/what/is/happéning/?what=1&2%20b#how-aboüt-this=1a": 1,
    "HTtpS://a.example.com/what/is/happening/?what=1&2%20b#how-about-this=1af&2f%20b": 1,
    "https://example.com/?what=1#how-about-this=1&2%20baf": 1,
    "https://example.com?what=1#how-about-this=1&2%20baf": 1,
    "<test>http://example7.com</test>": 1,
    "https://<test>": 0,
    "https://[test]": 0,
    'http://"test"': 0,
    "http://'test'": 0,
    "[https://example8.com/what/is/this.php?what=1]": 1,
    "[and http://example9.com?what=1&other=3#and-thing=2]": 1,
    '<what>https://example10.com#and-thing=2 "</about>': 1,
    'abc<this["https://example11.com/what/is#and-thing=2?whoami=23&where=1"]that>def': 1,
    "sdflkf[what](https://example12.com/who/what.php?whoami=1#whatami=2)?am=hi": 1,
    "<or>http://examplehttp://15.badc</that>": 2,
    "https://a.example.com/one.html?url=http://example.com/inside/of/another?=http://": 2,
    "[https://a.example.com/one.html?url=http://example.com/inside/of/another?=](http://a.example.com)": 3,
}


@pytest.mark.parametrize("url_str,num_urls", list(URL_REGEX_COUNT_CASES.items()))
def test_find_all_urls_count(url_str, num_urls):
    assert len(list(find_all_urls(url_str))) == num_urls
