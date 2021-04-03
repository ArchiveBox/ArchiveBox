import sqlite3

from .fixtures import *

def test_update_status_invalid(tmp_path, process, disable_extractors_dict):
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []

    a_process = subprocess.run(['archivebox', 'remove', 'http://127.0.0.1:8080/static/example.com.html', '--yes'], capture_output=True)

    conn = sqlite3.connect(str(tmp_path / "index.sqlite3"))
    c = conn.cursor()
    link = c.execute("SELECT * FROM core_snapshot").fetchone()
    conn.commit()
    conn.close()

    assert link is None

    update_process = subprocess.run(['archivebox', 'update', '--status=invalid'], capture_output=True, env=disable_extractors_dict)

    conn = sqlite3.connect(str(tmp_path / "index.sqlite3"))
    c = conn.cursor()
    url = c.execute("SELECT url FROM core_snapshot").fetchone()[0]
    conn.commit()
    conn.close()
    
    assert url == 'http://127.0.0.1:8080/static/example.com.html'
