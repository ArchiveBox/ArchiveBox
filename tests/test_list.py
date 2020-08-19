import json

from .fixtures import *

def test_list_json(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--json"], capture_output=True)
    output_json = json.loads(list_process.stdout.decode("utf-8"))
    assert output_json[0]["url"] == "http://127.0.0.1:8080/static/example.com.html"


def test_list_json_index(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "http://127.0.0.1:8080/static/example.com.html", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--json", "--index"], capture_output=True)
    output_json = json.loads(list_process.stdout.decode("utf-8"))
    assert output_json["links"][0]["url"] == "http://127.0.0.1:8080/static/example.com.html"
