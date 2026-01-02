from .fixtures import *
import json as pyjson


def test_singlefile_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_SINGLEFILE": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'https://example.com'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]
    output_file = archived_item_path / "singlefile.html"
    assert output_file.exists()

def test_readability_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_READABILITY": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'https://example.com'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "readability" / "content.html"
    assert output_file.exists()

def test_htmltotext_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_HTMLTOTEXT": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'https://example.com'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "htmltotext.txt"
    assert output_file.exists()

def test_use_node_false_disables_readability_and_singlefile(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_READABILITY": "true", "SAVE_DOM": "true", "USE_SINGLEFILE": "true", "USE_NODE": "false"})
    add_process = subprocess.run(['archivebox', 'add', 'https://example.com'],
                                  capture_output=True, env=disable_extractors_dict)
    output_str = add_process.stdout.decode("utf-8")
    assert "> singlefile" not in output_str
    assert "> readability" not in output_str

def test_headers_retrieved(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_HEADERS": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'https://example.com'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "headers.json"
    assert output_file.exists()
    with open(output_file, 'r', encoding='utf-8') as f:
        headers = pyjson.load(f)
    assert 'Content-Type' in headers or 'content-type' in headers
