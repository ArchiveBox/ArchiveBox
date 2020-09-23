from archivebox import util

def test_download_url_downloads_content():
    text = util.download_url("http://127.0.0.1:8080/static/example.com.html")
    assert "Example Domain" in text

def test_download_url_gets_encoding_from_body():
    text = util.download_url("http://127.0.0.1:8080/static_no_content_type/shift_jis.html")
    assert "鹿児島のニュース｜MBC南日本放送" in text
    assert "掲載された全ての記事・画像等の無断転載、二次利用をお断りいたします" in text