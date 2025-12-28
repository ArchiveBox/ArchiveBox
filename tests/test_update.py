import sqlite3

from .fixtures import *

def test_update_imports_orphaned_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that archivebox update imports orphaned snapshot directories."""
    # Add a snapshot
    subprocess.run(['archivebox', 'add', 'https://example.com'], capture_output=True, env=disable_extractors_dict)
    assert list((tmp_path / "archive").iterdir()) != []

    # Remove from DB but leave directory intact
    subprocess.run(['archivebox', 'remove', 'https://example.com', '--yes'], capture_output=True)

    # Verify snapshot removed from DB
    conn = sqlite3.connect(str(tmp_path / "index.sqlite3"))
    c = conn.cursor()
    link = c.execute("SELECT * FROM core_snapshot").fetchone()
    conn.commit()
    conn.close()

    assert link is None

    # Run update without filters - should scan filesystem and import orphaned directory
    update_process = subprocess.run(['archivebox', 'update'], capture_output=True, env=disable_extractors_dict)

    # Verify snapshot was re-imported from orphaned directory
    conn = sqlite3.connect(str(tmp_path / "index.sqlite3"))
    c = conn.cursor()
    url = c.execute("SELECT url FROM core_snapshot").fetchone()[0]
    conn.commit()
    conn.close()

    assert url == 'https://example.com'
