import os
import sqlite3

from .fixtures import *

def test_title_is_htmlencoded_in_index_html(tmp_path, process, disable_extractors_dict):
    """
    https://github.com/ArchiveBox/ArchiveBox/issues/330
    Unencoded content should not be rendered as it facilitates xss injections
    and breaks the layout.
    """
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/title_with_html.com.html'],
                                 capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--html"], capture_output=True)

    assert "<textarea>" not in list_process.stdout.decode("utf-8")

def test_title_in_meta_title(tmp_path, process, disable_extractors_dict):
    add_process = subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/title_with_html.com.html"],
                                   capture_output=True, env=disable_extractors_dict)

    os.chdir(tmp_path)
    conn = sqlite3.connect("index.sqlite3")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT title from core_snapshot")
    snapshot = c.fetchone()
    conn.close()

    assert snapshot[0] == "It All Starts with a Humble <textarea> ◆ 24 ways"

def test_title_in_meta_og(tmp_path, process, disable_extractors_dict):
    add_process = subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/title_og_with_html.com.html"],
                                   capture_output=True, env=disable_extractors_dict)

    os.chdir(tmp_path)
    conn = sqlite3.connect("index.sqlite3")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT title from core_snapshot")
    snapshot = c.fetchone()
    conn.close()

    assert snapshot[0] == "It All Starts with a Humble <textarea>"

def test_title_malformed(tmp_path, process, disable_extractors_dict):
    add_process = subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/malformed.html"],
                                   capture_output=True, env=disable_extractors_dict)

    os.chdir(tmp_path)
    conn = sqlite3.connect("index.sqlite3")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT title from core_snapshot")
    snapshot = c.fetchone()
    conn.close()

    assert snapshot[0] == "malformed document"
