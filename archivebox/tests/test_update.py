import json
import sqlite3
import subprocess

from .fixtures import disable_extractors_dict, process

FIXTURES = (disable_extractors_dict, process)

def test_update_imports_orphaned_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that archivebox update imports real legacy archive directories."""
    legacy_timestamp = '1710000000'
    legacy_dir = tmp_path / 'archive' / legacy_timestamp
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / 'singlefile.html').write_text('<html>example</html>')
    (legacy_dir / 'index.json').write_text(json.dumps({
        'url': 'https://example.com',
        'timestamp': legacy_timestamp,
        'title': 'Example Domain',
        'fs_version': '0.8.0',
        'archive_results': [],
    }))

    # Run update without filters - should import and migrate the legacy directory.
    update_process = subprocess.run(
        ['archivebox', 'update'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
        timeout=60,
    )
    assert update_process.returncode == 0, update_process.stderr

    conn = sqlite3.connect(str(tmp_path / "index.sqlite3"))
    c = conn.cursor()
    row = c.execute("SELECT url, fs_version FROM core_snapshot").fetchone()
    conn.commit()
    conn.close()

    assert row == ('https://example.com', '0.9.0')
    assert legacy_dir.is_symlink()

    migrated_dir = legacy_dir.resolve()
    assert migrated_dir.exists()
    assert (migrated_dir / 'index.jsonl').exists()
    assert (migrated_dir / 'singlefile.html').exists()
