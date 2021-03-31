import json

from .fixtures import *

def test_list_json(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--json"], capture_output=True)
    output_json = json.loads(list_process.stdout.decode("utf-8"))
    assert output_json[0]["url"] == "http://127.0.0.1:8080/static/example.com.html"


def test_list_json_headers(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--json", "--with-headers"], capture_output=True)
    output_json = json.loads(list_process.stdout.decode("utf-8"))
    assert output_json["links"][0]["url"] == "http://127.0.0.1:8080/static/example.com.html"

def test_list_html(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--html"], capture_output=True)
    output_html = list_process.stdout.decode("utf-8")
    assert "<footer>" not in output_html
    assert "http://127.0.0.1:8080/static/example.com.html" in output_html

def test_list_html_headers(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--html", "--with-headers"], capture_output=True)
    output_html = list_process.stdout.decode("utf-8")
    assert "<footer>" in output_html
    assert "http://127.0.0.1:8080/static/example.com.html" in output_html

def test_list_csv(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--csv", "url"], capture_output=True)
    output_csv = list_process.stdout.decode("utf-8")
    assert "http://127.0.0.1:8080/static/example.com.html" in output_csv

def test_list_csv_headers(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--csv", "url", "--with-headers"], capture_output=True)
    output_csv = list_process.stdout.decode("utf-8")
    assert "http://127.0.0.1:8080/static/example.com.html" in output_csv
    assert "url" in output_csv

def test_list_index_with_wrong_flags(process):
    list_process = subprocess.run(["archivebox", "list", "--with-headers"], capture_output=True)
    assert "--with-headers can only be used with --json, --html or --csv options" in list_process.stderr.decode("utf-8")

def test_link_sort_by_url(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/iana.org.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)

    list_process = subprocess.run(["archivebox", "list"], capture_output=True)
    link_list = list_process.stdout.decode("utf-8").split("\n")
    assert "http://127.0.0.1:8080/static/iana.org.html" in link_list[0]

    list_process = subprocess.run(["archivebox", "list", "--sort=url"], capture_output=True)
    link_list = list_process.stdout.decode("utf-8").split("\n")
    assert "http://127.0.0.1:8080/static/example.com.html" in link_list[0]
