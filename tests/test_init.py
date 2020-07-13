# archivebox init
# archivebox add

import os
import subprocess
from pathlib import Path
import json

from .fixtures import *

def test_init(tmp_path, process):
    assert "Initializing a new ArchiveBox collection in this folder..." in process.stdout.decode("utf-8")
    
def test_update(tmp_path, process):
    os.chdir(tmp_path)
    update_process = subprocess.run(['archivebox', 'init'], capture_output=True)
    assert "Updating existing ArchiveBox collection in this folder" in update_process.stdout.decode("utf-8")

def test_add_link(tmp_path, process):
    os.chdir(tmp_path)
    add_process = subprocess.run(['archivebox', 'add', 'http://localhost:8080/static/example.com.html'], capture_output=True)
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]

    assert "index.json" in [x.name for x in archived_item_path.iterdir()]

    with open(archived_item_path / "index.json", "r") as f:
        output_json = json.load(f)
    assert "Example Domain" == output_json['history']['title'][0]['output']

    with open(tmp_path / "index.html", "r") as f:
        output_html = f.read()
    assert "Example Domain" in output_html

def test_add_link_support_stdin(tmp_path, process):
    os.chdir(tmp_path)
    stdin_process = subprocess.Popen(["archivebox", "add"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdin_process.communicate(input="http://localhost:8080/static/example.com.html".encode())
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]

    assert "index.json" in [x.name for x in archived_item_path.iterdir()]

    with open(archived_item_path / "index.json", "r") as f:
        output_json = json.load(f)
    assert "Example Domain" == output_json['history']['title'][0]['output']

