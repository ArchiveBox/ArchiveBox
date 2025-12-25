# archivebox init
# archivebox add

import os
import subprocess
from pathlib import Path
import json, shutil
import sqlite3

from archivebox.config.common import STORAGE_CONFIG

from .fixtures import *

DIR_PERMISSIONS = STORAGE_CONFIG.OUTPUT_PERMISSIONS.replace('6', '7').replace('4', '5')

def test_init(tmp_path, process):
    assert "Initializing a new ArchiveBox" in process.stdout.decode("utf-8")

def test_update(tmp_path, process):
    os.chdir(tmp_path)
    update_process = subprocess.run(['archivebox', 'init'], capture_output=True)
    assert "updating existing ArchiveBox" in update_process.stdout.decode("utf-8")

def test_add_link(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    add_process = subprocess.run(['archivebox', 'add', '--index-only', 'https://example.com'],
                                  capture_output=True, env=disable_extractors_dict)

    # In the new architecture, URLs are saved to source files
    # Check that a source file was created with the URL
    sources_dir = tmp_path / "sources"
    assert sources_dir.exists(), "Sources directory should be created"
    source_files = list(sources_dir.glob("*cli_add.txt"))
    assert len(source_files) >= 1, "Source file should be created"
    source_content = source_files[0].read_text()
    assert "https://example.com" in source_content


def test_add_multiple_urls(tmp_path, process, disable_extractors_dict):
    """Test adding multiple URLs via command line arguments"""
    os.chdir(tmp_path)
    add_process = subprocess.run(['archivebox', 'add', '--index-only', 'https://example.com', 'https://iana.org'],
                                  capture_output=True, env=disable_extractors_dict)

    # Check that a source file was created with both URLs
    sources_dir = tmp_path / "sources"
    assert sources_dir.exists(), "Sources directory should be created"
    source_files = list(sources_dir.glob("*cli_add.txt"))
    assert len(source_files) >= 1, "Source file should be created"
    source_content = source_files[-1].read_text()
    assert "https://example.com" in source_content
    assert "https://iana.org" in source_content

def test_correct_permissions_output_folder(tmp_path, process):
    index_files = ['index.sqlite3', 'archive']
    for file in index_files:
        file_path = tmp_path / file
        assert oct(file_path.stat().st_mode)[-3:] in (STORAGE_CONFIG.OUTPUT_PERMISSIONS, DIR_PERMISSIONS)

def test_correct_permissions_add_command_results(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    add_process = subprocess.run(['archivebox', 'add', '--index-only', 'https://example.com'], capture_output=True,
                                  env=disable_extractors_dict)

    # Check database permissions
    assert oct((tmp_path / "index.sqlite3").stat().st_mode)[-3:] in (STORAGE_CONFIG.OUTPUT_PERMISSIONS, DIR_PERMISSIONS)

def test_collision_urls_different_timestamps(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'add', '--index-only', 'https://example.com'], capture_output=True,
                     env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', '--index-only', 'https://iana.org'], capture_output=True,
                     env=disable_extractors_dict)

    # Check both URLs are in database
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert count == 2

def test_unrecognized_folders(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'add', '--index-only', 'https://example.com'], capture_output=True,
                     env=disable_extractors_dict)
    (tmp_path / "archive" / "some_random_folder").mkdir(parents=True, exist_ok=True)

    init_process = subprocess.run(['archivebox', 'init'], capture_output=True, env=disable_extractors_dict)
    # Just check that init completes successfully
    assert init_process.returncode == 0
