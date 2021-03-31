import os
import sqlite3

from .fixtures import *

def test_remove_single_page(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    remove_process = subprocess.run(['archivebox', 'remove', 'http://127.0.0.1:8080/static/example.com.html', '--yes'], capture_output=True)
    assert "Found 1 matching URLs to remove" in remove_process.stdout.decode("utf-8")

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT() from core_snapshot").fetchone()[0]
    conn.commit()
    conn.close()

    assert count == 0


def test_remove_single_page_filesystem(tmp_path, process, disable_extractors_dict):
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []

    subprocess.run(['archivebox', 'remove', 'http://127.0.0.1:8080/static/example.com.html', '--yes', '--delete'], capture_output=True)

    assert list((tmp_path / "archive").iterdir()) == []

def test_remove_regex(tmp_path, process, disable_extractors_dict):
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/iana.org.html'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []

    subprocess.run(['archivebox', 'remove', '--filter-type=regex', '.*', '--yes', '--delete'], capture_output=True)

    assert list((tmp_path / "archive").iterdir()) == []

def test_remove_exact(tmp_path, process, disable_extractors_dict):
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/iana.org.html'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []

    remove_process = subprocess.run(['archivebox', 'remove', '--filter-type=exact', 'http://127.0.0.1:8080/static/iana.org.html', '--yes', '--delete'], capture_output=True)

    assert len(list((tmp_path / "archive").iterdir())) == 1

def test_remove_substr(tmp_path, process, disable_extractors_dict):
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/iana.org.html'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []

    subprocess.run(['archivebox', 'remove', '--filter-type=substring', 'example.com', '--yes', '--delete'], capture_output=True)

    assert len(list((tmp_path / "archive").iterdir())) == 1

def test_remove_domain(tmp_path, process, disable_extractors_dict):
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/iana.org.html'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []

    remove_process = subprocess.run(['archivebox', 'remove', '--filter-type=domain', '127.0.0.1', '--yes', '--delete'], capture_output=True)

    assert len(list((tmp_path / "archive").iterdir())) == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT() from core_snapshot").fetchone()[0]
    conn.commit()
    conn.close()

    assert count == 0


def test_remove_tag(tmp_path, process, disable_extractors_dict):
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/iana.org.html'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []
    
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    c.execute("INSERT INTO core_tag (id, name, slug) VALUES (2, 'test-tag', 'test-tag')")
    snapshot_ids = c.execute("SELECT id from core_snapshot")
    c.executemany('INSERT INTO core_snapshot_tags (snapshot_id, tag_id) VALUES (?, 2)', list(snapshot_ids))
    conn.commit()

    remove_process = subprocess.run(['archivebox', 'remove', '--filter-type=tag', 'test-tag', '--yes', '--delete'], capture_output=True)

    assert len(list((tmp_path / "archive").iterdir())) == 0

    count = c.execute("SELECT COUNT() from core_snapshot").fetchone()[0]
    conn.commit()
    conn.close()

    assert count == 0

def test_remove_before(tmp_path, process, disable_extractors_dict):
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/iana.org.html'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    higherts, lowerts = timestamp = c.execute("SELECT timestamp FROM core_snapshot ORDER BY timestamp DESC").fetchall()
    conn.commit()
    conn.close()

    lowerts = lowerts[0]
    higherts = higherts[0]

    # before is less than, so only the lower snapshot gets deleted
    subprocess.run(['archivebox', 'remove', '--filter-type=regex', '.*', '--yes', '--delete', '--before', higherts], capture_output=True)

    assert not (tmp_path / "archive" / lowerts).exists()
    assert (tmp_path / "archive" / higherts).exists()

def test_remove_after(tmp_path, process, disable_extractors_dict):
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/iana.org.html'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    higherts, lowerts = c.execute("SELECT timestamp FROM core_snapshot ORDER BY timestamp DESC").fetchall()
    conn.commit()
    conn.close()

    lowerts = lowerts[0].split(".")[0]
    higherts = higherts[0].split(".")[0]

    # after is greater than or equal to, so both snapshots get deleted
    subprocess.run(['archivebox', 'remove', '--filter-type=regex', '.*', '--yes', '--delete', '--after', lowerts], capture_output=True)

    assert not (tmp_path / "archive" / lowerts).exists()
    assert not (tmp_path / "archive" / higherts).exists()
