from archivebox import util

def test_download_url_downloads_content():
    text = util.download_url("http://localhost:8080/static/example.com.html")
    assert "Example Domain" in text