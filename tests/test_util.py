from archivebox.misc.util import download_url

def test_download_url_downloads_content():
    text = download_url("https://example.com")
    assert "Example Domain" in text
