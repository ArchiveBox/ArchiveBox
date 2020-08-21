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