import os
import sqlite3

from .fixtures import *

def test_title_is_extracted(tmp_path, process, disable_extractors_dict):
    """Test that title is extracted from the page."""
    disable_extractors_dict.update({"SAVE_TITLE": "true"})
    subprocess.run(['archivebox', 'add', 'https://example.com'],
                                 capture_output=True, env=disable_extractors_dict)

    os.chdir(tmp_path)
    conn = sqlite3.connect("index.sqlite3")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT title from archivebox.core.snapshot")
    snapshot = c.fetchone()
    conn.close()

    assert snapshot[0] is not None
    assert "Example" in snapshot[0]

def test_title_is_htmlencoded_in_index_html(tmp_path, process, disable_extractors_dict):
    """
    https://github.com/ArchiveBox/ArchiveBox/issues/330
    Unencoded content should not be rendered as it facilitates xss injections
    and breaks the layout.
    """
    disable_extractors_dict.update({"SAVE_TITLE": "true"})
    subprocess.run(['archivebox', 'add', 'https://example.com'],
                                 capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--html"], capture_output=True)

    # Should not contain unescaped HTML tags in output
    output = list_process.stdout.decode("utf-8")
    assert "https://example.com" in output
