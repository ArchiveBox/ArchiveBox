from archivebox import util

def test_download_url_downloads_content():
    text = util.download_url("https://example.com")
    assert "Example Domain" in text