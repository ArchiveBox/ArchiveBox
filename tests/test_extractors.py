from .fixtures import *
import json as pyjson
from archivebox.extractors import ignore_methods, get_default_archive_methods, should_save_title

def test_wget_broken_pipe(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_WGET": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                 capture_output=True, env=disable_extractors_dict)
    assert "TypeError chmod_file(..., path: str) got unexpected NoneType argument path=None" not in add_process.stdout.decode("utf-8")

def test_ignore_methods():
    """
    Takes the passed method out of the default methods list and returns that value
    """
    ignored = ignore_methods(['title'])
    assert "title" not in ignored

def test_save_allowdenylist_works(tmp_path, process, disable_extractors_dict):
    allow_list = {
        r'/static': ["headers", "singlefile"],
        r'example\.com\.html$': ["headers"],
    }
    deny_list = {
        "/static": ["singlefile"],
    }
    disable_extractors_dict.update({
        "SAVE_HEADERS": "true",
        "USE_SINGLEFILE": "true",
        "SAVE_ALLOWLIST": pyjson.dumps(allow_list),
        "SAVE_DENYLIST": pyjson.dumps(deny_list),
    })
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict) 
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]
    singlefile_file = archived_item_path / "singlefile.html"
    assert not singlefile_file.exists()
    headers_file = archived_item_path / "headers.json"
    assert headers_file.exists()

def test_save_denylist_works(tmp_path, process, disable_extractors_dict):
    deny_list = {
        "/static": ["singlefile"],
    }
    disable_extractors_dict.update({
        "SAVE_HEADERS": "true",
        "USE_SINGLEFILE": "true",
        "SAVE_DENYLIST": pyjson.dumps(deny_list),
    })
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict) 
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]
    singlefile_file = archived_item_path / "singlefile.html"
    assert not singlefile_file.exists()
    headers_file = archived_item_path / "headers.json"
    assert headers_file.exists()

def test_singlefile_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_SINGLEFILE": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]
    output_file = archived_item_path / "singlefile.html" 
    assert output_file.exists()

def test_readability_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_READABILITY": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "readability" / "content.html"
    assert output_file.exists()

def test_mercury_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_MERCURY": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "mercury" / "content.html"
    assert output_file.exists()

def test_htmltotext_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_HTMLTOTEXT": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "htmltotext.txt"
    assert output_file.exists()

def test_readability_works_with_wget(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_READABILITY": "true", "USE_WGET": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "readability" / "content.html"
    assert output_file.exists()

def test_readability_works_with_singlefile(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_READABILITY": "true", "USE_SINGLEFILE": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "readability" / "content.html"
    assert output_file.exists()

def test_readability_works_with_dom(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_READABILITY": "true", "SAVE_DOM": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "readability" / "content.html"
    assert output_file.exists()

def test_use_node_false_disables_readability_and_singlefile(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_READABILITY": "true", "SAVE_DOM": "true", "USE_SINGLEFILE": "true", "USE_NODE": "false"}) 
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    output_str = add_process.stdout.decode("utf-8")
    assert "> singlefile" not in output_str
    assert "> readability" not in output_str

def test_headers_ignored(tmp_path, process, disable_extractors_dict):
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/headers/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "headers.json"
    assert not output_file.exists()

def test_headers_retrieved(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_HEADERS": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/headers/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "headers.json"
    assert output_file.exists()
    headers_file = archived_item_path / 'headers.json'
    with open(headers_file, 'r', encoding='utf-8') as f:
        headers = pyjson.load(f)
    assert headers['Content-Language'] == 'en'
    assert headers['Content-Script-Type'] == 'text/javascript'
    assert headers['Content-Style-Type'] == 'text/css'

def test_headers_redirect_chain(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_HEADERS": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/redirect/headers/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "headers.json" 
    with open(output_file, 'r', encoding='utf-8') as f:
        headers = pyjson.load(f)
    assert headers['Content-Language'] == 'en'
    assert headers['Content-Script-Type'] == 'text/javascript'
    assert headers['Content-Style-Type'] == 'text/css'

def test_headers_400_plus(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_HEADERS": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/400/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob("archive/**/*"))[0]
    output_file = archived_item_path / "headers.json" 
    with open(output_file, 'r', encoding='utf-8') as f:
        headers = pyjson.load(f)
    assert headers["Status-Code"] == "200"
