import subprocess
import json
import sqlite3

from .fixtures import *

def test_depth_flag_is_accepted(process, disable_extractors_dict):
    arg_process = subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    assert 'unrecognized arguments: --depth' not in arg_process.stderr.decode("utf-8")


def test_depth_flag_fails_if_it_is_not_0_or_1(process, disable_extractors_dict):
    arg_process = subprocess.run(
        ["archivebox", "add", "--depth=5", "http://127.0.0.1:8080/static/example.com.html"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    assert 'invalid choice' in arg_process.stderr.decode("utf-8")
    arg_process = subprocess.run(
        ["archivebox", "add", "--depth=-1", "http://127.0.0.1:8080/static/example.com.html"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    assert 'invalid choice' in arg_process.stderr.decode("utf-8")


def test_depth_flag_0_crawls_only_the_arg_page(tmp_path, process, disable_extractors_dict):
    arg_process = subprocess.run(
        ["archivebox", "add", "--depth=0", "http://127.0.0.1:8080/static/example.com.html"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]
    with open(archived_item_path / "index.json", "r", encoding='utf-8') as f:
        output_json = json.load(f)
    assert output_json["base_url"] == "127.0.0.1:8080/static/example.com.html"


def test_depth_flag_1_crawls_the_page_AND_links(tmp_path, process, disable_extractors_dict):
    arg_process = subprocess.run(
        ["archivebox", "add", "--depth=1", "http://127.0.0.1:8080/static/example.com.html"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    urls = c.execute("SELECT url from core_snapshot").fetchall()
    conn.commit()
    conn.close()

    urls = list(map(lambda x: x[0], urls))
    assert "http://127.0.0.1:8080/static/example.com.html" in urls 
    assert "http://127.0.0.1:8080/static/iana.org.html" in urls


def test_overwrite_flag_is_accepted(process, disable_extractors_dict):
    subprocess.run(
        ["archivebox", "add", "--depth=0", "http://127.0.0.1:8080/static/example.com.html"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    arg_process = subprocess.run(
        ["archivebox", "add", "--overwrite", "http://127.0.0.1:8080/static/example.com.html"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    assert 'unrecognized arguments: --overwrite' not in arg_process.stderr.decode("utf-8")
    assert 'favicon' in arg_process.stdout.decode('utf-8'), 'archive methods probably didnt run, did overwrite work?'

def test_add_updates_history_json_index(tmp_path, process, disable_extractors_dict):
    subprocess.run(
        ["archivebox", "add", "--depth=0", "http://127.0.0.1:8080/static/example.com.html"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]

    with open(archived_item_path / "index.json", "r", encoding="utf-8") as f:
        output_json = json.load(f)
    assert output_json["history"] != {}

def test_extract_input_uses_only_passed_extractors(tmp_path, process):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--extract", "wget"],
                    capture_output=True)
    
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]

    assert (archived_item_path / "warc").exists()
    assert not (archived_item_path / "singlefile.html").exists()

def test_json(tmp_path, process, disable_extractors_dict):
    with open('../../mock_server/templates/example.json', 'r', encoding='utf-8') as f:
        arg_process = subprocess.run(
            ["archivebox", "add", "--index-only", "--parser=json"],
            stdin=f,
            capture_output=True,
            env=disable_extractors_dict,
        )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    urls = c.execute("SELECT url from core_snapshot").fetchall()
    tags = c.execute("SELECT name from core_tag").fetchall()
    conn.commit()
    conn.close()

    urls = list(map(lambda x: x[0], urls))
    assert "http://127.0.0.1:8080/static/example.com.html" in urls
    assert "http://127.0.0.1:8080/static/iana.org.html" in urls
    assert "http://127.0.0.1:8080/static/shift_jis.html" in urls
    assert "http://127.0.0.1:8080/static/title_og_with_html" in urls
    # if the following URL appears, we must have fallen back to another parser
    assert not "http://www.example.com/should-not-exist" in urls

    tags = list(map(lambda x: x[0], tags))
    assert "Tag1" in tags
    assert "Tag2" in tags
    assert "Tag3" in tags
    assert "Tag4 with Space" in tags
    assert "Tag5" in tags
    assert "Tag6 with Space" in tags

def test_json_with_leading_garbage(tmp_path, process, disable_extractors_dict):
    with open('../../mock_server/templates/example.json.bad', 'r', encoding='utf-8') as f:
        arg_process = subprocess.run(
            ["archivebox", "add", "--index-only", "--parser=json"],
            stdin=f,
            capture_output=True,
            env=disable_extractors_dict,
        )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    urls = c.execute("SELECT url from core_snapshot").fetchall()
    tags = c.execute("SELECT name from core_tag").fetchall()
    conn.commit()
    conn.close()

    urls = list(map(lambda x: x[0], urls))
    assert "http://127.0.0.1:8080/static/example.com.html" in urls
    # if the following URL appears, we must have fallen back to another parser
    assert not "http://www.example.com/should-not-exist" in urls

    tags = list(map(lambda x: x[0], tags))
    assert "Tag1" in tags
    assert "Tag2" in tags

def test_generic_rss(tmp_path, process, disable_extractors_dict):
    with open('../../mock_server/templates/example.rss', 'r', encoding='utf-8') as f:
        arg_process = subprocess.run(
            ["archivebox", "add", "--index-only", "--parser=rss"],
            stdin=f,
            capture_output=True,
            env=disable_extractors_dict,
        )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    urls = c.execute("SELECT url from core_snapshot").fetchall()
    tags = c.execute("SELECT name from core_tag").fetchall()
    conn.commit()
    conn.close()

    urls = list(map(lambda x: x[0], urls))
    assert "http://127.0.0.1:8080/static/example.com.html" in urls
    # if the following URL appears, we must have fallen back to another parser
    assert not "http://purl.org/dc/elements/1.1/" in urls

    tags = list(map(lambda x: x[0], tags))
    assert "Tag1 Tag2" in tags

def test_pinboard_rss(tmp_path, process, disable_extractors_dict):
    with open('../../mock_server/templates/example.rss', 'r', encoding='utf-8') as f:
        arg_process = subprocess.run(
            ["archivebox", "add", "--index-only", "--parser=pinboard_rss"],
            stdin=f,
            capture_output=True,
            env=disable_extractors_dict,
        )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    tags = c.execute("SELECT name from core_tag").fetchall()
    conn.commit()
    conn.close()

    tags = list(map(lambda x: x[0], tags))
    assert "Tag1" in tags
    assert "Tag2" in tags

def test_atom(tmp_path, process, disable_extractors_dict):
    with open('../../mock_server/templates/example.atom', 'r', encoding='utf-8') as f:
        arg_process = subprocess.run(
            ["archivebox", "add", "--index-only", "--parser=rss"],
            stdin=f,
            capture_output=True,
            env=disable_extractors_dict,
        )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    urls = c.execute("SELECT url from core_snapshot").fetchall()
    tags = c.execute("SELECT name from core_tag").fetchall()
    conn.commit()
    conn.close()

    urls = list(map(lambda x: x[0], urls))
    assert "http://127.0.0.1:8080/static/example.com.html" in urls
    # if the following URL appears, we must have fallen back to another parser
    assert not "http://www.w3.org/2005/Atom" in urls

    tags = list(map(lambda x: x[0], tags))
    assert "Tag1" in tags
    assert "Tag2" in tags

def test_jsonl(tmp_path, process, disable_extractors_dict):
    with open('../../mock_server/templates/example.jsonl', 'r', encoding='utf-8') as f:
        arg_process = subprocess.run(
            ["archivebox", "add", "--index-only", "--parser=jsonl"],
            stdin=f,
            capture_output=True,
            env=disable_extractors_dict,
        )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    urls = c.execute("SELECT url from core_snapshot").fetchall()
    tags = c.execute("SELECT name from core_tag").fetchall()
    conn.commit()
    conn.close()

    urls = list(map(lambda x: x[0], urls))
    assert "http://127.0.0.1:8080/static/example.com.html" in urls
    assert "http://127.0.0.1:8080/static/iana.org.html" in urls
    assert "http://127.0.0.1:8080/static/shift_jis.html" in urls
    assert "http://127.0.0.1:8080/static/title_og_with_html" in urls
    # if the following URL appears, we must have fallen back to another parser
    assert not "http://www.example.com/should-not-exist" in urls

    tags = list(map(lambda x: x[0], tags))
    assert "Tag1" in tags
    assert "Tag2" in tags
    assert "Tag3" in tags
    assert "Tag4 with Space" in tags
    assert "Tag5" in tags
    assert "Tag6 with Space" in tags

def test_jsonl_single(tmp_path, process, disable_extractors_dict):
    with open('../../mock_server/templates/example-single.jsonl', 'r', encoding='utf-8') as f:
        arg_process = subprocess.run(
            ["archivebox", "add", "--index-only", "--parser=jsonl"],
            stdin=f,
            capture_output=True,
            env=disable_extractors_dict,
        )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    urls = c.execute("SELECT url from core_snapshot").fetchall()
    tags = c.execute("SELECT name from core_tag").fetchall()
    conn.commit()
    conn.close()

    urls = list(map(lambda x: x[0], urls))
    assert "http://127.0.0.1:8080/static/example.com.html" in urls
    # if the following URL appears, we must have fallen back to another parser
    assert not "http://www.example.com/should-not-exist" in urls

    tags = list(map(lambda x: x[0], tags))
    assert "Tag1" in tags
    assert "Tag2" in tags

# make sure that JSON parser rejects a single line of JSONL which is valid
# JSON but not our expected format
def test_json_single(tmp_path, process, disable_extractors_dict):
    with open('../../mock_server/templates/example-single.jsonl', 'r', encoding='utf-8') as f:
        arg_process = subprocess.run(
            ["archivebox", "add", "--index-only", "--parser=json"],
            stdin=f,
            capture_output=True,
            env=disable_extractors_dict,
        )

    assert 'expects list of objects' in arg_process.stderr.decode("utf-8")
